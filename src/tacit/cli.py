"""tacit CLI: provision, seed, query, dream, and benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .config import Settings, build_service, load_settings

app = typer.Typer(help="Shared team memory for AI agents on Azure AI Search.", no_args_is_help=True)


def _settings(backend: str = "", project: str = "", search_endpoint: str = "") -> Settings:
    return load_settings(backend=backend, project=project, search_endpoint=search_endpoint)


_BACKEND_OPT = typer.Option("", help="local | search (default from TACIT_BACKEND)")
_PROJECT_OPT = typer.Option("", help="Project slug (one store per project)")
_ENDPOINT_OPT = typer.Option("", help="Azure AI Search endpoint (search backend)")


@app.command()
def provision(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Create the tm-<project> indexes on Azure AI Search (idempotent)."""
    from .azure_common import build_credential
    from .search_index import provision as provision_indexes

    settings = _settings(backend="search", project=project, search_endpoint=search_endpoint)
    settings.require("search_endpoint")
    credential = build_credential(settings.auth_mode, settings.tenant_id)
    typer.echo("provisioned indexes: " + ", ".join(provision_indexes(settings, credential)))


@app.command()
def reindex(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Rebuild the chunks index from the memories index.

    Run once per project provisioned before section-level search; re-running is
    harmless because chunk keys are derived from path + section slug."""
    settings = _settings(backend="search", project=project, search_endpoint=search_endpoint)
    settings.require("search_endpoint")
    count = build_service(settings).reindex()
    typer.echo(f"reindexed {count} memories")


@app.command()
def add(
    path: str = typer.Argument(..., help="Memory path, e.g. /gotchas/vpn-dns.md"),
    content: str = typer.Option("", help="Markdown body starting with '# Title' (or use --file / stdin)"),
    file: Path = typer.Option(None, help="Read the body from a markdown file"),
    category: str = typer.Option("general", help="onboarding|gotcha|architecture|convention|general"),
    tags: str = typer.Option("", help="Comma-separated tags"),
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Store one memory directly — no agent needed. Body comes from --content,
    --file, or stdin (pipe it in)."""
    import sys

    if file is not None:
        body = file.read_text(encoding="utf-8")
    elif content:
        body = content
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        raise typer.BadParameter("provide --content, --file, or pipe the body on stdin")
    service = build_service(_settings(backend, project, search_endpoint))
    memory = service.create(
        path, body, category=category, tags=[t.strip() for t in tags.split(",") if t.strip()]
    )
    typer.echo(f"+ {memory.path} (v{memory.version}, {memory.category}) '{memory.title}'")


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
def bench(
    backend: str = typer.Option("local", help="Warm-arm backend: local (hermetic) or search (live Azure)"),
    project: str = typer.Option("bench", help="Project slug when --backend search"),
    out: str = typer.Option("", help="Report path (default benchmark/RESULTS.md)"),
) -> None:
    """Run the token-efficiency benchmark (cold vs warm onboarding)."""
    import sys

    # The benchmark lives in the repo (it depends on samples/), not the
    # package — resolve it relative to this source tree.
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "benchmark").is_dir():
        raise typer.Exit("bench requires the tacit repo checkout (benchmark/ + samples/)")
    sys.path.insert(0, str(repo_root))
    from benchmark.bench import main as run_bench

    argv = ["--backend", backend, "--project", project]
    if out:
        argv += ["--out", out]
    run_bench(argv)


@app.command()
def install(
    project: str = typer.Option("default", help="Project slug teammates should join"),
    search_endpoint: str = typer.Option("", help="Shared AI Search endpoint (omit for local-only)"),
    function_app: str = typer.Option("", help="Deployed Functions app name (remote MCP variant)"),
) -> None:
    """Print ready-to-paste MCP wiring for every client your team uses.
    With --function-app, leads with the endpoint-only handout (URL + key, no
    clone); the stdio variants follow as the keyless-per-user alternative."""
    from . import clients

    if function_app:
        typer.echo("# ====== HAND THIS TO TEAMMATES: MCP endpoint, nothing to install ======\n")
        typer.echo(f"# Endpoint: {clients.mcp_endpoint(function_app)}")
        typer.echo("# Key (share via your secret channel, never commit it):")
        typer.echo(
            f"#   az functionapp keys list -g <rg> -n {function_app} "
            "--query systemKeys.mcp_extension -o tsv\n"
        )
        typer.echo("# Claude Code:\n")
        typer.echo(f"    export TACIT_KEY=<key>   # then:")
        typer.echo(f"    {clients.claude_code_remote_command(function_app)}\n")
        typer.echo("# VS Code / GitHub Copilot — save as .vscode/mcp.json (prompts for the key):\n")
        typer.echo(clients.functions_http_json(function_app) + "\n")
        typer.echo("# ====== Alternative: local stdio (keyless, per-user Entra identity) ======\n")

    wiring = clients.Wiring(
        repo_dir=str(Path(__file__).resolve().parents[2]),
        search_endpoint=search_endpoint,
        project=project,
    )
    typer.echo("# Claude Code (stdio; needs repo clone + uv + az login):\n")
    typer.echo(f"    {clients.claude_code_command(wiring)}\n")
    typer.echo("# VS Code / GitHub Copilot stdio — .vscode/mcp.json:\n")
    typer.echo(clients.vscode_mcp_json(wiring) + "\n")
    typer.echo("# Copilot CLI — merge into ~/.copilot/mcp-config.json:\n")
    typer.echo(clients.copilot_cli_json(wiring) + "\n")
    typer.echo("# Add to the project's AGENTS.md / CLAUDE.md so agents actually use it:\n")
    typer.echo(clients.agents_md_snippet(project))


@app.command()
def stats(
    backend: str = _BACKEND_OPT,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Is the team using it? Memories by category, contributor, and recency."""
    from collections import Counter

    service = build_service(_settings(backend, project, search_endpoint))
    memories = service.list("/")
    if not memories:
        typer.echo("store is empty — nothing has been written yet")
        raise typer.Exit(0)
    by_category = Counter(m.category for m in memories)
    by_author = Counter(m.updated_by for m in memories)
    newest = max(memories, key=lambda m: m.updated)
    total_versions = sum(m.version for m in memories)
    typer.echo(f"{len(memories)} active memories, {total_versions} versions written")
    typer.echo("by category: " + ", ".join(f"{k}={v}" for k, v in by_category.most_common()))
    typer.echo("contributors: " + ", ".join(f"{k}={v}" for k, v in by_author.most_common()))
    typer.echo(f"latest write: {newest.path} by {newest.updated_by} at {newest.updated.isoformat()}")


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
