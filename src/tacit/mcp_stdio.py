"""Local stdio MCP server over the shared tool surface.

Keyless wiring for engineers working from a clone: the agent spawns
``tacit-mcp`` (stdio — every MCP client speaks it) and DefaultAzureCredential
mints AI Search tokens at runtime, so no secrets ever land in agent config
(same pattern as `foundry-iq mcp`). Each engineer therefore reads and writes
under their own Entra identity, which the shared Functions endpoint cannot do.

Project routing: the default store is inferred from the working directory
(git repo folder name) when TACIT_PROJECT isn't set — MCP clients spawn stdio
servers inside the workspace, so each repo lands in its own store with zero
config. Every tool also takes an optional ``project`` override.

Register in Claude Code:
    claude mcp add tacit -- uv --directory /path/to/tacit run tacit-mcp
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import ServiceRegistry, infer_project_from_cwd, load_settings
from .tools import TOOL_DEFINITIONS, call_tool

mcp = FastMCP(
    "tacit",
    instructions=(
        "Shared team memory for this project. Search it BEFORE exploring the "
        "repo; store durable learnings (gotchas, conventions, decisions) so "
        "the next engineer's agent doesn't relearn them. Tools route by the "
        "optional `project` argument (repo folder name, kebab-case); the "
        "server's default is the directory it was launched in."
    ),
)

_registry: ServiceRegistry | None = None


def get_registry() -> ServiceRegistry:
    global _registry
    if _registry is None:
        settings = load_settings()
        if settings.project == "default":  # not pinned via env/flag -> infer
            settings.project = infer_project_from_cwd()
        _registry = ServiceRegistry(settings)
    return _registry


def _register(name: str) -> None:
    description = TOOL_DEFINITIONS[name][0]

    # Explicit signatures per tool so MCP clients see real parameter schemas.
    if name == "tacit_setup":

        @mcp.tool(name=name, description=description)
        def _setup(project: str = "") -> Any:
            return call_tool(get_registry(), "tacit_setup", {"project": project})

    elif name == "memory_search":

        @mcp.tool(name=name, description=description)
        def _search(
            query: str,
            top: int = 3,
            category: str = "",
            scope: str = "",
            entity: str = "",
            project: str = "",
        ) -> Any:
            return call_tool(
                get_registry(),
                "memory_search",
                {
                    "query": query,
                    "top": top,
                    "category": category,
                    "scope": scope,
                    "entity": entity,
                    "project": project,
                },
            )

    elif name == "memory_brief":

        @mcp.tool(name=name, description=description)
        def _brief(project: str = "") -> Any:
            return call_tool(get_registry(), "memory_brief", {"project": project})

    elif name == "memory_read":

        @mcp.tool(name=name, description=description)
        def _read(path: str, project: str = "") -> Any:
            return call_tool(get_registry(), "memory_read", {"path": path, "project": project})

    elif name == "memory_list":

        @mcp.tool(name=name, description=description)
        def _list(prefix: str = "/", project: str = "") -> Any:
            return call_tool(get_registry(), "memory_list", {"prefix": prefix, "project": project})

    elif name == "memory_create":

        @mcp.tool(name=name, description=description)
        def _create(
            path: str,
            content: str,
            category: str = "general",
            tags: str = "",
            visibility: str = "",
            project: str = "",
        ) -> Any:
            return call_tool(
                get_registry(),
                "memory_create",
                {
                    "path": path,
                    "content": content,
                    "category": category,
                    "tags": tags,
                    "visibility": visibility,
                    "project": project,
                },
            )

    elif name == "memory_update":

        @mcp.tool(name=name, description=description)
        def _update(
            path: str,
            expected_sha256: str,
            content: str,
            visibility: str = "",
            project: str = "",
        ) -> Any:
            return call_tool(
                get_registry(),
                "memory_update",
                {
                    "path": path,
                    "expected_sha256": expected_sha256,
                    "content": content,
                    "visibility": visibility,
                    "project": project,
                },
            )

    elif name == "memory_delete":

        @mcp.tool(name=name, description=description)
        def _delete(path: str, expected_sha256: str, project: str = "") -> Any:
            return call_tool(
                get_registry(),
                "memory_delete",
                {"path": path, "expected_sha256": expected_sha256, "project": project},
            )

    elif name == "memory_versions":

        @mcp.tool(name=name, description=description)
        def _versions(path: str, project: str = "") -> Any:
            return call_tool(get_registry(), "memory_versions", {"path": path, "project": project})


for _name in TOOL_DEFINITIONS:
    _register(_name)


def _register_prompt(name: str) -> None:
    from .prompts import PROMPT_DEFINITIONS, render

    description = PROMPT_DEFINITIONS[name][0]

    if name == "tacit_recall":

        @mcp.prompt(name=name, description=description)
        def _recall(question: str) -> str:
            return render("tacit_recall", {"question": question})

    elif name == "tacit_remember":

        @mcp.prompt(name=name, description=description)
        def _remember(learning: str = "") -> str:
            return render("tacit_remember", {"learning": learning})

    else:  # tacit_onboard / tacit_harvest take no arguments

        @mcp.prompt(name=name, description=description)
        def _plain() -> str:
            return render(name)


from .prompts import PROMPT_DEFINITIONS as _PROMPTS  # noqa: E402

for _name in _PROMPTS:
    _register_prompt(_name)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
