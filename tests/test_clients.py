"""Client wiring snippets: valid, complete, and secret-free."""

import json

from tacit.clients import (
    Wiring,
    agents_md_snippet,
    claude_code_command,
    copilot_cli_json,
    functions_http_json,
    vscode_mcp_json,
)

WIRING = Wiring(
    repo_dir="/opt/tacit",
    search_endpoint="https://srch-x.search.windows.net",
    project="contoso-payments",
)


def test_claude_code_one_liner():
    command = claude_code_command(WIRING)
    assert command.startswith("claude mcp add tacit ")
    assert "--env TACIT_BACKEND=search" in command
    assert "--env TACIT_SEARCH_ENDPOINT=https://srch-x.search.windows.net" in command
    assert command.endswith("-- uv --directory /opt/tacit run tacit-mcp")


def test_local_wiring_has_no_endpoint():
    wiring = Wiring(repo_dir="/opt/tacit")
    assert wiring.env == {"TACIT_BACKEND": "local", "TACIT_PROJECT": "default"}


def test_vscode_and_copilot_json_shapes():
    vscode = json.loads(vscode_mcp_json(WIRING))
    server = vscode["servers"]["tacit"]
    assert server["type"] == "stdio"
    assert server["command"] == "uv"
    assert server["env"]["TACIT_PROJECT"] == "contoso-payments"

    copilot = json.loads(copilot_cli_json(WIRING))
    assert copilot["mcpServers"]["tacit"]["args"] == server["args"]


def test_claude_code_remote_is_endpoint_only():
    from tacit.clients import claude_code_remote_command, mcp_endpoint

    command = claude_code_remote_command("func-x")
    assert mcp_endpoint("func-x") == "https://func-x.azurewebsites.net/runtime/webhooks/mcp"
    assert "--transport http" in command
    assert "https://func-x.azurewebsites.net/runtime/webhooks/mcp" in command
    assert "$TACIT_KEY" in command  # env reference, never a literal key
    assert "uv " not in command and "--directory" not in command  # truly no-clone


def test_functions_http_uses_streamable_http_and_prompts_for_key():
    config = json.loads(functions_http_json("func-tacit-abc"))
    server = config["servers"]["tacit"]
    assert server["type"] == "http"
    assert server["url"] == "https://func-tacit-abc.azurewebsites.net/runtime/webhooks/mcp"
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
