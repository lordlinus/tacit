"""Settings: TACIT_* env vars / a local .env. Keyless by design —
there is deliberately no api-key field anywhere."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TACIT_",
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
    local_root: str = Field(default=".tacit")

    # Who mutations are attributed to (defaults to the OS user at runtime).
    actor: str = Field(default="")

    # Auth: "default-credential" (keyless) or "azure-cli".
    auth_mode: str = Field(default="default-credential")
    tenant_id: str = Field(default="")

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n, "")]
        if missing:
            pretty = ", ".join(f"TACIT_{n.upper()}" for n in missing)
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


def slugify_project(name: str) -> str:
    """Folder/repo name -> valid project slug ('Contoso Payments' -> 'contoso-payments')."""
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "default"


def infer_project_from_cwd() -> str:
    """Project slug from the git repo root's (or cwd's) folder name — how the
    stdio server picks the right store when clients spawn it in a workspace."""
    import subprocess
    from pathlib import Path

    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        name = Path(root).name
    except Exception:  # noqa: BLE001 - not a git repo / git missing
        name = Path.cwd().name
    return slugify_project(name)


class ServiceRegistry:
    """One MemoryService per project slug over shared settings — how a single
    MCP server (one endpoint) serves many projects."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._services: dict = {}

    @property
    def default_project(self) -> str:
        return self._settings.project

    def get_service(self, project: str = ""):
        slug = slugify_project(project) if project.strip() else self._settings.project
        if slug not in self._services:
            scoped = self._settings.model_copy(update={"project": slug})
            self._services[slug] = build_service(scoped)
        return self._services[slug]
