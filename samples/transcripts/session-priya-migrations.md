# Session: priya + Claude Code, 2026-06-03 — add refund table migration

(abridged transcript)

user: the refunds migration broke staging last week, make sure this one is safe

assistant: Looking at docs/deploy.md and the migration history... the previous
incident shipped a column drop in the same release as the code that stopped
using it, so the old code in the un-swapped slot crashed.

LEARNED: database migrations must be expand-contract across TWO releases — the
contract step (drops/renames) only ships after the release that stopped using
the old shape has fully swapped through both slots.

assistant: applied the expand step only; filed CP-1182 to ship the contract
step next release.
