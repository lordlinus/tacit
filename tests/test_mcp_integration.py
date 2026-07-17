"""End-to-end MCP: spawn the real stdio server as a subprocess and drive it
with the real MCP client — the exact wire path a teammate's agent uses.
If this passes, any MCP client (Claude Code, VS Code, Copilot CLI) can talk
to the server."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _server_params(tmp_path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "tacit.mcp_stdio"],
        env={
            "TACIT_BACKEND": "local",
            "TACIT_LOCAL_ROOT": str(tmp_path),
            "TACIT_PROJECT": "integration",
            "TACIT_ACTOR": "integration-test",
        },
    )


def _tool_payload(result) -> object:
    """MCP tool results carry JSON in text content; prefer structured if
    present. FastMCP emits list results as one text block per item."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    blocks = [json.loads(c.text) for c in result.content if getattr(c, "text", "")]
    return blocks[0] if len(blocks) == 1 else blocks


async def _session_scenario(params: StdioServerParameters) -> dict:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}

            created = _tool_payload(
                await session.call_tool(
                    "memory_create",
                    {
                        "path": "/gotchas/wire-test.md",
                        "content": "# Wire test gotcha\n\nSeen over real MCP.",
                        "category": "gotcha",
                        "tags": "integration",
                    },
                )
            )
            hits = _tool_payload(
                await session.call_tool("memory_search", {"query": "wire test gotcha"})
            )
            conflict = _tool_payload(
                await session.call_tool(
                    "memory_update",
                    {
                        "path": "/gotchas/wire-test.md",
                        "expected_sha256": "stale-sha",
                        "content": "# nope",
                    },
                )
            )
            return {
                "server_name": info.serverInfo.name,
                "tools": tools,
                "created": created,
                "hits": hits,
                "conflict": conflict,
            }


@pytest.fixture(scope="module")
def wire(tmp_path_factory):
    params = _server_params(tmp_path_factory.mktemp("wire-store"))
    return asyncio.run(_session_scenario(params))


def test_initialize_and_all_tools_visible(wire):
    from tacit.tools import TOOL_DEFINITIONS

    assert wire["server_name"] == "tacit"
    assert wire["tools"] == set(TOOL_DEFINITIONS)


def test_create_roundtrips_over_the_wire(wire):
    created = wire["created"]
    assert created["path"] == "/gotchas/wire-test.md"
    assert created["version"] == 1
    assert len(created["content_sha256"]) == 64


def test_search_finds_the_memory(wire):
    hits = wire["hits"]
    if isinstance(hits, dict):  # single hit arrives as one block
        hits = [hits]
    assert hits[0]["path"] == "/gotchas/wire-test.md"
    assert "Seen over real MCP" in hits[0]["content"]


def test_sha_conflict_is_structured_over_the_wire(wire):
    assert wire["conflict"]["error"] == "sha_conflict"
