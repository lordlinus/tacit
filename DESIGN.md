# tacit — design

A mini **enterprise team memory** for AI coding agents, modeled on Anthropic's
managed-agents **memory stores** + **dreams**, rebuilt on Azure so *any* agent
(GitHub Copilot, Claude Code, Cursor — anything that speaks MCP) can share one
project memory.

## The hypothesis

> When engineer #1's agent learns a project (architecture, gotchas, conventions,
> hard-won fixes), those learnings should be written to a **shared, searchable
> team memory**. Engineer #2's agent then answers onboarding questions from
> memory hits (a few hundred tokens each) instead of re-reading and re-deriving
> them from the repo (tens of thousands of tokens) — and never relearns a gotcha
> the hard way.

The benchmark in `benchmark/` tests exactly this: the same onboarding questions
answered **cold** (agent explores the repo) vs **warm** (agent queries team
memory), with token counts for both.

## Mapping Anthropic's model onto Azure

| Anthropic managed agents          | tacit                                          |
| --------------------------------- | ------------------------------------------------------- |
| Memory store (`memstore_...`)     | One Azure AI Search index per project (`tm-<project>`)  |
| Memory (path-addressed doc)       | Search document keyed by path slug                      |
| Memory version (`memver_...`)     | Doc in a companion `tm-<project>-versions` index        |
| `content_sha256` precondition     | Same — optimistic concurrency on update/delete          |
| Mounted directory + file tools    | **MCP tools** served by Azure Functions (native MCP)    |
| Dreams (curation pipeline)        | `tacit dream` — store + transcripts → new store |
| 2,000-memory cap per store        | Soft cap enforced in the service layer (configurable)   |

Two deliberate upgrades over the "mounted directory" model:

1. **Search is first-class.** Memories live in AI Search, so `memory_search`
   is BM25-ranked full text, not directory listing — the agent pulls the 2–3
   relevant memories for a question instead of reading the whole store.
2. **Vendor-neutral access.** The store is exposed over MCP from Azure
   Functions, so GHCP and Claude on the same team hit the *same* memory.

## Invariants (inherited from PEMP)

1. Memory is **immutable**: update appends a version; delete writes a tombstone
   version. Nothing is erased; the versions index is the audit trail.
2. Every mutation requires the caller to present `expected_sha256` from its last
   read; a mismatch returns a structured `sha_conflict` (not an opaque error) so
   agents re-read and retry deliberately.
3. **Keyless-first** (from foundry-iq): auth is `DefaultAzureCredential` /
   managed identity; no keys in payloads, config, or MCP wiring.
4. Dreams never modify their input: consolidation writes a **new** store
   (`tm-<project>-dream-<n>`); you review, then switch over.

## Components

```
src/tacit/
    models.py        Memory / MemoryVersion (pydantic, path-addressed)
    errors.py        NotFound / Duplicate / ShaConflict (structured)
    store.py         MemoryStore protocol
    local_store.py   JSON-file backend — hermetic tests, offline dev, benchmark
    search_store.py  Azure AI Search backend (keyless REST, same ops)
    search_index.py  index schemas + provision (create-if-missing)
    service.py       validation, concurrency, tombstones, brief() onboarding pack
    dream.py         consolidation: store + transcripts → new store
    tokens.py        token estimation (heuristic ~4 chars/token)
    config.py        TACIT_* settings (pydantic-settings)
    mcp_stdio.py     local stdio MCP server over either backend
    cli.py           typer: provision / seed / search / read / dream / bench
functions/           Azure Functions app — MCP tool trigger per memory tool
infra/               bicep + azd: AI Search + Flex Consumption Functions + RBAC
samples/             contoso-payments sample repo, seed memories, transcripts
benchmark/           the token-efficiency experiment + generated RESULTS.md
```

### MCP tools (identical surface from Functions and stdio)

| Tool              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `memory_search`   | Semantic search over sections — the token-efficiency hero       |
| `memory_brief`    | One-call onboarding pack (all `onboarding`-category memories)   |
| `memory_read`     | Full memory by path (returns `content_sha256`)                  |
| `memory_list`     | Paths + titles, optional prefix filter                          |
| `memory_create`   | New memory at a path (fails if it exists)                       |
| `memory_update`   | New version; requires `expected_sha256`                         |
| `memory_delete`   | Tombstone; requires `expected_sha256`                           |
| `memory_versions` | Audit trail for a path                                          |

### Retrieval: sections, semantic ranking, progressive disclosure

A memory store is only worth its tokens if a hit costs less than reading the
repo. Three decisions make that true:

**Sections are the retrieval unit.** Each memory is split on level-2 headings
into an index of its own, `tm-<project>-chunks`. The split is *adaptive*: a
memory with no `##` headings — tacit's usual "one focused fact" shape — stays a
single chunk, so short memories behave exactly as before. Long memories (a
runbook, an ADR) gain granularity: asking about refunds returns the refunds
section, not the whole runbook.

The chunks index is **derived**. `tm-<project>` remains the system of record for
`get`/`list`/`count` and the `content_sha256` preconditions; chunk keys are
`path--s-<slug>`, so re-projection is idempotent. `tacit reindex` rebuilds it,
which is how a project provisioned before sections existed catches up.

**Semantic ranking, with a fallback.** Queries use `queryType: semantic` with
extractive captions, so a plain-language question outranks keyword overlap. A
scoring profile (title ×3, tags ×2, plus freshness) shapes the BM25 candidate
set, aligning Azure's ordering with the local backend's. If a service tier
declines semantic search, the store downgrades to BM25 permanently for that
process rather than failing the query — and the scoring profile, which the L2
reranker would otherwise never see, is applied on that path.

**One field, progressively narrowed.** A hit carries the matched section; if
that section is itself long, it is replaced by the caption/highlight extract and
flagged `truncated`, meaning "call `memory_read` for the rest". Never both — a
snippet sitting next to the text it summarises is duplication the caller pays
for twice. Measured: emitting both dropped the benchmark from 65% to 54%.

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
