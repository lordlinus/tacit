# tacit — design

An **organizational memory** for AI coding agents, modeled on Anthropic's
managed-agents **memory stores** + **dreams**, rebuilt on Azure so *any* agent
(GitHub Copilot, Claude Code, Cursor — anything that speaks MCP) on *any* team
can share one memory.

## The hypothesis

> When engineer #1's agent learns a project (architecture, gotchas, conventions,
> hard-won fixes), those learnings should be written to a **shared, searchable
> memory**. Engineer #2's agent then answers onboarding questions from
> memory hits (a few hundred tokens each) instead of re-reading and re-deriving
> them from the repo (tens of thousands of tokens) — and never relearns a gotcha
> the hard way.
>
> The same holds one level up: team B should not re-pay for what team A already
> learned about the shared gateway, the shared rate limiter, the shared
> migration footgun.

The benchmark in `benchmark/` tests exactly this: the same onboarding questions
answered **cold** (agent explores the repo) vs **warm** (agent queries team
memory), with token counts for both.

## Mapping Anthropic's model onto Azure

| Anthropic managed agents          | tacit                                          |
| --------------------------------- | ------------------------------------------------------- |
| Memory store (`memstore_...`)     | Shared index set, partitioned by a `project` field      |
| Memory (path-addressed doc)       | Search document keyed by `(project, path)`              |
| Memory version (`memver_...`)     | Doc in the companion `tacit-versions` index             |
| `content_sha256` precondition     | Same — optimistic concurrency on update/delete          |
| Mounted directory + file tools    | **MCP tools** served by Azure Functions (native MCP)    |
| Dreams (curation pipeline)        | `tacit dream` — store + transcripts → new store |
| 2,000-memory cap per store        | Soft cap enforced per project in the service layer      |

Three deliberate upgrades over the "mounted directory" model:

1. **Search is first-class.** Memories live in AI Search, so `memory_search`
   is semantically ranked, not directory listing — the agent pulls the 2–3
   relevant memories for a question instead of reading the whole store.
2. **Vendor-neutral access.** The store is exposed over MCP from Azure
   Functions, so GHCP and Claude on the same team hit the *same* memory.
3. **The store is organization-wide, not team-wide.** A mounted directory has
   exactly one boundary; a query here can deliberately cross project boundaries
   as far as each memory's visibility allows.

## Why one shared index set

`project`, `team` and `visibility` are filterable fields on one index set
(`tacit-memories`, `tacit-versions`, `tacit-chunks`, `tacit-ontology`) rather
than a name baked into per-project indexes. Two reasons:

* **A query must be able to cross a project boundary.** If a search hits exactly
  one project's index, knowledge is invisible the moment it leaves your repo —
  which makes it a team memory, not an organizational one, and means the second
  team to hit a problem pays the first team's cost again.
* **Index count must not grow with the number of teams.** Three indexes per
  project exhausts a Basic service (15 indexes) at five teams and a Standard one
  (50) at sixteen. Onboarding a team should cost nothing.

A cross-team query is therefore one request, and a scoped one is the same
request with a narrower filter. Documents are keyed `<project>--<path-slug>` so
two teams may both keep `/gotchas/retry.md` without colliding.

The alternative — per-project indexes plus N parallel queries fanned out and
merged — was rejected: it is O(teams) requests per search, it still hits the
index cap, and merging N independently-ranked result sets is strictly worse than
letting one ranker see all candidates.

## Scope, visibility, and what they are not

Reach is the product of two things: the memory's `visibility` (`org` / `team` /
`private`) and the query's `scope` (`project` / `project+org` / `org`).

Defaults matter more than the mechanism. Memories default to `org` because
knowledge that cannot leave its team is not organizational memory; searches
default to `project+org` because an agent that has to *know* to ask for the rest
of the organization will not ask. Home-project hits get a modest boost
(`HOME_PROJECT_BOOST`) rather than a hard sort key, so local knowledge wins ties
but another team's clearly better answer still surfaces first.

