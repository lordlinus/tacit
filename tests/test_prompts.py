"""MCP prompts: shared definitions render workflow instructions, and both
runtimes expose them — stdio verified over the real wire protocol."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tacit.prompts import PROMPT_DEFINITIONS, render


def test_every_prompt_renders_tool_driving_instructions():
    for name in PROMPT_DEFINITIONS:
        text = render(name, {"question": "q", "learning": "x"})
        assert "memory_" in text, f"prompt {name!r} doesn't drive the memory tools"


def test_recall_embeds_the_question():
    assert "why is staging broken" in render("tacit_recall", {"question": "why is staging broken"})


def test_remember_handles_missing_learning():
    assert "Review this conversation" in render("tacit_remember", {})
    assert "429" in render("tacit_remember", {"learning": "simulator 429 fix"})


def test_unknown_prompt_raises():
    with pytest.raises(ValueError):
        render("dream_of_electric_sheep")


def test_prompts_over_the_wire(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tacit.mcp_stdio"],
        env={"TACIT_BACKEND": "local", "TACIT_LOCAL_ROOT": str(tmp_path)},
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


def test_function_app_registers_prompt_triggers(tmp_path, monkeypatch):
    monkeypatch.setenv("TACIT_BACKEND", "local")
    monkeypatch.setenv("TACIT_LOCAL_ROOT", str(tmp_path))
    functions_dir = str(Path(__file__).resolve().parents[1] / "functions")
    sys.path.insert(0, functions_dir)
    try:
        import importlib

        import function_app

        importlib.reload(function_app)
        registered = function_app.app.get_functions()
    finally:
        sys.path.remove(functions_dir)

    prompts = {}
    for fn in registered:
        raw = json.loads(str(fn.get_raw_bindings()[0]))
        if raw["type"] == "mcpPromptTrigger":
            prompts[raw["promptName"]] = fn
    assert set(prompts) == set(PROMPT_DEFINITIONS)
    rendered = prompts["tacit_harvest"].get_user_function()(json.dumps({"arguments": {}}))
    assert "memory_create" in rendered
