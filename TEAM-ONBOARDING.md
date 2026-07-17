# tacit — team memory for your AI agent (2-minute setup)

Our agents now share one memory: gotchas, conventions, and decisions learned
by anyone's Copilot/Claude session are instantly available to everyone else's.
You connect once; your agent does the rest.

## What you need (from Sunil)

- **Endpoint:** `https://func-tacit-enhjckqpox6lm.azurewebsites.net/runtime/webhooks/mcp`
- **Access key:** shared separately (Teams/secret channel — never commit it)

Nothing to install, no Azure access, no repo to clone.

## Connect your client

**Claude Code** (one command):

```bash
export TACIT_KEY=<key-from-sunil>
claude mcp add --transport http tacit \
  https://func-tacit-enhjckqpox6lm.azurewebsites.net/runtime/webhooks/mcp \
  --header "x-functions-key: $TACIT_KEY"
```

**VS Code / GitHub Copilot** — save as `.vscode/mcp.json` (safe to commit; VS
Code prompts each person for the key on first use):

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "tacit-key",
      "description": "tacit MCP access key",
      "password": true
    }
  ],
  "servers": {
    "tacit": {
      "type": "http",
      "url": "https://func-tacit-enhjckqpox6lm.azurewebsites.net/runtime/webhooks/mcp",
      "headers": { "x-functions-key": "${input:tacit-key}" }
    }
  }
}
```

**Copilot CLI** — merge into `~/.copilot/mcp-config.json` with the same
`type: http` / `url` / `headers` block.

## How to use it — four slash commands

Your client discovers these automatically from the server (Claude Code shows
them as `/mcp__tacit__<name>`; VS Code lists them in the prompt picker):

| Prompt | When | What happens |
|---|---|---|
| `tacit_onboard` | First time in a repo | Agent pulls the project's memory and briefs you: setup, gotchas, conventions |
| `tacit_recall` | You have a question | Agent answers from team memory first (cites sources); explores the repo only if memory has nothing |
| `tacit_remember` | You just learned something the team should keep | Agent distills it into a well-formed memory and stores it |
| `tacit_harvest` | End of a work session | Agent sweeps the whole session and stores every durable learning |

You can also just talk: *"check team memory for deploy gotchas"* or *"store
that in team memory"* — the agent has the tools either way.

## Which project's memory? Automatic.

One endpoint serves all our projects. Your agent infers the project from the
**repository folder name** (`~/work/payments-api` → `payments-api`) and says
which one it's using — correct it in chat if it guessed wrong. A project's
store is created automatically on its first write, so new repos just work.

## Ground rules

- **Store:** non-obvious fixes, gotchas that cost you >15 minutes, decisions
  and their why, conventions. One fact per memory, descriptive title.
- **Don't store:** secrets/keys/tokens (ever), transient debugging state,
  anything obvious from reading the code.
- Memory is versioned and attributed — updates append, nothing is erased, and
  `sha_conflict` responses mean someone edited concurrently (your agent
  re-reads and retries automatically).

## The habit that makes this work

End every substantial session with **`tacit_harvest`**. Thirty seconds; it's
what turns your session's pain into the next person's shortcut. The whole
point: the second engineer on any problem should start where the first one
finished.
