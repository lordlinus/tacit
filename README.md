# tacit

**A mini enterprise team memory for AI coding agents** — Anthropic's managed-agents
[memory stores](https://docs.claude.com/en/docs/managed-agents/memory) +
[dreams](https://docs.claude.com/en/docs/managed-agents/dreams) model, rebuilt on
Azure so *any* MCP-speaking agent (GitHub Copilot, Claude Code, Cursor) on a team
shares one project memory.

- **Store:** Azure AI Search — per project, memories are path-addressed,
  versioned, and searched by the semantic ranker over section-level chunks,
  so a hit costs the relevant part of a memory rather than the whole file
- **Runtime:** Azure Functions (Flex Consumption) with native MCP tool
  triggers — serverless, scale-to-zero
- **Curation:** `tacit dream` — consolidates a messy store + session
  transcripts into a new curated store (input never modified)
- **Auth:** keyless end to end (`az login` locally, managed identity in Azure) —
  the foundry-iq pattern; no secrets in agent config, ever

## Why

When engineer #1's agent learns a project — the `make bootstrap` you can't skip,
the gateway that lowercases webhook headers, the CI job you must never rename —
those learnings die with the session. Engineer #2's agent re-reads the repo,
re-derives the architecture, and relearns every gotcha the hard way, burning
tokens (and a sprint) to reach the same place.

tacit makes the learnings a **shared, searchable team asset**: agents
write durable facts as they work; the next agent answers from 2–3 memory hits
(hundreds of tokens) instead of repo excavation (thousands).

**Measured on the included sample** (`uv run tacit bench`): answering six
onboarding questions costs **10,085 tokens cold vs 3,512 warm — a 65% saving**,
with every warm answer verified to contain the right fact. The one-time cost of
writing the memories (1,539 tokens) pays back before the second engineer finishes
day one. See [benchmark/RESULTS.md](benchmark/RESULTS.md).

## The model, mapped

| Anthropic managed agents       | tacit                                    |
| ------------------------------ | ------------------------------------------------- |
| Memory store                   | AI Search index pair `tm-<project>` / `-versions` |
| Path-addressed memory          | Search doc keyed by path slug                     |
| Immutable memory versions      | Append-only versions index (full audit trail)     |
| `content_sha256` precondition  | Same — structured `sha_conflict` on mismatch      |
| Mounted dir + file tools       | 8 MCP tools incl. ranked `memory_search`          |
| Dreams                         | `tacit dream` (heuristic, LLM-pluggable) |

## Five-minute local demo (no Azure needed)

```bash
uv sync --extra dev
./scripts/demo.sh
```

Or step by step:

```bash
# Engineer #1's agent stored 7 learnings about the sample project:
uv run tacit seed samples/memories --backend local --project contoso-payments

# Engineer #2's agent, day one — one call instead of reading the repo:
uv run tacit search "webhook signature fails staging" --backend local --project contoso-payments
uv run tacit brief --backend local --project contoso-payments

# Prove the token hypothesis (writes benchmark/RESULTS.md):
uv run tacit bench

# Dream: curate a messy store (+2 stale duplicates) and mine 2 transcripts:
uv run tacit seed samples/memories-messy --backend local --project messy
uv run tacit dream --backend local --project messy \
    --output-project curated --transcripts samples/transcripts
```

## Share it with your team

One person (the admin) stands up the shared store; everyone else runs a single
command. `tacit install` prints the exact wiring for every client:

```bash
uv run tacit install --project contoso-payments \
    --search-endpoint https://<svc>.search.windows.net \
    --function-app <app-name>        # optional: the no-clone remote variant
```

That emits, ready to paste:
- the **Claude Code** one-liner (`claude mcp add tacit --env ... -- uv ... run tacit-mcp`)
- **VS Code / GitHub Copilot** `.vscode/mcp.json` (commit it to the project repo
  — the whole team gets wired on next open)
- **Copilot CLI** `~/.copilot/mcp-config.json`
- the deployed **Functions endpoint** config (Streamable HTTP; VS Code prompts
  for the system key so it never lands in a file)
- an **AGENTS.md / CLAUDE.md snippet** that tells agents to `memory_search`
  before exploring and to store learnings — wiring without instructions gets
  ignored, so commit this too.

Teammates using the stdio variant need only `git clone` + `uv` + `az login`;
tokens are minted at runtime via `DefaultAzureCredential`, so no config ever
contains a secret. Check adoption with `tacit stats` (memories by category,
contributor, recency — is the team actually writing?).

The MCP layer is verified end to end: `tests/test_mcp_integration.py` drives
the real server over the real wire protocol with the official MCP client —
the same path every teammate's agent takes.

### MCP tools

`memory_search` (the hero — ranked hits, answer-ready) · `memory_brief`
(one-call onboarding pack) · `memory_read` · `memory_list` · `memory_create` ·
`memory_update` (sha-preconditioned) · `memory_delete` (tombstone) ·
`memory_versions` (audit trail).

## Deploy the shared runtime to Azure

```bash
azd up                          # AI Search + Flex Consumption Functions + RBAC
uv run tacit provision --search-endpoint https://<svc>.search.windows.net \
    --project contoso-payments  # create the index pair (idempotent)
uv run tacit seed samples/memories --backend search \
    --search-endpoint https://<svc>.search.windows.net --project contoso-payments
```

Team members who don't want a local clone point their MCP client straight at
the deployed endpoint (Streamable HTTP):
`https://<app>.azurewebsites.net/runtime/webhooks/mcp`, header
`x-functions-key` = the `mcp_extension` system key
(`az functionapp keys list -g <rg> -n <app> --query systemKeys.mcp_extension -o tsv`).
`tacit install --function-app <app>` prints this config too.

> **Notes:** the Functions app uses the official
> [MCP bindings](https://learn.microsoft.com/azure/azure-functions/functions-bindings-mcp)
> — `mcp_tool_trigger` from `azure-functions>=1.24` with the mainstream v4
> extension bundle (Core Tools >= 4.0.7030 to run locally). The bicep defaults
> to AI Search's **Serverless tier** (preview,
> 2026): consumption-billed per Compute Unit + GB stored, no capacity to
> provision — a good fit for bursty team-memory traffic, but currently limited
> to westcentralus / switzerlandnorth / japaneast with no SLA. Pass
> `searchSku=basic` for production or other regions. The Functions app's
> managed identity gets Search data + service roles, so first use can create
> its own indexes.

## Using the real Anthropic memory stores & Dreams

tacit deliberately mirrors the managed-agents API shapes, so the two
compose rather than compete:

- **If your agents run as Claude managed agents**, Anthropic memory stores
  already give them mounted, versioned memory — attach one per project and
  those agents may not need tacit at all. tacit earns its keep when
  the team is *mixed* (GHCP + Claude Code + anything MCP) or when memory must
  live in your Azure tenant for data-residency/audit reasons.
- **Dreams as the curation brain:** the heuristic consolidator is the hermetic
  default, but `dream.Consolidator` is a protocol. A `DreamsConsolidator`
  could export the store to an Anthropic memory store (`memories.create` per
  path — the schemas map 1:1), run a real Dream over it plus session
  transcripts, and import the output store back into AI Search: Anthropic's
  semantic-quality merging, with the system of record staying in Azure.
  (Dreams is research preview; requires access and the `dreaming-2026-04-21`
  beta header.)

## How it relates to pemp and foundry-iq

- **pemp** is *personal* memory (local-first, markdown+git canonical).
  tacit lifts its invariants — immutable versions, optimistic
  concurrency, tombstones, structured conflicts — to a *team* store where
  search and shared access matter more than local files.
- **foundry-iq-cli** answers "what do the *documents* say" (Azure AI Search
  knowledge bases over your docs). tacit answers "what has the *team
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