The rules live in exactly one place, `tacit/scope.py`, which emits the OData
filter every read path sends to Azure — search, `read`, `list`, `versions` and
the overlap graph all derive their filter from it rather than writing their own,
because a divergence would either hide a team's knowledge or leak a private
note, and neither failure shows up as a failing search.

**Permission is evaluated against the viewer, never the routed project.** One
endpoint serves every repo, and the client picks which one it is asking about —
but on a shared endpoint that choice is an unverifiable hint, and the agent
making the call is itself steerable by repo content. So `scope.py` splits the
decision in two: the *shape* (which projects are candidates) comes from the
caller's scope and routed project, while the *permission* (which of those may be
read) comes from a `Viewer` built from this server's own configuration. Naming
another team's project therefore routes a request to it without granting its
privileges. The same check gates `read`, `list` and `versions`, because
otherwise `memory_read` would simply be a way around the search filter, and the
audit trail — which carries the full content of every version — a way around
`memory_read`. A denied read reports `not_found` rather than a permission error:
confirming that a path exists inside another team's project is itself a
disclosure. Mutations inherit the check for free, since they require a
`content_sha256` that only a successful read can supply.

`TACIT_TRUST_ROUTED_PROJECT` was considered as an escape hatch for servers whose
callers are all trusted, and rejected: the case it would serve — one team, one
server, several of its own repos — is exactly what `visibility="team"` is for,
and that is checked against the server's configured team rather than a name the
caller supplied. Keeping `private` to mean "this repo only" leaves a rule with
no exceptions, and no flag for a misconfigured deployment to turn on.

What visibility does *not* buy you is protection of `org` memories: anything
published org-wide is reachable by anyone who can call the endpoint, by design.
Access control is Entra RBAC on the Search service plus the Functions key, and
the README says plainly that no memory of any visibility should hold a secret.

## The shared vocabulary

Reach solves "your memory is invisible to me". It does not solve "we call it
different things". Payments writes `pmt-gw`, platform writes "the gateway", the
asker types "the payments gateway" — one system, three names, and neither BM25
nor a semantic reranker bridges them, because the equivalence is a fact about
this organization rather than about language.

`tacit/ontology.py` holds that fact: canonical entities plus the aliases teams
actually type. It is applied **at write time**. Every chunk is annotated with
the canonical ids it mentions (`entities`, filterable) and with every alias of
those entities as searchable text (`entity_vocabulary`). A memory written in one
team's words therefore carries all of them, and a question in any team's words
matches through ordinary ranking.

Normalizing on write rather than expanding on read was the deliberate choice:

* query latency is untouched — no vocabulary lookup on the hot path;
* the semantic ranker keeps seeing the user's real question, rather than an
  OR-expanded soup of aliases that dilutes L2 reranking;
* the vocabulary can grow without any query path changing — widening it is a
  re-chunk (`tacit reindex`), which is a job, not a request.

The cost is exactly that: annotations are stale until re-chunked. That is an
acceptable trade for a vocabulary that changes a few times a quarter, and the
CLI says so after every mutation.

Matching is deterministic — longest surface form first, on word boundaries — so
"the Payments Gateway" resolves to the gateway rather than a generic "gateway"
entity, and `kafka` does not fire on `kafkaesque`. No model is involved, which
keeps it hermetic to test, free to run, and stable over time; curating the
vocabulary is a human act, and `tacit ontology export` emits JSON so it can live
in a repo and be reviewed like code.

The vocabulary is **organization-wide, not per team** — a per-team vocabulary
would defeat its own purpose. A missing or unreachable one degrades to no
annotation rather than failing the write: memory is useful without it, and a
vocabulary outage must not stop someone recording what they just learned.

## The overlap graph

Adoption is an argument, and the argument is easier to see than to read. The
graph puts entities in the middle and the projects that wrote about them around
the outside; an entity touched by two or more projects is highlighted, because
that is knowledge about to be rediscovered.

Three decisions:

* **Entities are the hubs, not memories.** A memory-level graph is a hairball
  that shows *activity*; an entity-level one shows *overlap*, which is the only
  thing a viewer can act on.
