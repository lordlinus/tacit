# foundry-memory

**A mini enterprise team memory for AI coding agents** — Anthropic's managed-agents
[memory stores](https://docs.claude.com/en/docs/managed-agents/memory) +
[dreams](https://docs.claude.com/en/docs/managed-agents/dreams) model, rebuilt on
Azure so *any* MCP-speaking agent (GitHub Copilot, Claude Code, Cursor) on a team
shares one project memory.

- **Store:** Azure AI Search — one index pair per project, memories are
  path-addressed, versioned, and BM25-searchable
- **Runtime:** Azure Functions (Flex Consumption) with native MCP tool
  triggers — serverless, scale-to-zero
- **Curation:** `foundry-memory dream` — consolidates a messy store + session
  transcripts into a new curated store (input never modified)
- **Auth:** keyless end to end (`az login` locally, managed identity in Azure) —
  the foundry-iq pattern; no secrets in agent config, ever

## Why

When engineer #1's agent learns a project — the `make bootstrap` you can't skip,
the gateway that lowercases webhook headers, the CI job you must never rename —
those learnings die with the session. Engineer #2's agent re-reads the repo,
re-derives the architecture, and relearns every gotcha the hard way, burning
tokens (and a sprint) to reach the same place.

foundry-memory makes the learnings a **shared, searchable team asset**: agents
write durable facts as they work; the next agent answers from 2–3 memory hits
(hundreds of tokens) instead of repo excavation (thousands).

**Measured on the included sample** (`uv run foundry-memory bench`): answering six
onboarding questions costs **10,085 tokens cold vs 3,512 warm — a 65% saving**,
with every warm answer verified to contain the right fact. The one-time cost of
writing the memories (1,539 tokens) pays back before the second engineer finishes
day one. See [benchmark/RESULTS.md](benchmark/RESULTS.md).

## The model, mapped

| Anthropic managed agents       | foundry-memory                                    |
| ------------------------------ | ------------------------------------------------- |
| Memory store                   | AI Search index pair `tm-<project>` / `-versions` |
| Path-addressed memory          | Search doc keyed by path slug                     |
| Immutable memory versions      | Append-only versions index (full audit trail)     |
| `content_sha256` precondition  | Same — structured `sha_conflict` on mismatch      |
| Mounted dir + file tools       | 8 MCP tools incl. ranked `memory_search`          |
| Dreams                         | `foundry-memory dream` (heuristic, LLM-pluggable) |

## Five-minute local demo (no Azure needed)

```bash
uv sync --extra dev
./scripts/demo.sh
```

Or step by step:

```bash
# Engineer #1's agent stored 7 learnings about the sample project:
uv run foundry-memory seed samples/memories --backend local --project contoso-payments

# Engineer #2's agent, day one — one call instead of reading the repo:
uv run foundry-memory search "webhook signature fails staging" --backend local --project contoso-payments
uv run foundry-memory brief --backend local --project contoso-payments

# Prove the token hypothesis (writes benchmark/RESULTS.md):
uv run foundry-memory bench

# Dream: curate a messy store (+2 stale duplicates) and mine 2 transcripts:
uv run foundry-memory seed samples/memories-messy --backend local --project messy
uv run foundry-memory dream --backend local --project messy \
    --output-project curated --transcripts samples/transcripts
```

## Wire an agent (local stdio MCP)

```bash
claude mcp add team-memory -- uv --directory /path/to/foundry-memory run foundry-memory-mcp
```

Same command shape for any MCP client (VS Code `mcp.json`, Copilot CLI). Set
`FOUNDRY_MEMORY_BACKEND=search` + `FOUNDRY_MEMORY_SEARCH_ENDPOINT` to point the
stdio server at the shared cloud store — tokens are minted at runtime via
`DefaultAzureCredential`, so the config stays secret-free.

### MCP tools

`memory_search` (the hero — ranked hits, answer-ready) · `memory_brief`
(one-call onboarding pack) · `memory_read` · `memory_list` · `memory_create` ·
`memory_update` (sha-preconditioned) · `memory_delete` (tombstone) ·
`memory_versions` (audit trail).

## Deploy the shared runtime to Azure

```bash
azd up                          # AI Search + Flex Consumption Functions + RBAC
uv run foundry-memory provision --search-endpoint https://<svc>.search.windows.net \
    --project contoso-payments  # create the index pair (idempotent)
uv run foundry-memory seed samples/memories --backend search \
    --search-endpoint https://<svc>.search.windows.net --project contoso-payments
```

Team members point their MCP client at the deployed endpoint:
`https://<app>.azurewebsites.net/runtime/webhooks/mcp/sse` (header
`x-functions-key` = the `mcp_extension` system key; fetch with
`az functionapp keys list`).

> **Notes:** the Functions MCP trigger is preview (Experimental extension
> bundle). Azure AI Search has no consumption SKU — the bicep defaults to
> `basic` (`free` parameter available for dev); the *runtime* is the serverless
> half. The Functions app's managed identity gets Search data + service roles,
> so first use can create its own indexes.

## How it relates to pemp and foundry-iq

- **pemp** is *personal* memory (local-first, markdown+git canonical).
  foundry-memory lifts its invariants — immutable versions, optimistic
  concurrency, tombstones, structured conflicts — to a *team* store where
  search and shared access matter more than local files.
- **foundry-iq-cli** answers "what do the *documents* say" (Azure AI Search
  knowledge bases over your docs). foundry-memory answers "what has the *team
  already learned*". They compose: wire both MCP servers and an agent checks
  team memory first, falls back to the doc KB, then to the repo.

## Development

```bash
uv sync --extra dev
uv run --extra dev pytest     # 30 tests, hermetic — no Azure calls
az bicep build --file infra/main.bicep --stdout > /dev/null   # infra lint
```

Layout and design rationale: [DESIGN.md](DESIGN.md). Security red lines: no
keys/secrets in payloads, config, skills, or MCP wiring; mutations always
require the caller's `expected_sha256`; dreams never modify their input store.
