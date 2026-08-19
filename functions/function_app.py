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

The app also serves a read-only overlap-graph UI over plain HTTP:
    https://<app>.azurewebsites.net/api/ui?code=<function key>
The page and its data come from the same origin, so no CORS configuration is
needed, and the function key never leaves the URL the operator already has.
"""

from __future__ import annotations

import json
import os

import azure.functions as func

from tacit.config import ServiceRegistry, load_settings
from tacit.tools import TOOL_DEFINITIONS, call_tool
from tacit.ui import PAGE

app = func.FunctionApp()

# One shared endpoint serves every team project: tools route by their optional
# `project` argument; the default comes from the TACIT_PROJECT app setting.
_registry: ServiceRegistry | None = None


def get_registry() -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry(load_settings())
    return _registry


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
        result = call_tool(get_registry(), tool_name, arguments)
        return json.dumps(result, ensure_ascii=False, default=str)

    return handler


for _name in TOOL_DEFINITIONS:
    _register(_name)


# --------------------------------------------------------------------------- #
# MCP prompts
#
# Registration is OFF by default on this runtime, deliberately.
#
# The Functions MCP extension's prompt trigger registers fine — the prompts
# appear in `prompts/list` — but invoking one returns JSON-RPC -32603. Working
# invocation needs the `mcp_prompt_trigger` decorator from azure-functions 2.x,
# which requires Python >= 3.13, while the remote Oryx build resolves 3.12
# regardless of the runtime version configured on the app. Advertising a slash
# command that always errors is worse for a first-time user than not offering
# it: they see "Error resolving prompt" and conclude the server is broken.
#
# The same workflows are reachable everywhere as tools (`tacit_setup`) or in
# plain language, and the stdio server still registers the prompts, where they
# work. Set TACIT_ENABLE_MCP_PROMPTS=true to re-enable here once the platform
# supports invocation.
# --------------------------------------------------------------------------- #
def _prompts_enabled() -> bool:
    return os.environ.get("TACIT_ENABLE_MCP_PROMPTS", "").strip().lower() in {
        "1", "true", "yes",
    }


def _register_prompt(prompt_name: str):
    from tacit.prompts import PROMPT_DEFINITIONS, render

    description, arg_defs = PROMPT_DEFINITIONS[prompt_name]

    def handler(context: str) -> str:
        payload = json.loads(context)
        arguments = payload.get("arguments") or {}
        return render(prompt_name, arguments)

    if hasattr(app, "mcp_prompt_trigger"):
        from azure.functions.decorators.mcp import PromptArgument

        return app.function_name(name=f"prompt_{prompt_name}")(
            app.mcp_prompt_trigger(
                arg_name="context",
                prompt_name=prompt_name,
                description=description,
                prompt_arguments=[
                    PromptArgument(
                        name=arg, description=arg_description, required=required
                    )
                    for arg, arg_description, required in arg_defs
                ],
            )(handler)
        )

    return app.function_name(name=f"prompt_{prompt_name}")(
        app.generic_trigger(
            arg_name="context",
            type="mcpPromptTrigger",
            promptName=prompt_name,
            description=description,
            promptArguments=json.dumps(
                [
                    {"name": arg, "description": arg_description, "required": required}
                    for arg, arg_description, required in arg_defs
                ]
            ),
        )(handler)
    )


from tacit.prompts import PROMPT_DEFINITIONS as _PROMPTS  # noqa: E402

if _prompts_enabled():
    for _name in _PROMPTS:
        _register_prompt(_name)


# --------------------------------------------------------------------------- #
# Read-only graph UI (plain HTTP, function-key auth, same origin as its data)
# --------------------------------------------------------------------------- #
@app.function_name(name="ui")
@app.route(route="ui", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def ui(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the overlap-graph page."""
    return func.HttpResponse(
        PAGE,
        mimetype="text/html",
        # The page embeds no data, so the policy stays tight: its own inline
        # script, its own origin for data, and the pinned D3 CDN — which is the
        # single external dependency the graph needs.
        headers={
            "Content-Security-Policy":
                "default-src 'none'; "
                "script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'unsafe-inline'; connect-src 'self'; img-src data:",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.function_name(name="graph")
@app.route(route="graph", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def graph(req: func.HttpRequest) -> func.HttpResponse:
    """Overlap-graph JSON for one viewer.

    ``project`` selects which project the viewer is looking *from*; as
    everywhere else it is a routing hint that grants nothing, and the graph is
    built from ``visible_memories``, which applies the same visibility rules as
    search. A private memory therefore contributes no node, edge or count.
    """
    try:
        service = get_registry().get_service(req.params.get("project", "") or "")
        payload = service.graph(req.params.get("scope") or None)
    except ValueError as exc:
        return func.HttpResponse(
            json.dumps({"error": "invalid_argument", "detail": str(exc)}),
            status_code=400, mimetype="application/json",
        )
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, default=str),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


@app.function_name(name="search")
@app.route(route="search", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def search(req: func.HttpRequest) -> func.HttpResponse:
    """The UI's search box, over the same tool an agent calls.

    Dispatching through ``call_tool`` rather than the service keeps one
    definition of what a hit looks like, so the page cannot drift from what
    `memory_search` returns — including the rule that a `project` field appears
    only when the result crossed a team boundary.
    """
    args = {
        "query": req.params.get("q", ""),
        "top": _int_param(req.params.get("top"), default=8, maximum=25),
        "scope": req.params.get("scope") or "",
        "category": req.params.get("category") or "",
        "entity": req.params.get("entity") or "",
        "project": req.params.get("project") or "",
    }
    if not args["query"].strip():
        return func.HttpResponse("[]", mimetype="application/json")
    result = call_tool(get_registry(), "memory_search", args)
    status = 400 if isinstance(result, dict) and result.get("error") else 200
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False, default=str),
        status_code=status,
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )


def _int_param(raw: str | None, *, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(raw), maximum))
    except (TypeError, ValueError):
        return default
