# tacit — organizational memory for your AI agent (2-minute setup)

Our agents now share one memory: gotchas, conventions, and decisions learned
by anyone's Copilot/Claude session are instantly available to everyone else's —
**including people on other teams and in other repos**. You connect once; your
agent does the rest.

## What you need (from your admin)

- **Endpoint:** `https://<app>.azurewebsites.net/runtime/webhooks/mcp`
  (your admin gets this from `tacit install --function-app <app>`)
- **Access key:** shared separately (Teams/secret channel — never commit it)

Nothing to install, no Azure access, no repo to clone.

## Connect your client

**Claude Code** (one command):

```bash
export TACIT_KEY=<key-from-your-admin>
claude mcp add --transport http tacit \
  https://<app>.azurewebsites.net/runtime/webhooks/mcp \
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
      "url": "https://<app>.azurewebsites.net/runtime/webhooks/mcp",
      "headers": { "x-functions-key": "${input:tacit-key}" }
    }
  }
}
```

**Copilot CLI** — merge into `~/.copilot/mcp-config.json` with the same
`type: http` / `url` / `headers` block.

## First thing you do: ask for `tacit_setup`

Once you're connected, in the repo you're working on, tell your agent:

> **"Run tacit_setup for this repo and write the instructions."**

Your agent calls the `tacit_setup` tool, gets the standing instructions, and
writes them into the repo's `AGENTS.md` (and `CLAUDE.md` /
`.github/copilot-instructions.md` if you already have them). Review the change
and commit it — everyone else on the repo then gets the behaviour too.

That's the part that makes it stick. Connecting the server only gives your agent
the *ability* to use memory; the instructions are what make it actually do so
without you asking, every session.

## Day-to-day

Just talk to your agent — the tools are always available:

- *"check team memory before you start"*
- *"has anyone else hit this? check other teams"*
- *"store that in team memory"*
- *"sweep this session and save anything worth keeping"*

> **No slash commands over this endpoint — by design.** The Azure Functions MCP
> prompt trigger cannot serve prompts over HTTP today (invoking one returns an
> error), so rather than advertise commands that fail, the server offers none.
> Everything they would have done, you can ask for in plain language above, and
> `tacit_setup` is a normal tool that always works. Nothing is missing —
> `/tacit_*` commands simply won't appear, and that's expected.

## Which project's memory? Automatic.

One endpoint serves all our projects. Your agent infers the project from the
**repository folder name** (`~/work/payments-api` → `payments-api`) and says
which one it's using — correct it in chat if it guessed wrong. A project's
memories are created automatically on first write, so new repos just work.

## Reading across teams

By default a search covers **your repo plus everything other teams have
published**. When a result came from somewhere else, your agent will say so —
treat it as a strong lead about how they solved it, not as gospel about your
repo. If your repo's memory is empty on something, ask the agent to *"check
what other teams know"* and it will search org-wide only.

When you store something, it is shared org-wide by default. Write titles that
make sense to someone who has never seen your repo ("the payments gateway
lowercases webhook headers", not "the gateway does that thing"). If a note
genuinely should not travel — unannounced work, team-internal process — tell
your agent to store it as `team` or `private`.

> **That is about relevance, not secrecy.** Everyone with this endpoint and key
> can reach anything marked org-wide, and the endpoint cannot tell us apart.
> Never store secrets, credentials, or need-to-know material in any memory,
> whatever its visibility.

## Ground rules

- **Store:** non-obvious fixes, gotchas that cost you >15 minutes, decisions
  and their why, conventions. One fact per memory, descriptive title that
  stands alone outside your repo.
- **Don't store:** secrets/keys/tokens (ever), transient debugging state,
  anything obvious from reading the code.
- Memory is versioned and attributed — updates append, nothing is erased, and
  `sha_conflict` responses mean someone edited concurrently (your agent
  re-reads and retries automatically).

## The habit that makes this work

End every substantial session with **`tacit_harvest`**. Thirty seconds; it's
what turns your session's pain into the next person's shortcut — and at this
point "the next person" might be on a team you've never met. The whole point:
the second engineer on any problem, anywhere in the org, should start where the
first one finished.
