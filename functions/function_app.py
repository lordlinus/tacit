"""Azure Functions MCP runtime for the team memory.

One function per memory tool, registered from the shared TOOL_DEFINITIONS via
the Functions MCP extension's ``mcp_tool_trigger`` binding (azure-functions
>= 1.24, mainstream v4 extension bundle), so this file is pure transport:
parse the trigger context, dispatch through ``tacit.tools.call_tool``,
serialize the result.

The ``tacit`` package is copied in next to this file by
``scripts/sync_functions.sh`` before packaging/deploy (azd runs it as a
prepackage hook). Auth to AI Search is the function app's managed identity —
keyless end to end.

MCP endpoint once deployed (Streamable HTTP — preferred; /sse is deprecated):
    https://<app>.azurewebsites.net/runtime/webhooks/mcp
    (header: x-functions-key = the mcp_extension system key)
"""

from __future__ import annotations

import json

import azure.functions as func

from tacit.config import build_service, load_settings
from tacit.service import MemoryService
from tacit.tools import TOOL_DEFINITIONS, call_tool

app = func.FunctionApp()

_service: MemoryService | None = None


def get_service() -> MemoryService:
    global _service
    if _service is None:
        _service = build_service(load_settings())
    return _service


def _tool_properties(name: str) -> str:
    return json.dumps(
        [
            {"propertyName": prop, "propertyType": kind, "description": description}
            for prop, kind, description in TOOL_DEFINITIONS[name][1]
        ]
    )


def _register(tool_name: str):
    @app.function_name(name=tool_name)
    @app.mcp_tool_trigger(
        arg_name="context",
        tool_name=tool_name,
        description=TOOL_DEFINITIONS[tool_name][0],
        tool_properties=_tool_properties(tool_name),
    )
    def handler(context: str) -> str:
        payload = json.loads(context)
        arguments = payload.get("arguments") or {}
        result = call_tool(get_service(), tool_name, arguments)
        return json.dumps(result, ensure_ascii=False, default=str)

    return handler


for _name in TOOL_DEFINITIONS:
    _register(_name)
