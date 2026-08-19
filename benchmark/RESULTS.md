# Token-efficiency results: cold vs warm onboarding

Six onboarding questions about `samples/contoso-payments`, answered by
a **cold** agent (repo exploration) vs a **warm** agent (one
`memory_search`, top 2 hits). Token counts via the heuristic in
`tacit/tokens.py`, applied identically to both arms;
15 tokens/tool-call framing charged to both.

Warm backend: **local** — the hermetic local backend (reproducible without an Azure account).

> **Stale.** These numbers were produced by the local backend, which no longer
> exists. Regenerate against a live service with `uv run tacit bench` (needs
> `TACIT_SEARCH_ENDPOINT` and `az login`); the cold arm is unaffected, but the
> warm arm now comes from the semantic ranker rather than the local TF-IDF one.

| question | cold (tokens / calls) | warm (tokens / calls) | saving | warm answered? | top hit |
|---|---|---|---|---|---|
| dev-setup | 1,894 / 6 | 664 / 1 | 65% | yes | `/onboarding/dev-setup.md` |
| webhook-staging | 1,975 / 5 | 627 / 1 | 68% | yes | `/gotchas/webhook-header-casing.md` |
| idempotency | 2,210 / 5 | 552 / 1 | 75% | yes | `/architecture/idempotent-charges.md` |
| deploy | 1,127 / 4 | 642 / 1 | 43% | yes | `/gotchas/slot-swap-config-sentinel.md` |
| simulator-429 | 1,649 / 5 | 649 / 1 | 61% | yes | `/gotchas/simulator-429.md` |
| ci-rules | 1,230 / 4 | 271 / 1 | 78% | yes | `/conventions/ci-and-lint.md` |
|---|---|---|---|---|---|
| **total** | **10,085** | **3,405** | **66%** | all verified | |

## Amortization

Engineer #1's agent spent **1,539 tokens** writing these memories
(content + create calls). Every subsequent engineer saves
**6,680 tokens** on just these six questions, so the
write cost pays back **before the second engineer finishes day one** —
and keeps paying for every engineer after:

| team members onboarded | cold total | warm total (incl. one-time write) | saving |
|---|---|---|---|
| 1 | 10,085 | 4,944 | 51% |
| 2 | 20,170 | 8,349 | 59% |
| 5 | 50,425 | 18,564 | 63% |
| 10 | 100,850 | 35,589 | 65% |

## Honesty notes

- The cold traces charge only the files a competent agent must read —
  no wrong turns, no re-reads — so the cold numbers are a *lower bound*.
  Real cold exploration (greps that miss, reading the wrong module,
  rediscovering the incident report) costs more.
- The warm agent is charged the full serialized tool results it sees.
- Not counted on either side (identical): system prompt, tool schemas,
  the question text, and the model's own answer tokens.
- 'warm answered?' verifies the expected fact is literally present in
  the returned memories — cheap-but-wrong would not count.
- These numbers come from the local backend's ranker, which has been removed.
  Re-run with `tacit bench --project <slug>` against Azure AI Search to confirm
  the saving is not an artefact of it.
