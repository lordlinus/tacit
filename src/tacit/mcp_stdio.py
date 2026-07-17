"""Local stdio MCP server over the shared tool surface.

Keyless wiring for local dev and for teams not yet on the Functions endpoint:
the agent spawns ``tacit-mcp`` (stdio — every MCP client speaks it);
against the `search` backend, DefaultAzureCredential mints tokens at runtime,
so no secrets ever land in agent config (same pattern as `foundry-iq mcp`).

Register in Claude Code:
    claude mcp add tacit -- uv --directory /path/to/tacit run tacit-mcp
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import build_service, load_settings
from .service import MemoryService
from .tools import TOOL_DEFINITIONS, call_tool

mcp = FastMCP(
    "tacit",
    instructions=(
        "Shared team memory for this project. Search it BEFORE exploring the "
        "repo; store durable learnings (gotchas, conventions, decisions) so "
        "the next engineer's agent doesn't relearn them."
    ),
)

_service: MemoryService | None = None


def get_service() -> MemoryService:
    global _service
    if _service is None:
        _service = build_service(load_settings())
    return _service


def _register(name: str) -> None:
    description = TOOL_DEFINITIONS[name][0]

    # Explicit signatures per tool so MCP clients see real parameter schemas.
    if name in {"memory_search"}:

        @mcp.tool(name=name, description=description)
        def _search(query: str, top: int = 3, category: str = "") -> Any:
            return call_tool(get_service(), "memory_search", {"query": query, "top": top, "category": category})

    elif name == "memory_brief":

        @mcp.tool(name=name, description=description)
        def _brief() -> Any:
            return call_tool(get_service(), "memory_brief", {})

    elif name == "memory_read":

        @mcp.tool(name=name, description=description)
        def _read(path: str) -> Any:
            return call_tool(get_service(), "memory_read", {"path": path})

    elif name == "memory_list":

        @mcp.tool(name=name, description=description)
        def _list(prefix: str = "/") -> Any:
            return call_tool(get_service(), "memory_list", {"prefix": prefix})

    elif name == "memory_create":

        @mcp.tool(name=name, description=description)
        def _create(path: str, content: str, category: str = "general", tags: str = "") -> Any:
            return call_tool(
                get_service(),
                "memory_create",
                {"path": path, "content": content, "category": category, "tags": tags},
            )

    elif name == "memory_update":

        @mcp.tool(name=name, description=description)
        def _update(path: str, expected_sha256: str, content: str) -> Any:
            return call_tool(
                get_service(),
                "memory_update",
                {"path": path, "expected_sha256": expected_sha256, "content": content},
            )

    elif name == "memory_delete":

        @mcp.tool(name=name, description=description)
        def _delete(path: str, expected_sha256: str) -> Any:
            return call_tool(
                get_service(), "memory_delete", {"path": path, "expected_sha256": expected_sha256}
            )

    elif name == "memory_versions":

        @mcp.tool(name=name, description=description)
        def _versions(path: str) -> Any:
            return call_tool(get_service(), "memory_versions", {"path": path})


for _name in TOOL_DEFINITIONS:
    _register(_name)


def _register_prompt(name: str) -> None:
    from .prompts import PROMPT_DEFINITIONS, render

    description = PROMPT_DEFINITIONS[name][0]

    if name == "recall":

        @mcp.prompt(name=name, description=description)
        def _recall(question: str) -> str:
            return render("recall", {"question": question})

    elif name == "remember":

        @mcp.prompt(name=name, description=description)
        def _remember(learning: str = "") -> str:
            return render("remember", {"learning": learning})

    else:  # onboard / harvest take no arguments

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
