"""The Functions MCP runtime, tested without a Functions host: every tool in
TOOL_DEFINITIONS must register an mcpToolTrigger function, and the handlers
must dispatch through the shared tool surface.

The app module itself is imported once per session by ``conftest.py`` — it has
import-time registration side effects, so importing it here too would
double-register every trigger.
"""

import json

import pytest


# Tools only — the prompt triggers registered alongside them are covered in
# test_prompts.py, and the HTTP routes in test_graph_endpoints.
@pytest.fixture(scope="session")
def functions_by_name(registered_bindings):
    return {
        name: fn
        for name, raw, fn in registered_bindings
        if raw["type"] == "mcpToolTrigger"
    }


def test_every_tool_registers_a_function(functions_by_name):
    from tacit.tools import TOOL_DEFINITIONS

    assert set(functions_by_name) == set(TOOL_DEFINITIONS)


def test_trigger_bindings_are_mcp_tool_triggers(functions_by_name):
    for name, registered in functions_by_name.items():
        raw = json.loads(str(registered.get_raw_bindings()[0]))
        assert raw["type"] == "mcpToolTrigger"
        assert raw["toolName"] == name
        json.loads(raw["toolProperties"])  # must be valid JSON property schemas


def test_handler_roundtrip_create_then_search(functions_by_name):
    def invoke(name: str, arguments: dict):
        handler = functions_by_name[name].get_user_function()
        return json.loads(handler(json.dumps({"arguments": arguments})))

    created = invoke(
        "memory_create",
        {"path": "/gotchas/slots.md", "content": "# Slot swap needs sentinel bump", "category": "gotcha"},
    )
    assert created["version"] == 1
    hits = invoke("memory_search", {"query": "slot swap sentinel"})
    assert hits[0]["path"] == "/gotchas/slots.md"
    conflict = invoke(
        "memory_update",
        {"path": "/gotchas/slots.md", "expected_sha256": "stale", "content": "# X"},
    )
    assert conflict["error"] == "sha_conflict"
