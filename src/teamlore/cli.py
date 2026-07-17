"""team-lore CLI: provision, seed, query, dream, and benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .config import Settings, build_service, load_settings

app = typer.Typer(help="Shared team memory for AI agents on Azure AI Search.", no_args_is_help=True)


def _settings(backend: str = "", project: str = "", search_endpoint: str = "") -> Settings:
    return load_settings(backend=backend, project=project, search_endpoint=search_endpoint)


_BACKEND_OPT = typer.Option("", help="local | search (default from TEAMLORE_BACKEND)")
_PROJECT_OPT = typer.Option("", help="Project slug (one store per project)")
_ENDPOINT_OPT = typer.Option("", help="Azure AI Search endpoint (search backend)")


@app.command()
def provision(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Create the tm-<project> index pair on Azure AI Search (idempotent)."""
    from .azure_common import build_credential
    from .search_index import provision as provision_indexes

    settings = _settings(backend="search", project=project, search_endpoint=search_endpoint)
    settings.require("search_endpoint")
    credential = build_credential(settings.auth_mode, settings.tenant_id)
    memories, versions = provision_indexes(settings, credential)
    typer.echo(f"provisioned indexes: {memories}, {versions}")


@app.command()
def seed(
    directory: Path = typer.Argument(..., help="Folder of .md memories (frontmatter: path/category/tags)"),
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Load a folder of markdown memories into the store."""
    service = build_service(_settings(backend, project, search_endpoint))
    count = 0
    for file in sorted(directory.glob("*.md")):
        meta, content = parse_memory_file(file.read_text(encoding="utf-8"))
        path = meta.get("path") or f"/{file.stem}.md"
        service.create(
            path,
            content,
            category=meta.get("category", "general"),
            tags=[t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        )
        count += 1
        typer.echo(f"  + {path}")
    typer.echo(f"seeded {count} memories")


@app.command()
def search(
    query: str,
    top: int = typer.Option(3, help="Max results"),
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Search the team memory (what an agent's memory_search call returns)."""
    service = build_service(_settings(backend, project, search_endpoint))
    hits = service.search(query, top=top)
    if not hits:
        typer.echo("no hits")
        raise typer.Exit(0)
    for hit in hits:
        typer.echo(f"--- {hit.path}  (score {hit.score}, {hit.category})")
        typer.echo(hit.content.rstrip("\n"))


@app.command()
def read(
    path: str,
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Read one memory in full (shows content_sha256 for updates)."""
    service = build_service(_settings(backend, project, search_endpoint))
    memory = service.read(path)
    typer.echo(json.dumps(
        {"path": memory.path, "version": memory.version, "content_sha256": memory.content_sha256},
    ))
    typer.echo(memory.content.rstrip("\n"))


@app.command()
def brief(
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Print the onboarding pack (all 'onboarding'-category memories)."""
    service = build_service(_settings(backend, project, search_endpoint))
    typer.echo(service.brief())


@app.command()
def dream(
    output_project: str = typer.Option(..., help="Fresh project slug for the curated output store"),
    transcripts: Path = typer.Option(None, help="Folder of session transcripts (.md/.txt/.jsonl)"),
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Curate the store into a NEW store: dedupe, supersede stale facts, mine
    transcripts for insights. The input store is never modified."""
    from .dream import dream as run_dream
    from .dream import load_transcripts

    settings = _settings(backend, project, search_endpoint)
    input_service = build_service(settings)
    output_settings = settings.model_copy(update={"project": output_project})
    if output_settings.backend == "search":
        from .azure_common import build_credential
        from .search_index import provision as provision_indexes

        provision_indexes(output_settings, build_credential(settings.auth_mode, settings.tenant_id))
    output_service = build_service(output_settings)

    texts = load_transcripts(transcripts) if transcripts else []
    report = run_dream(input_service, output_service, transcripts=texts)
    typer.echo(
        f"dream complete -> project '{output_project}': kept {report.kept}, "
        f"merged {report.merged} duplicates, superseded {report.superseded} stale, "
        f"mined {report.mined} new insights"
    )
    for note in report.notes:
        typer.echo(f"  * {note}")


@app.command()
def bench() -> None:
    """Run the token-efficiency benchmark (cold vs warm onboarding)."""
    import sys

    # The benchmark lives in the repo (it depends on samples/), not the
    # package — resolve it relative to this source tree.
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "benchmark").is_dir():
        raise typer.Exit("bench requires the team-lore repo checkout (benchmark/ + samples/)")
    sys.path.insert(0, str(repo_root))
    from benchmark.bench import main as run_bench

    run_bench()


def parse_memory_file(text: str) -> tuple[dict[str, str], str]:
    """Parse optional ``key: value`` frontmatter from a seed .md file."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[end + 5 :].lstrip("\n")


if __name__ == "__main__":
    app()
