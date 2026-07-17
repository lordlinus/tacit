---
path: /onboarding/dev-setup.md
category: onboarding
tags: setup, bootstrap, proto
---
# Dev setup: Python 3.12 exactly, and `make bootstrap` is NOT optional

- Python **3.12 exactly** (3.13 breaks the pinned asyncpg build; 3.11 lacks
  tomllib features the config loader uses).
- After `uv pip install -e ".[dev]"`, you MUST run `make bootstrap`: it
  generates the protobuf stubs into `src/contoso_payments/_proto/`. Skipping
  it gives `ModuleNotFoundError: contoso_payments._proto.settlement_pb2` in
  about half the test suite — this catches almost every new contributor.
- `make test` = hermetic unit tests. `make test-integration` needs
  `docker compose up -d postgres simulator` first.
