#!/usr/bin/env bash
# The whole story, locally: seed -> onboard -> benchmark -> dream.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
export TACIT_LOCAL_ROOT="$(mktemp -d)"

banner() { printf '\n\033[1m== %s ==\033[0m\n\n' "$1"; }

banner "1. Engineer #1's agent stored 7 learnings about contoso-payments"
uv run tacit seed samples/memories --backend local --project contoso-payments

banner "2. Engineer #2's agent, day one: one search instead of reading the repo"
uv run tacit search "tests fail ModuleNotFoundError settlement_pb2" \
    --backend local --project contoso-payments --top 1

banner "3. The hypothesis, measured (full report: benchmark/RESULTS.md)"
uv run tacit bench | sed -n '/| question/,/| \*\*total\*\*/p'

banner "4. Dream: curate a messy store (2 stale duplicates) + mine 2 transcripts"
uv run tacit seed samples/memories-messy --backend local --project messy > /dev/null
uv run tacit dream --backend local --project messy \
    --output-project curated --transcripts samples/transcripts

banner "5. The curated store answers with the CURRENT fix, not the stale note"
uv run tacit search "429 parallel tests" --backend local --project curated --top 1
