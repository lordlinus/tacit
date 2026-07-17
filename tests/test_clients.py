"""Client wiring snippets: valid, complete, and secret-free."""

import json

from teamlore.clients import (
    Wiring,
    agents_md_snippet,
    claude_code_command,
    copilot_cli_json,
    functions_http_json,
    vscode_mcp_json,
)

WIRING = Wiring(
    repo_dir="/opt/team-lore",
    search_endpoint="https://srch-x.search.windows.net",
    project="contoso-payments",
)


def test_claude_code_one_liner():
    command = claude_code_command(WIRING)
    assert command.startswith("claude mcp add team-lore ")
    assert "--env TEAMLORE_BACKEND=search" in command
    assert "--env TEAMLORE_SEARCH_ENDPOINT=https://srch-x.search.windows.net" in command
    assert command.endswith("-- uv --directory /opt/team-lore run lore-mcp")


def test_local_wiring_has_no_endpoint():
    wiring = Wiring(repo_dir="/opt/team-lore")
    assert wiring.env == {"TEAMLORE_BACKEND": "local", "TEAMLORE_PROJECT": "default"}


def test_vscode_and_copilot_json_shapes():
    vscode = json.loads(vscode_mcp_json(WIRING))
    server = vscode["servers"]["team-lore"]
    assert server["type"] == "stdio"
    assert server["command"] == "uv"
    assert server["env"]["TEAMLORE_PROJECT"] == "contoso-payments"

    copilot = json.loads(copilot_cli_json(WIRING))
    assert copilot["mcpServers"]["team-lore"]["args"] == server["args"]


def test_functions_http_uses_streamable_http_and_prompts_for_key():
    config = json.loads(functions_http_json("func-lore-abc"))
    server = config["servers"]["team-lore"]
    assert server["type"] == "http"
    assert server["url"] == "https://func-lore-abc.azurewebsites.net/runtime/webhooks/mcp"
    assert not server["url"].endswith("/sse")
    # The key is a VS Code input reference, never a literal secret.
    assert server["headers"]["x-functions-key"] == "${input:mcp-extension-system-key}"
    assert config["inputs"][0]["password"] is True


def test_no_snippet_embeds_secrets():
    for text in (
        claude_code_command(WIRING),
        vscode_mcp_json(WIRING),
        copilot_cli_json(WIRING),
        functions_http_json("func-x"),
        agents_md_snippet("p"),
    ):
        lowered = text.lower()
        for needle in ("api-key", "api_key", "password\": \"", "secret=", "bearer "):
            assert needle not in lowered, f"{needle!r} leaked into client config"


def test_agents_md_snippet_teaches_the_workflow():
    snippet = agents_md_snippet("contoso-payments")
    assert "memory_search" in snippet
    assert "memory_create" in snippet
    assert "expected_sha256" in snippet