* **It is built from `visible_memories`, not from its own query.** The graph
  aggregates across every project, which makes it the most likely place for a
  visibility leak and the least likely place to notice one — a leak appears as
  a slightly larger count, not an error. Sharing the store method means it
  cannot drift from what search enforces, and pins the subtle case: a private
  memory must not make a shared entity *look* shared.
* **Annotation is recomputed at build time** from the current vocabulary rather
  than read from stored chunk annotations. If the two disagree the graph is
  right and the chunks are stale, which is the direction that prompts someone
  to run `reindex` rather than the direction that hides the problem.

The page (`ui.py`) is a module constant rather than a static asset: it vendors
into the Functions app with the rest of the package, needs no package-data
configuration, and is served from the same origin as `/api/graph` so there is no
CORS. It has no CDN reference, no framework and no build step — the force
simulation is about forty lines of plain JavaScript over SVG — because the
network this gets demoed in may not be able to reach a CDN at all.

## Invariants (inherited from PEMP)

1. Memory is **immutable**: update appends a version; delete writes a tombstone
   version. Nothing is erased; the versions index is the audit trail.
2. Every mutation requires the caller to present `expected_sha256` from its last
   read; a mismatch returns a structured `sha_conflict` (not an opaque error) so
   agents re-read and retry deliberately.
3. **Keyless-first** (from foundry-iq): auth is `DefaultAzureCredential` /
   managed identity; no keys in payloads, config, or MCP wiring.
4. Dreams never modify their input: consolidation writes a **new** store
   (a fresh project slug); you review, then switch over.
5. **Only search crosses a project boundary, and only within permission.**
   `get`, `list`, `count`, `versions` and every mutation are scoped to the
   calling project, so the sha precondition contract stays per-project and no
   store can write into another team's namespace. Every read path — search,
   `read`, `list`, `versions` — is additionally gated on the viewer, so routing
   to a project never confers that project's privileges.

## Components

```
src/tacit/
    models.py        Memory / MemoryVersion / Visibility / SearchScope
    scope.py         the one definition of reach: the OData filter
    ontology.py      the org's shared vocabulary + deterministic matcher
    graph.py         the cross-team overlap graph (pure: memories + ontology)
    ui.py            the single-page graph UI, shipped as a module constant
    errors.py        NotFound / Duplicate / ShaConflict (structured)
    store.py         MemoryStore protocol
    search_store.py  Azure AI Search backend (keyless REST)
    search_index.py  shared index schemas + provision (create-if-missing)
    embeddings.py    Azure OpenAI embeddings — the vector half of hybrid search
    service.py       validation, concurrency, tombstones, provenance stamping
    dream.py         consolidation: store + transcripts → new store
    tokens.py        token estimation (heuristic ~4 chars/token)
    config.py        TACIT_* settings (pydantic-settings)
    mcp_stdio.py     stdio MCP server (per-engineer Entra identity)
    cli.py           typer: provision / ontology / seed / search / dream / bench
functions/           Azure Functions app — MCP tool trigger per memory tool
infra/               bicep + azd: AI Search + Flex Consumption Functions + RBAC
samples/             contoso-payments sample repo, seed memories, transcripts
benchmark/           the token-efficiency experiment + generated RESULTS.md
```

### MCP tools (identical surface from Functions and stdio)

