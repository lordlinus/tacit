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


def mcp_endpoint(function_app: str) -> str:
    return f"https://{function_app}.azurewebsites.net/runtime/webhooks/mcp"


def claude_code_remote_command(function_app: str) -> str:
    """Endpoint-only wiring for Claude Code — no clone, no uv, no az login.
    $TACIT_KEY keeps the secret out of shell history and pasted docs."""
    return (
        f"claude mcp add --transport http {SERVER_NAME} {mcp_endpoint(function_app)} "
        '--header "x-functions-key: $TACIT_KEY"'
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
## Organizational memory (tacit MCP server)

This project ('{project}') shares a searchable memory with the rest of the
organization. Use it without being asked:

- **Pass `project: "{project}"` on every memory tool call.** One endpoint serves
  every repo; without it your calls go to the server's default project and this
  repo's memory is neither read nor written.
- **Before exploring the repo** for setup steps, architecture, conventions, or
  debugging a weird failure: call `memory_search` first; call `memory_brief`
  once when you first start working here. Prior engineers' agents have already
  stored the gotchas — and `memory_search` reaches other teams too, so a problem
  another team solved will surface here.
- **A hit carrying a `project` field came from another team.** Say so when you
  use it, and treat it as a strong lead about how they solved it rather than
  settled fact for this repo.
- **If this repo's memory is empty on a question**, search again with
  `scope: "org"` before falling back to reading code.
- **When you learn something durable** — a non-obvious fix, a convention, a
  decision, a gotcha that cost real time — store it with `memory_create`
  (one focused fact per memory, '# Title' heading, category:
  onboarding|gotcha|architecture|convention). Write the title so it makes sense
  to someone outside this repo; it is shared org-wide by default.
- **Keep memories current.** If you find one that is now wrong or incomplete,
  `memory_read` it and `memory_update` with the corrected fact (requires
  `expected_sha256` from that read; on `sha_conflict`, re-read and retry).
  A confidently stale memory is worse than none.
- Pass `visibility: "team"` or `"private"` only for unannounced work or
  team-internal process notes.
- Do **not** store secrets, transient debugging state, or anything trivially
  derivable from the code."""
