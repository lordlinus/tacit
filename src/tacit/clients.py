"""Ready-to-paste MCP wiring for every client a teammate might use.

Pure functions (no cloud, no filesystem) so they're trivially unit-tested —
the foundry-iq buttons.py pattern. Nothing here ever embeds a secret: the
stdio server mints Entra tokens at runtime via DefaultAzureCredential, and the
Functions variant tells the user to fetch the system key themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

SERVER_NAME = "tacit"


@dataclass(frozen=True)
class Wiring:
    """Everything needed to point a stdio MCP client at the shared store."""

    repo_dir: str
    search_endpoint: str = ""
    project: str = "default"

    @property
    def env(self) -> dict[str, str]:
        if not self.search_endpoint:
            return {"TACIT_BACKEND": "local", "TACIT_PROJECT": self.project}
        return {
            "TACIT_BACKEND": "search",
            "TACIT_SEARCH_ENDPOINT": self.search_endpoint,
            "TACIT_PROJECT": self.project,
        }

    @property
    def command_args(self) -> list[str]:
        return ["--directory", self.repo_dir, "run", "tacit-mcp"]


def claude_code_command(wiring: Wiring) -> str:
    """One-liner for Claude Code / Copilot CLI-compatible `mcp add`."""
    env_flags = " ".join(f"--env {key}={value}" for key, value in wiring.env.items())
    return f"claude mcp add {SERVER_NAME} {env_flags} -- uv {' '.join(wiring.command_args)}"


def vscode_mcp_json(wiring: Wiring) -> str:
    """`.vscode/mcp.json` for VS Code agent mode / GitHub Copilot."""
    return json.dumps(
        {
            "servers": {
                SERVER_NAME: {
                    "type": "stdio",
                    "command": "uv",
                    "args": wiring.command_args,
                    "env": wiring.env,
                }
            }
        },
        indent=2,
    )


def copilot_cli_json(wiring: Wiring) -> str:
    """Entry for ~/.copilot/mcp-config.json."""
    return json.dumps(
        {
            "mcpServers": {
                SERVER_NAME: {
                    "command": "uv",
                    "args": wiring.command_args,
                    "env": wiring.env,
                }
            }
        },
        indent=2,
    )


def functions_http_json(function_app: str) -> str:
    """Remote variant: the Azure Functions MCP endpoint over Streamable HTTP
    (no repo clone needed). VS Code prompts for the key via `inputs`, so the
    secret never lands in the file — fetch it with:
    az functionapp keys list -g <rg> -n <app> --query systemKeys.mcp_extension -o tsv
    """
    return json.dumps(
        {
            "inputs": [
                {
                    "type": "promptString",
                    "id": "mcp-extension-system-key",
                    "description": "Azure Functions MCP extension system key",
                    "password": True,
                }
            ],
            "servers": {
                SERVER_NAME: {
                    "type": "http",
                    "url": f"https://{function_app}.azurewebsites.net/runtime/webhooks/mcp",
                    "headers": {"x-functions-key": "${input:mcp-extension-system-key}"},
                }
            },
        },
        indent=2,
    )


def agents_md_snippet(project: str) -> str:
    """Drop into the target repo's AGENTS.md / CLAUDE.md so agents actually
    use the memory — wiring without instructions gets ignored."""
    return f"""\
## Team memory (tacit MCP server)

This project has a shared team memory ('{project}'). Use it without being asked:

- **Before exploring the repo** for setup steps, architecture, conventions, or
  debugging a weird failure: call `memory_search` first; call `memory_brief`
  once when you first start working here. Prior engineers' agents have already
  stored the gotchas.
- **When you learn something durable** — a non-obvious fix, a convention, a
  decision, a gotcha that cost real time — store it with `memory_create`
  (one focused fact per memory, '# Title' heading, category:
  onboarding|gotcha|architecture|convention). Update stale memories with
  `memory_read` -> `memory_update` (requires expected_sha256; on sha_conflict,
  re-read and retry).
- Do **not** store secrets, transient debugging state, or anything trivially
  derivable from the code."""
