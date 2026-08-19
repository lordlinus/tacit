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

    # Project slug — the repo/workspace a memory belongs to. One shared index
    # set holds every project; this says which one this process writes to.
    project: str = Field(default="default")

    # Owning team. Purely descriptive for search, but load-bearing for
    # visibility="team" memories, which only this team's projects can read.
    team: str = Field(default="")

    # Visibility stamped on memories that don't ask for one: "org" by default,
    # because knowledge that cannot leave its team is not organizational memory.
    default_visibility: str = Field(default="org")

    # Who mutations are attributed to (defaults to the OS user at runtime).
    actor: str = Field(default="")

    # Azure OpenAI embedding deployment powering the vector half of hybrid
    # search. Optional: leave the endpoint unset and retrieval stays BM25 +
    # semantic reranking, exactly as before.
    embedding_endpoint: str = Field(default="")
    embedding_deployment: str = Field(default="text-embedding-3-small")
    #: The model behind that deployment. Usually the same string, but the
    #: vectorizer needs the model name specifically, and deployments are often
    #: named for their purpose rather than their model.
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dimensions: int = Field(default=1536)

    # Auth: "default-credential" (keyless) or "azure-cli".
    auth_mode: str = Field(default="default-credential")
    tenant_id: str = Field(default="")

    def viewer(self):
        """Who this server is, for permission decisions. Never caller-supplied."""
        from .scope import Viewer

        return Viewer(project=self.project, team=self.team)

    @property
    def vectors_enabled(self) -> bool:
        return bool(self.embedding_endpoint and self.embedding_deployment)

    def embedder(self, credential=None):
        """The embedding client, or None when vectors are not configured."""
        if not self.vectors_enabled:
            return None
        from .azure_common import build_credential
        from .embeddings import Embedder

        return Embedder(
            self.embedding_endpoint,
            self.embedding_deployment,
            credential or build_credential(self.auth_mode, self.tenant_id),
            dimensions=self.embedding_dimensions,
        )

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


def build_service(settings: Settings, viewer=None):
    """Wire a MemoryService onto the shared Azure AI Search index set.

    The store is organization-wide and this service writes into it on behalf of
    one project, so the project is passed to the service rather than baked into
    an index name. ``viewer`` overrides who permission is evaluated against; the
    registry supplies the server's own identity so a routed project cannot
    escalate.
    """
    from .models import Visibility
    from .search_store import SearchStore
    from .service import MemoryService

    resolved_viewer = viewer or settings.viewer()
    settings.require("search_endpoint")
    store = SearchStore(settings, viewer=resolved_viewer)
    return MemoryService(
        store,
        actor=settings.actor,
        project=settings.project,
        team=settings.team,
        default_visibility=Visibility(settings.default_visibility),
        viewer=resolved_viewer,
    )


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
    MCP server (one endpoint) serves many projects.

    The routed project changes *which* memories a call operates on; it never
    changes *what the caller is allowed to see*. Permission is always evaluated
    against the viewer built from this server's own configuration, so naming
    another team's project cannot reveal that team's private memories.
    """

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
            self._services[slug] = build_service(scoped, viewer=self._settings.viewer())
        return self._services[slug]
