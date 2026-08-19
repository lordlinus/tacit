"""tacit CLI: provision, seed, query, dream, and benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .config import Settings, build_service, load_settings
from .ontology import KINDS

app = typer.Typer(help="Shared team memory for AI agents on Azure AI Search.", no_args_is_help=True)


def _settings(project: str = "", search_endpoint: str = "", team: str = "") -> Settings:
    settings = load_settings(project=project, search_endpoint=search_endpoint, team=team)
    settings.require("search_endpoint")
    return settings


_PROJECT_OPT = typer.Option("", help="Project slug (the repo this memory belongs to)")
_ENDPOINT_OPT = typer.Option("", help="Azure AI Search endpoint (default from TACIT_SEARCH_ENDPOINT)")
_TEAM_OPT = typer.Option("", help="Owning team (default from TACIT_TEAM)")


@app.command()
def provision(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Create the shared organization-wide indexes (idempotent).

    Run once per Azure AI Search service, not once per team: every project
    writes into the same index set, which is what lets one team's memory answer
    another team's question."""
    from .azure_common import build_credential
    from .search_index import provision as provision_indexes

    settings = _settings(project=project, search_endpoint=search_endpoint)
    credential = build_credential(settings.auth_mode, settings.tenant_id)
    typer.echo("provisioned indexes: " + ", ".join(provision_indexes(settings, credential)))
    if settings.vectors_enabled:
        typer.echo(
            f"hybrid retrieval ON: {settings.embedding_deployment} "
            f"({settings.embedding_dimensions}d) — run `tacit reindex` to embed "
            "memories stored before now"
        )
    else:
        typer.echo(
            "hybrid retrieval OFF (keyword + semantic only) — set "
            "TACIT_EMBEDDING_ENDPOINT to add vector search"
        )


@app.command()
def reindex(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Rebuild the chunks index from the memories index.

    Run this after changing the shared vocabulary, or after turning on an
    embedding deployment: entity annotations and vectors are both written onto
    chunks, so memories stored earlier keep their old ones until re-projected.
    Re-running is harmless — chunk keys are derived from project + path +
    section slug, so it converges."""
    settings = _settings(project=project, search_endpoint=search_endpoint)
    count = build_service(settings).reindex()
    mode = "with embeddings" if settings.vectors_enabled else "text only"
    typer.echo(f"reindexed {count} memories ({mode})")


@app.command()
def add(
    path: str = typer.Argument(..., help="Memory path, e.g. /gotchas/vpn-dns.md"),
    content: str = typer.Option("", help="Markdown body starting with '# Title' (or use --file / stdin)"),
    file: Path = typer.Option(None, help="Read the body from a markdown file"),
    category: str = typer.Option("general", help="onboarding|gotcha|architecture|convention|general"),
    tags: str = typer.Option("", help="Comma-separated tags"),
    visibility: str = typer.Option(
        "", help="org (default) | team | private — who outside this project may read it"
    ),
    project: str = _PROJECT_OPT,
    team: str = _TEAM_OPT,
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
    service = build_service(_settings(project, search_endpoint, team))
    try:
        memory = service.create(
            path,
            body,
            category=category,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            visibility=visibility or None,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--visibility") from exc
    typer.echo(
        f"+ {memory.path} (v{memory.version}, {memory.category}, {memory.visibility}) "
        f"'{memory.title}'"
    )


@app.command()
def seed(
    directory: Path = typer.Argument(..., help="Folder of .md memories (frontmatter: path/category/tags)"),
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Load a folder of markdown memories into the store."""
    service = build_service(_settings(project, search_endpoint))
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
    scope: str = typer.Option(
        "", help="project | project+org (default) | org — how far across the org to look"
    ),
    project: str = _PROJECT_OPT,
    team: str = _TEAM_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Search the organization's memory (what an agent's memory_search returns)."""
    service = build_service(_settings(project, search_endpoint, team))
    try:
        hits = service.search(query, top=top, scope=scope or None)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--scope") from exc
    if not hits:
        typer.echo("no hits")
        raise typer.Exit(0)
    for hit in hits:
        origin = "" if hit.project == service.project else f"  [from {hit.project}]"
        typer.echo(f"--- {hit.path}  (score {hit.score}, {hit.category}){origin}")
        typer.echo(hit.content.rstrip("\n"))


@app.command()
def read(
    path: str,
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Read one memory in full (shows content_sha256 for updates)."""
    service = build_service(_settings(project, search_endpoint))
    memory = service.read(path)
    typer.echo(json.dumps(
        {"path": memory.path, "version": memory.version, "content_sha256": memory.content_sha256},
    ))
    typer.echo(memory.content.rstrip("\n"))


