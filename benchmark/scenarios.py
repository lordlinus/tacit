"""Onboarding scenarios: the questions a new engineer's agent answers in week 1.

Each scenario defines:
- ``cold_trace``: the files a competent agent actually reads to answer the
  question from the repo alone (it greps to *find* them, but must read them to
  answer). Relative to samples/contoso-payments/.
- ``warm_query``: the memory_search call a memory-aware agent makes instead.
- ``expect``: a substring the correct answer must contain — used to verify the
  warm path genuinely answers the question, not just that it's cheaper.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    id: str
    question: str
    cold_trace: list[str] = field(default_factory=list)
    warm_query: str = ""
    expect: str = ""


SCENARIOS = [
    Scenario(
        id="dev-setup",
        question="Tests fail with ModuleNotFoundError: contoso_payments._proto.settlement_pb2 — how do I set up the dev environment properly?",
        cold_trace=[
            "README.md",
            "CONTRIBUTING.md",
            "Makefile",
            "pyproject.toml",
            "docs/troubleshooting.md",
        ],
        warm_query="dev setup ModuleNotFoundError settlement_pb2 proto stubs bootstrap",
        expect="make bootstrap",
    ),
    Scenario(
        id="webhook-staging",
        question="Bank webhooks fail signature verification in staging but pass locally and in prod. Why?",
        cold_trace=[
            "src/contoso_payments/webhooks.py",
            "src/contoso_payments/app.py",
            "docs/incidents/2026-03-11-webhook-signatures.md",
            "docs/troubleshooting.md",
        ],
        warm_query="webhook signature verification fails staging only",
        expect="lowercase",
    ),
    Scenario(
        id="idempotency",
        question="Is it safe for clients to retry charge creation? How does idempotency work here?",
        cold_trace=[
            "src/contoso_payments/charges.py",
            "src/contoso_payments/idempotency.py",
            "src/contoso_payments/models.py",
            "docs/adr-007-idempotent-charges.md",
        ],
        warm_query="charge idempotency retry safe design outbox",
        expect="outbox",
    ),
    Scenario(
        id="deploy",
        question="What is the release process, and what must I not forget when deploying manually?",
        cold_trace=[
            "docs/deploy.md",
            "README.md",
            "src/contoso_payments/config.py",
        ],
        warm_query="deploy release process slot swap manual gotcha",
        expect="CONTOSO_APP_CONFIG_SENTINEL",
    ),
    Scenario(
        id="simulator-429",
        question="Integration tests get 429s from the bank simulator when run with pytest -n auto. What's the fix?",
        cold_trace=[
            "src/contoso_payments/bank_client.py",
            "docker-compose.yml",
            "docs/troubleshooting.md",
            "CONTRIBUTING.md",
        ],
        warm_query="simulator 429 rate limit parallel pytest workers",
        expect="SIMULATOR_KEY_PREFIX",
    ),
    Scenario(
        id="ci-rules",
        question="What lint, typing, and CI requirements must my PR meet before merge?",
        cold_trace=[
            "pyproject.toml",
            ".github/workflows/ci.yml",
            "CONTRIBUTING.md",
        ],
        warm_query="lint ruff mypy CI required check rules PR",
        expect="required check",
    ),
]
