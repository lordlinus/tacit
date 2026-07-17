"""Settings: TEAMLORE_* env vars / a local .env. Keyless by design —
there is deliberately no api-key field anywhere."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEAMLORE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure AI Search service hosting the team memory indexes.
    search_endpoint: str = Field(default="")

    # Project slug — one memory store (index pair) per project.
    project: str = Field(default="default")

    # "local" (JSON files under local_root) or "search" (Azure AI Search).
    backend: str = Field(default="local")
    local_root: str = Field(default=".team-lore")

    # Who mutations are attributed to (defaults to the OS user at runtime).
    actor: str = Field(default="")

    # Auth: "default-credential" (keyless) or "azure-cli".
    auth_mode: str = Field(default="default-credential")
    tenant_id: str = Field(default="")

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n, "")]
        if missing:
            pretty = ", ".join(f"TEAMLORE_{n.upper()}" for n in missing)
            raise RuntimeError(f"Missing required configuration: {pretty}.")


def load_settings(**overrides: str) -> Settings:
    settings = Settings()
    for key, value in overrides.items():
        if value:
            setattr(settings, key, value)
    if not settings.actor:
        import getpass

        try:
            settings.actor = getpass.getuser()
        except Exception:  # noqa: BLE001 - containers without a passwd entry
            settings.actor = "unknown"
    return settings


def build_service(settings: Settings):
    """Wire a MemoryService onto the configured backend."""
    from .service import MemoryService

    if settings.backend == "search":
        from .search_store import SearchStore

        settings.require("search_endpoint")
        store = SearchStore(settings)
    else:
        from pathlib import Path

        from .local_store import LocalStore

        store = LocalStore(Path(settings.local_root) / settings.project)
    return MemoryService(store, actor=settings.actor)