| Tool              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `memory_search`   | Semantic search over sections, across teams — the hero          |
| `memory_brief`    | One-call onboarding pack (this project's `onboarding` memories) |
| `memory_read`     | Full memory by path (returns `content_sha256`)                  |
| `memory_list`     | Paths + titles for this project, optional prefix filter         |
| `memory_create`   | New memory at a path (fails if it exists)                       |
| `memory_update`   | New version; requires `expected_sha256`                         |
| `memory_delete`   | Tombstone; requires `expected_sha256`                           |
| `memory_versions` | Audit trail for a path                                          |

### Adoption is a design problem, not a documentation one

Nothing auto-populates. A memory exists only because an agent called
`memory_create`, and an agent calls it only if something told it to. Connecting
the server and hoping is the failure mode this design has to defend against, so
the countermeasures are structural:

1. **Tool descriptions carry the instruction.** `memory_search` opens with
   "ALWAYS try this before exploring the repo" — the one instruction every
   client sees, including those that support no prompts at all.
2. **`tacit_setup` writes the standing instructions into the repo.** One call,
   made once, that leaves `AGENTS.md` configured and committed. After that the
   habit applies to every agent and every teammate on that repo, with nobody
   remembering anything.
3. **`tacit_harvest` makes writing a ritual** rather than a judgement call made
   mid-task, which is when it never happens.

`tacit_setup` is exposed **as a tool as well as a prompt**, which looks like
duplication and is not. MCP prompts do not reach everyone:

* **Copilot Studio supports MCP tools and resources but not prompts** — so
  exactly the users least likely to hand-configure an agent cannot run a prompt.
* On the **Azure Functions HTTP transport**, prompts register but cannot be
  invoked: `prompts/list` succeeds while `prompts/get` returns JSON-RPC
  `-32603`. The extension's prompt trigger needs `azure-functions` 2.x, which
  requires Python ≥3.13, while the remote Oryx build resolves 3.12 regardless
  of the configured runtime version.

So the Functions app registers **no prompt triggers at all** (opt back in with
`TACIT_ENABLE_MCP_PROMPTS=true`). Advertising a slash command that always errors
is worse than offering none: a first-time user sees "Error resolving prompt" and
concludes the server is broken, which is precisely the impression a memory
nobody trusts never recovers from. The stdio server, where prompts work, still
registers them.

A capability that is unavailable on the transport most colleagues use is not a
capability to build adoption on. The tool is the supported path; the prompt is a
convenience where it happens to work.

The instruction block lives in exactly one place, `clients.agents_md_snippet()`,
rendered by `tacit install` (for the admin), the `tacit_setup` tool (every
client) and the `tacit_setup` prompt (stdio). Three copies would eventually
describe three different workflows; a test asserts they agree.

### Retrieval: sections, semantic ranking, progressive disclosure

A memory store is only worth its tokens if a hit costs less than reading the
repo. Four decisions make that true:

**Sections are the retrieval unit.** Each memory is split on level-2 headings
into an index of its own, `tacit-chunks`. The split is *adaptive*: a
memory with no `##` headings — tacit's usual "one focused fact" shape — stays a
single chunk, so short memories behave exactly as before. Long memories (a
runbook, an ADR) gain granularity: asking about refunds returns the refunds
section, not the whole runbook.

The chunks index is **derived**. `tacit-memories` remains the system of record
for `get`/`list`/`count` and the `content_sha256` preconditions; chunk keys are
`<project>--<path>--s-<slug>`, so re-projection is idempotent. `tacit reindex`
rebuilds it, which is how a widened vocabulary reaches memories that were
already stored.

**Semantic ranking, with a fallback.** Queries use `queryType: semantic` with
extractive captions, so a plain-language question outranks keyword overlap. A
scoring profile (title ×3, tags ×2, plus freshness) shapes the BM25 candidate
set. If a service tier declines semantic search, the store downgrades to BM25
permanently for that process rather than failing the query — and the scoring
profile, which the L2 reranker would otherwise never see, is applied on that
path.

**Hybrid, when an embedding deployment exists.** The vocabulary solves "we call
it different things" only for names somebody thought to curate. Vectors cover
the rest: a question about "the thing that rewrites webhook headers" reaching a
memory that only ever says "lowercases the signature header". Each section is
embedded with its memory's title prepended — sections are retrieved
independently, and `## Draining` alone carries no clue what is being drained —
and the same request then sends both a text query and a vector query, which
Azure fuses with RRF before the semantic ranker orders the survivors. `k` is the
reranker's 50-row window rather than `top`, because a smaller `k` starves the
stage that decides the final order.

Vectors are **opt-in**, and degrade in three separate places, because retrieval
must never become the reason a memory is lost or a question goes unanswered:

* no embedding endpoint configured — the field is never added to the index and
  every query is exactly what it was before;
* an embedding call fails *on write* — the chunk is stored without a vector
  (omitted, not empty: the field has a fixed dimension) and is still findable by
  BM25 and the ranker until the next `reindex`;
* an embedding call fails *on query* — that one search runs text-only, and
  deliberately does **not** stick, since a transient blip must not silently
  halve retrieval quality for the life of the process.

Only a rejection by the *service* is sticky, mirroring the semantic downgrade,
and it unwinds in two steps because there are two distinct causes. An index that
has the vector field but no vectorizer means "embed here instead"; an index with
neither means "drop that half". A single flag for both would turn a missing
vectorizer into a permanent loss of vector recall.

**Who embeds, and why it differs by direction.** Queries use *integrated
vectorization*: the index carries an `AzureOpenAIVectorizer`, so a question
travels as plain text and the search service embeds it under its own managed
identity. That keeps the embedding call off the agent's hot path and confines
model access to one principal instead of every engineer's. Writes cannot work
that way — index-time integrated vectorization requires an indexer and skillset
over a crawlable data source, and memories are *pushed* through the documents
API, which is what makes `content_sha256` preconditions possible in the first
place. So section vectors are always computed by the writer. The asymmetry is
inherent to the write model, not an oversight.

That is also the upgrade path — adding a field is one of the schema changes
Azure applies without a rebuild, so switching vectors on is `provision` +
`reindex`, not a migration.

**Results are over-fetched, then thinned.** Only the best section of each memory
is returned, and home-project hits are boosted after the service ranks. Both
reorder and drop rows, so asking for exactly `top` would routinely return fewer
than `top`; the store requests a bounded multiple and trims afterwards.

**One field, progressively narrowed.** A hit carries the matched section; if
that section is itself long, it is replaced by the caption/highlight extract and
flagged `truncated`, meaning "call `memory_read` for the rest". Never both — a
snippet sitting next to the text it summarises is duplication the caller pays
for twice. Measured: emitting both dropped the benchmark from 65% to 54%.

Cross-team hits carry one extra field, `project`, and only when the hit did
*not* come from the caller's own project. Its presence is the signal that the
result crossed a boundary; on a same-project hit the field would be per-call
noise, so it is elided — the same token economy that governs `heading` and
`truncated`.

### On "AI Search serverless"

Both halves are consumption-based by default:

- **Store:** AI Search's **Serverless tier** (preview, `sku: serverless` on
  `Microsoft.Search/searchServices@2026-03-01-preview`) — billed per Compute
  Unit-hour + GB stored, capacity fully managed, no replicas/partitions to
  configure. Preview caveats: regions limited to westcentralus /
  switzerlandnorth / japaneast, no SLA, no tier migration; the bicep takes
  `searchSku=basic|standard|free` for everything else. (The preview's missing
  File Knowledge Source doesn't matter here — we use plain indexes.)
- **Runtime:** Functions **Flex Consumption** with the MCP extension
  (preview) — scale-to-zero, pay-per-execution, native `mcpToolTrigger`
  bindings.

### Dream pipeline

`dream(input_store, transcripts) -> output_store`, deterministic by default:

1. Read all active memories; group near-duplicates (normalized-title similarity).
2. Merge each group: newest content wins contradictions; union of tags; merge
   provenance into the body's `Sources` line.
3. Mine transcripts for insight markers (`LEARNED:`, `GOTCHA:`, resolved-error
   patterns) → new candidate memories not already covered.
4. Write everything to a fresh output store; input untouched.

An `LlmConsolidator` hook exists for Azure OpenAI-powered curation (same
interface); the default heuristic keeps the sample hermetic and testable.

## Benchmark design (honesty rules)

- Cold path is a *scripted exploration trace* per question: the directory
  listing, greps, and full-file reads a competent agent would actually perform.
  We charge it only what real tool output would contain.
- Warm path charges everything the agent sees: the tool schemas' overhead,
  the search call, and the full returned snippets.
- Token counts use a stated heuristic (≈4 chars/token) applied identically to
  both paths; swap in a real tokenizer without changing the harness.
- Results report per-question and totals, plus amortization: memory-writing
  cost is charged to engineer #1 and divided across subsequent engineers.
