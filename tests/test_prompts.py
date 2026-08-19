"""MCP prompts: shared definitions render workflow instructions, and both
runtimes expose them — stdio verified over the real wire protocol."""

import asyncio
import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tacit.prompts import PROMPT_DEFINITIONS, render


def test_every_prompt_renders_tool_driving_instructions():
    for name in PROMPT_DEFINITIONS:
        text = render(name, {"question": "q", "learning": "x"})
        assert "memory_" in text, f"prompt {name!r} doesn't drive the memory tools"


class TestSetupPrompt:
    """The one a colleague runs once. It has to leave the repo configured, or
    the server is wired up and then quietly ignored."""

    def test_it_is_offered_first(self):
        """Clients list prompts in definition order; setup must lead."""
        assert next(iter(PROMPT_DEFINITIONS)) == "tacit_setup"

    def test_it_takes_no_arguments(self):
        assert PROMPT_DEFINITIONS["tacit_setup"][1] == []

    def test_it_establishes_the_project_before_anything_else(self):
        text = render("tacit_setup")
        assert "kebab-case" in text
        assert text.index("project slug") < text.index("memory_list")

    def test_it_verifies_the_connection_and_reports_an_empty_store(self):
        text = render("tacit_setup")
        assert "memory_list" in text and "memory_search" in text
        assert "empty" in text, "a new project must be told it is starting from scratch"

    def test_it_writes_the_standing_instructions(self):
        text = render("tacit_setup")
        assert "AGENTS.md" in text
        assert "CLAUDE.md" in text
        assert ".github/copilot-instructions.md" in text

    def test_it_carries_the_same_block_the_cli_prints(self):
        """`tacit install`, the setup tool and the setup prompt must not
        describe the workflow differently; the block has exactly one source."""
        from tacit.clients import agents_md_snippet

        block = agents_md_snippet("<PROJECT_SLUG>")
        assert block in render("tacit_setup")

    def test_the_tool_and_the_prompt_deliver_the_same_block(self):
        """Prompts do not reach every client — Copilot Studio has none, and the
        Functions HTTP transport cannot invoke them today — so the same setup
        is offered as a tool. The two must not drift."""
        from tacit.clients import agents_md_snippet
        from tacit.tools import call_tool

        class _Service:
            project = "demo"
            team = "platform"

            def list(self, prefix="/"):
                return []

        result = call_tool(_Service(), "tacit_setup", {})
        assert result["instructions_block"] == agents_md_snippet("demo")
        assert result["project"] == "demo"
        assert "AGENTS.md" in result["write_to"][0]

    def test_the_block_covers_reading_and_updating(self):
        from tacit.clients import agents_md_snippet

        block = agents_md_snippet("demo")
        for tool in ("memory_search", "memory_brief", "memory_create",
                     "memory_read", "memory_update"):
            assert tool in block, f"standing instructions never mention {tool}"

    def test_the_block_tells_the_agent_to_route_by_project(self):
        """One endpoint serves every repo. An agent that omits `project` reads
        and writes the server's default instead of this repo's memory."""
        from tacit.clients import agents_md_snippet

        assert 'project: "demo"' in agents_md_snippet("demo")

    def test_it_does_not_duplicate_itself_on_a_second_run(self):
        text = render("tacit_setup")
        assert "replace it rather than appending" in text

    def test_it_leaves_committing_to_the_human(self):
        assert "Do not commit" in render("tacit_setup")


def test_recall_embeds_the_question():
    assert "why is staging broken" in render("tacit_recall", {"question": "why is staging broken"})


def test_remember_handles_missing_learning():
    assert "Review this conversation" in render("tacit_remember", {})
    assert "429" in render("tacit_remember", {"learning": "simulator 429 fix"})


def test_unknown_prompt_raises():
    with pytest.raises(ValueError):
        render("dream_of_electric_sheep")


def test_prompts_over_the_wire():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tacit.mcp_stdio"],
        # Prompt rendering never touches the store, so the endpoint is only
        # needed to satisfy configuration on startup.
        env={
            "TACIT_SEARCH_ENDPOINT": "https://srch-test.search.windows.net",
            "TACIT_PROJECT": "test",
        },
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = {p.name for p in (await session.list_prompts()).prompts}
                got = await session.get_prompt("tacit_recall", {"question": "deploy gotchas?"})
                return listed, got.messages[0].content.text

    listed, recall_text = asyncio.run(scenario())
    assert listed == set(PROMPT_DEFINITIONS)
    assert "deploy gotchas?" in recall_text
    assert "memory_search" in recall_text


def test_function_app_registers_prompt_triggers(function_app, registered_bindings, monkeypatch):
    """Prompt triggers are OFF by default on the Functions runtime.

    They register but cannot be invoked over HTTP (JSON-RPC -32603), and a
    slash command that always errors reads as a broken server. The registration
    code is still exercised here so it stays correct for the day the platform
    supports invocation.
    """
    advertised = {
        raw["promptName"] for _n, raw, _f in registered_bindings
        if raw["type"] == "mcpPromptTrigger"
    }
    assert advertised == set(), "prompts must not be advertised where they cannot be invoked"

    monkeypatch.setenv("TACIT_ENABLE_MCP_PROMPTS", "true")
    assert function_app._prompts_enabled() is True
    builder = function_app._register_prompt("tacit_harvest")
    rendered = builder._function.get_user_function()(json.dumps({"arguments": {}}))
    assert "memory_create" in rendered


def test_the_opt_in_flag_is_off_by_default(function_app, monkeypatch):
    monkeypatch.delenv("TACIT_ENABLE_MCP_PROMPTS", raising=False)
    assert function_app._prompts_enabled() is False


def test_setup_is_reachable_as_a_tool_where_prompts_are_not(registered_bindings):
    """The workflow prompts would have carried must survive their absence."""
    tools = {
        raw["toolName"] for _n, raw, _f in registered_bindings
        if raw["type"] == "mcpToolTrigger"
    }
    assert "tacit_setup" in tools
