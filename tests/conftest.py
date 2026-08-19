"""Shared fixtures.

The Functions app is a module with import-time side effects: importing it
registers every trigger on a module-level ``FunctionApp``, and
``get_functions()`` validates name uniqueness against accumulated state. Two
test modules that each imported (or reloaded) it would therefore either
double-register — "Function memory_search does not have a unique function
name" — or fight over ``sys.path``, and which happened depended on the order
pytest chose. Importing it exactly once per session removes both failure modes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

FUNCTIONS_DIR = str(Path(__file__).resolve().parents[1] / "functions")


@pytest.fixture(scope="session")
def function_app(tmp_path_factory):
    """The imported Functions app module, registered exactly once."""
    # The app builds its service from env on first call. These tests only
    # inspect trigger registration, so a syntactically valid endpoint is enough
    # — nothing here ever issues a request.
    previous = {k: os.environ.get(k) for k in ("TACIT_SEARCH_ENDPOINT", "TACIT_PROJECT")}
    os.environ["TACIT_SEARCH_ENDPOINT"] = "https://srch-test.search.windows.net"
    os.environ["TACIT_PROJECT"] = "test"
    added = FUNCTIONS_DIR not in sys.path
    if added:
        sys.path.insert(0, FUNCTIONS_DIR)
    try:
        import function_app  # noqa: PLC0415

        yield function_app
    finally:
        if added and FUNCTIONS_DIR in sys.path:
            sys.path.remove(FUNCTIONS_DIR)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="session")
def registered_bindings(function_app):
    """``[(function_name, raw_binding_dict), ...]`` for every registered trigger.

    ``get_functions()`` is not idempotent, so it is called once and the result
    shared; tests filter this rather than re-reading the registry.
    """
    import json

    out = []
    for fn in function_app.app.get_functions():
        out.append((fn.get_function_name(), json.loads(str(fn.get_raw_bindings()[0])), fn))
    return out
