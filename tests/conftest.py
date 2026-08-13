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
    root = tmp_path_factory.mktemp("function-app-store")
    # The app builds its service from env on first call; point it at a local
    # store so importing it can never reach for Azure.
    previous = {k: os.environ.get(k) for k in ("TACIT_BACKEND", "TACIT_LOCAL_ROOT")}
    os.environ["TACIT_BACKEND"] = "local"
    os.environ["TACIT_LOCAL_ROOT"] = str(root)
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
