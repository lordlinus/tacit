"""Azure Functions MCP runtime for the team memory.

One function per memory tool, registered from the shared TOOL_DEFINITIONS via
the native ``mcpToolTrigger`` binding (Functions MCP extension, preview), so
this file is pure transport: parse the trigger context, dispatch through
``foundry_memory.tools.call_tool``, serialize the result.

The ``foundry_memory`` package is copied in next to this file by
``scripts/sync_functions.sh`` before packaging/deploy (azd runs it as a
prepackage hook). Auth to AI Search is the function app's managed identity —
keyless end to end.

MCP endpoint once deployed:
    https://<app>.azurewebsites.net/runtime/webhooks/mcp/sse
    (header: x-functions-key = the mcp_extension system key)
"""

from __future__ import annotations

import json

import azure.functions as func

from foundry_memory.config import build_service, load_settings
from foundry_memory.service import MemoryService
from foundry_memory.tools import TOOL_DEFINITIONS, call_tool

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
    @app.generic_trigger(
        arg_name="context",
        type="mcpToolTrigger",
        toolName=tool_name,
        description=TOOL_DEFINITIONS[tool_name][0],
        toolProperties=_tool_properties(tool_name),
    )
    def handler(context: str) -> str:
        payload = json.loads(context)
        arguments = payload.get("arguments") or {}
        result = call_tool(get_service(), tool_name, arguments)
        return json.dumps(result, ensure_ascii=False, default=str)

    return handler


for _name in TOOL_DEFINITIONS:
    _register(_name)