@app.command()
def brief(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Print the onboarding pack (all 'onboarding'-category memories)."""
    service = build_service(_settings(project, search_endpoint))
    typer.echo(service.brief())


@app.command()
def dream(
    output_project: str = typer.Option(..., help="Fresh project slug for the curated output store"),
    transcripts: Path = typer.Option(None, help="Folder of session transcripts (.md/.txt/.jsonl)"),
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Curate the store into a NEW store: dedupe, supersede stale facts, mine
    transcripts for insights. The input store is never modified."""
    from .azure_common import build_credential
    from .dream import dream as run_dream
    from .dream import load_transcripts
    from .search_index import provision as provision_indexes

    settings = _settings(project, search_endpoint)
    input_service = build_service(settings)
    output_settings = settings.model_copy(update={"project": output_project})
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
    project: str = typer.Option("bench", help="Throwaway project slug to seed and measure against"),
    out: str = typer.Option("", help="Report path (default benchmark/RESULTS.md)"),
) -> None:
    """Run the token-efficiency benchmark (cold vs warm onboarding).

    Warm hits a live AI Search project, so this needs TACIT_SEARCH_ENDPOINT and
    a signed-in identity. The project is emptied before and after."""
    import sys

    # The benchmark lives in the repo (it depends on samples/), not the
    # package — resolve it relative to this source tree.
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "benchmark").is_dir():
        raise typer.Exit("bench requires the tacit repo checkout (benchmark/ + samples/)")
    sys.path.insert(0, str(repo_root))
    from benchmark.bench import main as run_bench

    argv = ["--project", project]
    if out:
        argv += ["--out", out]
    run_bench(argv)


