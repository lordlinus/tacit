"""The token-efficiency experiment.

Two agents answer the same onboarding questions about contoso-payments:

- **cold** — repo access only: lists the tree once per session, then reads
  the files needed per question (the scripted traces in scenarios.py).
- **warm** — team memory access only: one memory_search per question; the
  tokens charged are the *actual serialized tool results* the agent would see.

Both sides pay the same per-tool-call framing overhead and the same question
text, so those cancel; what differs is payload volume. The harness verifies
each warm answer actually contains the expected fact — cheap but wrong would
prove nothing.

Run: ``uv run foundry-memory bench`` (or ``uv run python -m benchmark.bench``).
Writes benchmark/RESULTS.md.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from foundry_memory.cli import parse_memory_file
from foundry_memory.local_store import LocalStore
from foundry_memory.service import MemoryService
from foundry_memory.tokens import estimate_tokens
from foundry_memory.tools import call_tool

from .scenarios import SCENARIOS, Scenario

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = REPO_ROOT / "samples" / "contoso-payments"
MEMORIES_DIR = REPO_ROOT / "samples" / "memories"
RESULTS_PATH = Path(__file__).resolve().parent / "RESULTS.md"

TOOL_CALL_OVERHEAD = 15  # request framing tokens per tool invocation, both arms
SEARCH_TOP = 2  # hits per warm query — what a focused agent asks for


@dataclass
class ScenarioResult:
    scenario: Scenario
    cold_tokens: int
    cold_calls: int
    warm_tokens: int
    warm_calls: int
    answered: bool
    top_hit: str

    @property
    def saving_pct(self) -> float:
        return 100.0 * (1 - self.warm_tokens / self.cold_tokens)


def project_listing() -> str:
    """The `ls -R`-equivalent output a cold agent reads once per session."""
    lines = []
    for file in sorted(PROJECT_DIR.rglob("*")):
        if file.is_file():
            lines.append(str(file.relative_to(PROJECT_DIR)))
    return "\n".join(lines)


def seed(service: MemoryService) -> int:
    """Engineer #1's memory-writing cost in tokens (create calls + content)."""
    spent = 0
    for file in sorted(MEMORIES_DIR.glob("*.md")):
        meta, content = parse_memory_file(file.read_text(encoding="utf-8"))
        service.create(
            meta["path"],
            content,
            category=meta.get("category", "general"),
            tags=[t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
        )
        spent += estimate_tokens(content) + TOOL_CALL_OVERHEAD
    return spent


def run_cold(scenario: Scenario, listing_tokens: int) -> tuple[int, int]:
    tokens = listing_tokens + TOOL_CALL_OVERHEAD  # the session's tree listing
    calls = 1
    for rel_path in scenario.cold_trace:
        tokens += estimate_tokens((PROJECT_DIR / rel_path).read_text(encoding="utf-8"))
        tokens += TOOL_CALL_OVERHEAD
        calls += 1
    return tokens, calls


def run_warm(service: MemoryService, scenario: Scenario) -> tuple[int, int, bool, str]:
    hits = call_tool(service, "memory_search", {"query": scenario.warm_query, "top": SEARCH_TOP})
    payload = json.dumps(hits, ensure_ascii=False)
    tokens = estimate_tokens(payload) + TOOL_CALL_OVERHEAD
    answered = any(scenario.expect.lower() in (h["content"] or "").lower() for h in hits)
    top_hit = hits[0]["path"] if hits else "(no hits)"
    return tokens, 1, answered, top_hit


def run() -> tuple[list[ScenarioResult], int]:
    with tempfile.TemporaryDirectory() as tmp:
        service = MemoryService(LocalStore(tmp), actor="engineer-1-agent")
        seed_cost = seed(service)
        listing_tokens = estimate_tokens(project_listing())
        results = []
        for scenario in SCENARIOS:
            cold_tokens, cold_calls = run_cold(scenario, listing_tokens)
            warm_tokens, warm_calls, answered, top_hit = run_warm(service, scenario)
            results.append(
                ScenarioResult(
                    scenario, cold_tokens, cold_calls, warm_tokens, warm_calls, answered, top_hit
                )
            )
        return results, seed_cost


def render(results: list[ScenarioResult], seed_cost: int) -> str:
    cold_total = sum(r.cold_tokens for r in results)
    warm_total = sum(r.warm_tokens for r in results)
    saving = 100.0 * (1 - warm_total / cold_total)
    all_answered = all(r.answered for r in results)

    lines = [
        "# Token-efficiency results: cold vs warm onboarding",
        "",
        "Six onboarding questions about `samples/contoso-payments`, answered by",
        "a **cold** agent (repo exploration) vs a **warm** agent (one",
        f"`memory_search`, top {SEARCH_TOP} hits). Token counts via the heuristic in",
        "`foundry_memory/tokens.py`, applied identically to both arms;",
        f"{TOOL_CALL_OVERHEAD} tokens/tool-call framing charged to both.",
        "",
        "| question | cold (tokens / calls) | warm (tokens / calls) | saving | warm answered? | top hit |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.scenario.id} | {r.cold_tokens:,} / {r.cold_calls} "
            f"| {r.warm_tokens:,} / {r.warm_calls} "
            f"| {r.saving_pct:.0f}% | {'yes' if r.answered else 'NO'} | `{r.top_hit}` |"
        )
    lines += [
        "|---|---|---|---|---|---|",
        f"| **total** | **{cold_total:,}** | **{warm_total:,}** | **{saving:.0f}%** "
        f"| {'all verified' if all_answered else 'FAILURES'} | |",
        "",
        "## Amortization",
        "",
        f"Engineer #1's agent spent **{seed_cost:,} tokens** writing these memories",
        "(content + create calls). Every subsequent engineer saves",
        f"**{cold_total - warm_total:,} tokens** on just these six questions, so the",
        "write cost pays back **before the second engineer finishes day one** —",
        "and keeps paying for every engineer after:",
        "",
        "| team members onboarded | cold total | warm total (incl. one-time write) | saving |",
        "|---|---|---|---|",
    ]
    for n in (1, 2, 5, 10):
        cold_n = cold_total * n
        warm_n = warm_total * n + seed_cost
        lines.append(
            f"| {n} | {cold_n:,} | {warm_n:,} | {100.0 * (1 - warm_n / cold_n):.0f}% |"
        )
    lines += [
        "",
        "## Honesty notes",
        "",
        "- The cold traces charge only the files a competent agent must read —",
        "  no wrong turns, no re-reads — so the cold numbers are a *lower bound*.",
        "  Real cold exploration (greps that miss, reading the wrong module,",
        "  rediscovering the incident report) costs more.",
        "- The warm agent is charged the full serialized tool results it sees.",
        "- Not counted on either side (identical): system prompt, tool schemas,",
        "  the question text, and the model's own answer tokens.",
        "- 'warm answered?' verifies the expected fact is literally present in",
        "  the returned memories — cheap-but-wrong would not count.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    results, seed_cost = run()
    report = render(results, seed_cost)
    RESULTS_PATH.write_text(report, encoding="utf-8")
    print(report)
    failures = [r.scenario.id for r in results if not r.answered]
    if failures:
        raise SystemExit(f"hypothesis check FAILED for: {', '.join(failures)}")


if __name__ == "__main__":
    main()
