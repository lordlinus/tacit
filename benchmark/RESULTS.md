# Token-efficiency results: cold vs warm onboarding

Six onboarding questions about `samples/contoso-payments`, answered by
a **cold** agent (repo exploration) vs a **warm** agent (one
`memory_search`, top 2 hits). Token counts via the heuristic in
`tacit/tokens.py`, applied identically to both arms;
15 tokens/tool-call framing charged to both.

Warm backend: **local** — the hermetic local backend (reproducible without an Azure account).

| question | cold (tokens / calls) | warm (tokens / calls) | saving | warm answered? | top hit |
|---|---|---|---|---|---|
| dev-setup | 1,894 / 6 | 682 / 1 | 64% | yes | `/onboarding/dev-setup.md` |
| webhook-staging | 1,975 / 5 | 645 / 1 | 67% | yes | `/gotchas/webhook-header-casing.md` |
| idempotency | 2,210 / 5 | 561 / 1 | 75% | yes | `/architecture/idempotent-charges.md` |
| deploy | 1,127 / 4 | 660 / 1 | 41% | yes | `/gotchas/slot-swap-config-sentinel.md` |
| simulator-429 | 1,649 / 5 | 667 / 1 | 60% | yes | `/gotchas/simulator-429.md` |
| ci-rules | 1,230 / 4 | 280 / 1 | 77% | yes | `/conventions/ci-and-lint.md` |
|---|---|---|---|---|---|
| **total** | **10,085** | **3,495** | **65%** | all verified | |

## Amortization

Engineer #1's agent spent **1,539 tokens** writing these memories
(content + create calls). Every subsequent engineer saves
**6,590 tokens** on just these six questions, so the
write cost pays back **before the second engineer finishes day one** —
and keeps paying for every engineer after:

| team members onboarded | cold total | warm total (incl. one-time write) | saving |
|---|---|---|---|
| 1 | 10,085 | 5,034 | 50% |
| 2 | 20,170 | 8,529 | 58% |
| 5 | 50,425 | 19,014 | 62% |
| 10 | 100,850 | 36,489 | 64% |

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
- Re-run against the real backend with
  `tacit bench --backend search --project <slug>`; the last such run
  scored **64%**, all six answered, confirming this local number is not
  an artefact of the local ranker.
