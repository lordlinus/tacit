"""The Functions MCP runtime, tested without a Functions host: every tool in
TOOL_DEFINITIONS must register an mcpToolTrigger function, and the handlers
must dispatch through the shared tool surface."""

import json
import sys
from pathlib import Path

import pytest

FUNCTIONS_DIR = str(Path(__file__).resolve().parents[1] / "functions")


@pytest.fixture(scope="module")
def function_app(tmp_path_factory):
    root = tmp_path_factory.mktemp("store")
    # The app builds its service from env at first call; point it at a local store.
    import os

    os.environ["TACIT_BACKEND"] = "local"
    os.environ["TACIT_LOCAL_ROOT"] = str(root)
    sys.path.insert(0, FUNCTIONS_DIR)
    try:
        import function_app  # noqa: PLC0415

        yield function_app
    finally:
        sys.path.remove(FUNCTIONS_DIR)
        os.environ.pop("TACIT_BACKEND")
        os.environ.pop("TACIT_LOCAL_ROOT")


# get_functions() is not idempotent (its name validation accumulates state),
# so snapshot the registry once for all tests. Tools only — the prompt
# triggers registered alongside them are covered in test_prompts.py.
@pytest.fixture(scope="module")
def functions_by_name(function_app):
    registered = {}
    for f in function_app.app.get_functions():
        raw = json.loads(str(f.get_raw_bindings()[0]))
        if raw["type"] == "mcpToolTrigger":
            registered[f.get_function_name()] = f
    return registered


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