@app.command()
def install(
    project: str = typer.Option("default", help="Project slug teammates should join"),
    search_endpoint: str = typer.Option(..., help="Shared AI Search endpoint"),
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
        typer.echo("# THEN, in each repo, they run the `tacit_setup` prompt once —")
        typer.echo("# it writes the standing instructions so their agent uses memory")
        typer.echo("# without being asked. Connecting alone does nothing.\n")
        typer.echo("# Claude Code:\n")
        typer.echo("    export TACIT_KEY=<key>   # then:")
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
    typer.echo("# Add to the project's AGENTS.md / CLAUDE.md so agents actually use it:")
    typer.echo("# (or just run the `tacit_setup` prompt in the repo and let the agent do it)\n")
    typer.echo(clients.agents_md_snippet(project))


@app.command()
def ui(
    port: int = typer.Option(8765, help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", help="Bind address (localhost by default)"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open a browser"),
    project: str = _PROJECT_OPT,
    team: str = _TEAM_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Serve the cross-team overlap graph locally.

    The same page and JSON the deployed Function App serves, but reading through
    your own identity, so a graph can be demoed before anything is deployed.
    Binds to localhost by default — the graph aggregates across every project
    you can see, which is not something to expose on a shared interface."""
    import http.server
    import json as _json
    import threading
    import webbrowser

    from .ui import PAGE

    service = build_service(_settings(project, search_endpoint, team))

    def _search(params: dict) -> list:
        from .tools import call_tool

        query = (params.get("q") or "").strip()
        if not query:
            return []
        try:
            top = max(1, min(int(params.get("top", 8)), 25))
        except ValueError:
            top = 8
        return call_tool(service, "memory_search", {
            "query": query,
            "top": top,
            "scope": params.get("scope") or "",
            "category": params.get("category") or "",
            "entity": params.get("entity") or "",
        })

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            from urllib.parse import parse_qs, urlsplit

            split = urlsplit(self.path)
            route = split.path.rstrip("/") or "/"
            params = {k: v[0] for k, v in parse_qs(split.query).items()}
            if route in ("/", "/ui"):
                self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif route in ("/graph", "/ui/graph"):
                self._json_or_error(
                    lambda: service.graph(params.get("scope") or None)
                )
            elif route in ("/search", "/ui/search"):
                # Through call_tool, so the page sees exactly the hit shape an
                # agent does rather than a second, drifting serialization.
                self._json_or_error(lambda: _search(params))
            else:
                self._send(b"not found", "text/plain", 404)

        def _json_or_error(self, produce) -> None:
            try:
                payload = _json.dumps(produce(), ensure_ascii=False, default=str)
            except Exception as exc:  # noqa: BLE001 - surfaced to the page
                self._send(
                    _json.dumps({"error": str(exc)}).encode("utf-8"),
                    "application/json", 500,
                )
                return
            self._send(payload.encode("utf-8"), "application/json")

        def log_message(self, *args) -> None:
            return  # keep the terminal readable during a demo

    try:
        server = http.server.ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        raise typer.BadParameter(
            f"could not bind {host}:{port} ({exc.strerror}). "
            "Pass a different --port.",
            param_hint="--port",
        ) from exc
    url = f"http://{host}:{port}/"
    stats = service.graph()["stats"]
    typer.echo(
        f"{stats['entities']} entities, {stats['shared_entities']} shared across teams, "
        f"{stats['visible_memories']} memories visible to '{service.project}'"
    )
    if not stats["vocabulary_size"]:
        typer.echo("vocabulary is empty — add entries with `tacit ontology add` for a graph")
    typer.echo(f"serving {url}  (ctrl-c to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nstopped")
    finally:
        server.server_close()


@app.command()
def stats(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Is the team using it? Memories by category, contributor, and recency."""
    from collections import Counter

    service = build_service(_settings(project, search_endpoint))
    memories = service.list("/")
    if not memories:
        typer.echo("store is empty — nothing has been written yet")
        raise typer.Exit(0)
    by_category = Counter(m.category for m in memories)
    by_author = Counter(m.updated_by for m in memories)
    by_visibility = Counter(str(m.visibility) for m in memories)
    newest = max(memories, key=lambda m: m.updated)
    total_versions = sum(m.version for m in memories)
    typer.echo(f"project '{service.project}': {len(memories)} active memories, "
               f"{total_versions} versions written")
    typer.echo("by category: " + ", ".join(f"{k}={v}" for k, v in by_category.most_common()))
    typer.echo("contributors: " + ", ".join(f"{k}={v}" for k, v in by_author.most_common()))
    typer.echo("shared as: " + ", ".join(f"{k}={v}" for k, v in by_visibility.most_common()))
    typer.echo(f"latest write: {newest.path} by {newest.updated_by} at {newest.updated.isoformat()}")


ontology_app = typer.Typer(
    help="Curate the organization's shared vocabulary (canonical names + aliases).",
    no_args_is_help=True,
)
app.add_typer(ontology_app, name="ontology")


@ontology_app.command("list")
def ontology_list(
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Show every canonical entity and the aliases teams actually type."""
    service = build_service(_settings(project, search_endpoint))
    entities = service.ontology().entities
    if not entities:
        typer.echo(
            "vocabulary is empty — add entries with `tacit ontology add`, or "
            "import a file with `tacit ontology import`"
        )
        raise typer.Exit(0)
    for entity in sorted(entities, key=lambda e: e.id):
        aliases = ", ".join(entity.aliases) or "(no aliases)"
        typer.echo(f"{entity.id}  [{entity.kind}]  {entity.name}\n    aka: {aliases}")


@ontology_app.command("add")
def ontology_add(
    name: str = typer.Argument(..., help="Canonical name, e.g. 'Payments Gateway'"),
    aliases: str = typer.Option("", help="Comma-separated aliases teams actually type"),
    kind: str = typer.Option(
        "concept", help=f"{'|'.join(KINDS)} (free-form; these are just the common ones)"
    ),
    description: str = typer.Option("", help="One line: what it is"),
    entity_id: str = typer.Option("", "--id", help="Slug (default: derived from the name)"),
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Teach the organization that several names mean one thing.

    Re-running with the same id replaces that entry, so this is also how you
    add an alias to an existing entity."""
    from .ontology import Entity, Ontology, slugify_entity

    service = build_service(_settings(project, search_endpoint))
    current = service.ontology()
    new = Entity(
        id=entity_id or slugify_entity(name),
        name=name,
        aliases=tuple(a.strip() for a in aliases.split(",") if a.strip()),
        kind=kind,
        description=description,
    )
    kept = [e for e in current.entities if e.id != new.id]
    count = service.set_ontology(Ontology(entities=[*kept, new]))
    typer.echo(f"+ {new.id} ({new.kind}) '{new.name}' — {len(new.aliases)} alias(es)")
    typer.echo(f"vocabulary now holds {count} entities")
    typer.echo("run `tacit reindex` to apply it to memories already stored")


@ontology_app.command("remove")
def ontology_remove(
    entity_id: str = typer.Argument(..., help="Entity id to drop"),
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Drop one entity from the vocabulary."""
    from .ontology import Ontology

    service = build_service(_settings(project, search_endpoint))
    current = service.ontology()
    if current.get(entity_id) is None:
        typer.echo(f"no entity {entity_id!r} in the vocabulary")
        raise typer.Exit(1)
    kept = [e for e in current.entities if e.id != entity_id]
    service.set_ontology(Ontology(entities=kept))
    typer.echo(f"- {entity_id}\nrun `tacit reindex` to apply it")


@ontology_app.command("import")
def ontology_import(
    file: Path = typer.Argument(..., help="JSON: {'entities':[{id,name,aliases,kind}]}"),
    replace: bool = typer.Option(False, help="Replace the vocabulary instead of merging"),
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Load a vocabulary file (merges by id unless --replace)."""
    from .ontology import Ontology

    service = build_service(_settings(project, search_endpoint))
    incoming = Ontology.from_dict(json.loads(file.read_text(encoding="utf-8")))
    if replace:
        merged = incoming.entities
    else:
        incoming_ids = {e.id for e in incoming.entities}
        merged = [e for e in service.ontology().entities if e.id not in incoming_ids]
        merged += incoming.entities
    count = service.set_ontology(Ontology(entities=merged))
    typer.echo(f"vocabulary now holds {count} entities")
    typer.echo("run `tacit reindex` to apply it to memories already stored")


@ontology_app.command("export")
def ontology_export(
    out: Path = typer.Option(None, help="Write here instead of stdout"),
    project: str = _PROJECT_OPT,
    search_endpoint: str = _ENDPOINT_OPT,
) -> None:
    """Dump the vocabulary as JSON (round-trips through `ontology import`)."""
    service = build_service(_settings(project, search_endpoint))
    payload = json.dumps(service.ontology().to_dict(), indent=2, ensure_ascii=False)
    if out is None:
        typer.echo(payload)
    else:
        out.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}")


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
