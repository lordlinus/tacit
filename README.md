# tacit

**Organizational memory for AI coding agents** — Anthropic's managed-agents
[memory stores](https://docs.claude.com/en/docs/managed-agents/memory) +
[dreams](https://docs.claude.com/en/docs/managed-agents/dreams) model, rebuilt on
Azure so *any* MCP-speaking agent (GitHub Copilot, Claude Code, Cursor) across
*any* team shares one searchable memory.

- **Store:** Azure AI Search — one shared index set for the whole organization.
  Memories are path-addressed per project, versioned, and searched by the
  semantic ranker over section-level chunks, so a hit costs the relevant part of
  a memory rather than the whole file
- **Reach:** a search spans your own repo *and* everything other teams have
  published, ranked together with a bias toward home — so a problem another
  team already solved surfaces before you rediscover it
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

Worse at organizational scale: *team B* relearns what *team A* already paid for.
The same gateway, the same rate limiter, the same migration footgun — solved
once per team, forever.

tacit makes the learnings a **shared, searchable asset across teams**: agents
write durable facts as they work; the next agent — in this repo or another one
entirely — answers from 2–3 memory hits (hundreds of tokens) instead of repo
excavation (thousands).

**Measured on the included sample** (`uv run tacit bench`): answering six
onboarding questions costs **10,085 tokens cold vs 3,512 warm — a 65% saving**,
with every warm answer verified to contain the right fact. The one-time cost of
writing the memories (1,539 tokens) pays back before the second engineer finishes
day one. See [benchmark/RESULTS.md](benchmark/RESULTS.md).

## Scope and visibility: how knowledge crosses teams

Every memory is addressed by `(project, path)` and published under a
**visibility**. Every search runs at a **scope**. Together those decide what
reaches whom.

| Visibility          | Who can find it                                   |
| ------------------- | ------------------------------------------------- |
| `org` *(default)*   | Anyone in the organization                        |
| `team`              | Projects belonging to the same `TACIT_TEAM`       |
| `private`           | Only the project that wrote it                    |

| Scope                     | What it searches                                     |
| ------------------------- | ---------------------------------------------------- |
| `project+org` *(default)* | This repo **plus** what other teams published        |
| `project`                 | This repo only                                       |
| `org`                     | Other teams only — "has anyone else solved this?"    |

A hit from another team carries a `project` field; a hit from your own does not.
That presence *is* the signal that a result crossed a boundary, so an agent can
weigh it as a lead rather than as fact about your repo.

```bash
# payments stores a gotcha (org-wide by default)
TACIT_PROJECT=payments TACIT_TEAM=platform \
  tacit add /gotchas/webhook-header-casing.md --file ./note.md --category gotcha

# a different team, a different repo, finds it
TACIT_PROJECT=search-svc TACIT_TEAM=discovery \
  tacit search "why does my webhook signature check fail in staging"
# --- /gotchas/webhook-header-casing.md  (score 4.49, gotcha)  [from payments]
```

> **What visibility does and does not protect.** `private` and `team` are
> enforced against the *viewer* — the project and team the server was configured
> with — never against the project named in a tool call. Naming another team's
> project routes your request to it, but cannot grant you its privileges, so an
> agent (or a prompt-injected repo) cannot read or overwrite another team's
> private notes through the shared endpoint. What visibility does **not** give
> you is protection of `org` memories: anything published org-wide is reachable
> by anyone who can call the endpoint, by design. Real access control is Entra
> RBAC on the Search service plus the Functions key — **never store secrets or
> credentials in a memory of any visibility.**
>
> The deployed Functions endpoint authenticates with one shared system key, so
> it cannot tell callers apart: memories it writes are attributed to its
> configured `TACIT_PROJECT`/`TACIT_TEAM`, and `private` memories of *other*
> projects are invisible through it. Use `team` visibility to share across your
> own team's repos, and the stdio variant — where each engineer runs under their
> own Entra identity and `TACIT_TEAM` — for per-person attribution.

## The shared vocabulary: one thing, many names

Reach is only half the problem. Payments writes "pmt-gw", platform writes "the
gateway", the new hire asks about "the payments gateway" — three names, one
system, and no ranker bridges them, because the connection is a fact about *your
organization*, not about English.

So tacit keeps a small controlled vocabulary of canonical entities and the
aliases teams actually type:

```bash
uv run tacit ontology add "Payments Gateway" \
    --aliases "pmt-gw,the gateway,Stripe proxy" --kind system
uv run tacit ontology list
uv run tacit reindex      # apply it to memories already stored
```

Before, and after, with the memory unchanged:

```
$ tacit search "payments gateway connection timeouts"     # before
no hits

$ tacit search "payments gateway connection timeouts"     # after
--- /gotchas/pmt-gw-timeout.md  (score 1.87, gotcha)  [from payments]
# pmt-gw drops connections above 30s
```

It works by **normalizing on write, not expanding on read**: every chunk is
annotated with the canonical ids it mentions plus every alias of those entities
as searchable text. A memory written in one team's words therefore carries all
of them, so query latency is untouched, the semantic ranker still sees the
user's real question, and the vocabulary can grow without any query path
changing. Matching is deterministic (longest alias first, on word boundaries) —
no model, no embedding drift, and `tacit ontology export` round-trips it as JSON
so the vocabulary can live in a repo and be reviewed like code.

Agents can also filter to one entity — `memory_search(entity="payments-gateway")`
is "everything the org knows about this thing, whatever each team calls it".

Widening the vocabulary changes annotations, which live on chunks, so follow an
`ontology add`/`import` with `tacit reindex`.

## Seeing the overlap

The argument for adopting this is easier to see than to describe, so the server
also renders it:

```bash
uv run tacit ui                     # local, reads through your own identity
```

Entities sit in the middle, the projects that wrote about them around the
outside, and an entity known to **more than one team turns orange** — that is
knowledge somebody is about to rediscover the hard way. Click an entity to see
the memories behind it and which team each came from.

The deployed Function App serves the same page from the same origin as its
data, so there is no CORS to configure and no key in the page:

```
https://<app>.azurewebsites.net/api/ui?code=<function key>
```

The graph is built from the same `visible_memories` call that search uses, so
it is **per-viewer**: a private memory contributes no node, no edge, and no
count. Two people looking at the same organization can legitimately see
different graphs.

## The model, mapped

| Anthropic managed agents       | tacit                                             |
| ------------------------------ | ------------------------------------------------- |
| Memory store                   | Shared AI Search index set, partitioned by project |
| Path-addressed memory          | Search doc keyed by project + path slug           |
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

# A DIFFERENT team's repo reaches the same knowledge:
uv run tacit search "webhook signature fails staging" --backend local --project search-svc

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

`memory_search` (the hero — ranked hits across teams, answer-ready) ·
`memory_brief` (one-call onboarding pack) · `memory_read` · `memory_list` ·
`memory_create` · `memory_update` (sha-preconditioned) · `memory_delete`
(tombstone) · `memory_versions` (audit trail).

`memory_search` takes `scope` and `entity`; `memory_create`/`memory_update` take
`visibility`. Everything else is scoped to the calling project.

`tacit ontology add|list|remove|import|export` curates the shared vocabulary.

### MCP prompts and the setup tool — how adoption actually happens

Wiring the server up gives an agent the *ability* to use memory; it does not
make it do so. **`tacit_setup` closes that gap**: a colleague's agent calls it
once per repo and gets back the standing instructions to write into `AGENTS.md`
(plus `CLAUDE.md` / `.github/copilot-instructions.md` when those exist).
Committed, that configures everyone on the repo.

It is offered as a **tool**, not only a prompt, and that is deliberate — see
"Adoption is a design problem" in [DESIGN.md](DESIGN.md). Tools reach every
client and every transport; MCP prompts do not.

`tacit_onboard` · `tacit_recall` · `tacit_remember` · `tacit_harvest` are the
day-to-day habits; `tacit_harvest` at the end of a session is what reliably gets
learnings written down.

The instruction block has one source — `clients.agents_md_snippet()` — so
`tacit install`, the `tacit_setup` tool and the `tacit_setup` prompt cannot
drift into describing the workflow differently.

> **Known limitation — prompts are not served over HTTP.** The Functions MCP
> extension's prompt trigger registers, but invoking one returns JSON-RPC
> `-32603`: working invocation needs `azure-functions` 2.x, which requires
> Python ≥3.13, while the remote Oryx build resolves 3.12 regardless of the
> configured runtime. Rather than advertise slash commands that always error,
> **the Functions app registers no prompts at all** (set
> `TACIT_ENABLE_MCP_PROMPTS=true` to re-enable once the platform supports it).
> The stdio server still registers them, where they work. Copilot Studio does
> not support MCP prompts either. **`tacit_setup` is therefore a tool**, and
> every workflow is reachable in plain language on every client.

### Configuration

| Env var                     | Meaning                                              |
| --------------------------- | ---------------------------------------------------- |
| `TACIT_SEARCH_ENDPOINT`     | Azure AI Search service                              |
| `TACIT_PROJECT`             | Repo slug this process reads/writes (stdio infers it) |
| `TACIT_TEAM`                | Owning team — resolves `visibility: team`            |
| `TACIT_DEFAULT_VISIBILITY`  | Visibility for new memories (default `org`)          |
| `TACIT_BACKEND`             | `search` or `local`                                  |

## Deploy the shared runtime to Azure

```bash
azd up                          # AI Search + Flex Consumption Functions + RBAC
uv run tacit provision --search-endpoint https://<svc>.search.windows.net
uv run tacit seed samples/memories --backend search \
    --search-endpoint https://<svc>.search.windows.net --project contoso-payments
```

`tacit provision` creates the four shared indexes (`tacit-memories`,
`tacit-versions`, `tacit-chunks`, `tacit-ontology`) and is run **once per Search
service**, not once per team — every project writes into the same set, which is
what lets one team's memory answer another team's question. Onboarding a new
team is just pointing it at the endpoint with its own `TACIT_PROJECT`; the store
creates what it needs on first write, and costs no additional indexes.

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
  concurrency, tombstones, structured conflicts — to an *organizational* store
  where cross-team search and shared access matter more than local files.
- **foundry-iq-cli** answers "what do the *documents* say" (Azure AI Search
  knowledge bases over your docs). tacit answers "what has the *team
  already learned*". They compose: wire both MCP servers and an agent checks
  team memory first, falls back to the doc KB, then to the repo.

## Development

```bash
uv sync --extra dev
uv run --extra dev pytest     # 261 tests, hermetic — no Azure calls
az bicep build --file infra/main.bicep --stdout > /dev/null   # infra lint
```

Layout and design rationale: [DESIGN.md](DESIGN.md). Security red lines: no
keys/secrets in payloads, config, skills, or MCP wiring; mutations always
require the caller's `expected_sha256`; dreams never modify their input store;
visibility is a relevance boundary, never a substitute for RBAC.
