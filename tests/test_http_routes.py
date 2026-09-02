"""The plain-HTTP routes: the public story page and the read-only graph UI.

These are httpTrigger functions, not mcpToolTrigger — covered separately from
test_function_app.py, which only inspects the tool triggers.
"""

from __future__ import annotations

import json

import azure.functions as func
import pytest


@pytest.fixture(scope="session")
def http_functions_by_name(registered_bindings):
    return {
        name: fn
        for name, raw, fn in registered_bindings
        if raw["type"] == "httpTrigger"
    }


def test_landing_registers_at_the_api_root_anonymously(http_functions_by_name):
    raw = json.loads(str(http_functions_by_name["landing"].get_raw_bindings()[0]))
    assert raw["route"] == ""
    assert raw["authLevel"] == "ANONYMOUS"
    assert raw["methods"] == ["GET"]


def test_ui_and_graph_and_search_stay_function_key_gated(http_functions_by_name):
    """Unlike the landing page, these render or return tenant data."""
    for name in ("ui", "graph", "search"):
        raw = json.loads(str(http_functions_by_name[name].get_raw_bindings()[0]))
        assert raw["authLevel"] == "FUNCTION", f"{name} should require a function key"


def test_landing_serves_the_story_page(http_functions_by_name):
    handler = http_functions_by_name["landing"].get_user_function()
    req = func.HttpRequest(method="GET", url="/api/", body=b"")
    resp = handler(req)

    assert resp.mimetype == "text/html"
    body = resp.get_body().decode()
    assert "tacit" in body
    assert "Configure &amp; run it" in body
    assert "Open the graph" in body
    # No external network dependency, unlike the graph UI's D3 CDN script.
    assert "cdn.jsdelivr.net" not in body
    assert "unsafe-inline" in resp.headers["Content-Security-Policy"]
