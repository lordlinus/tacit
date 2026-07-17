# Contributing to Contoso Payments

## Environment setup

We target **Python 3.12 exactly** — 3.13 breaks the pinned `asyncpg` build and
3.11 misses `tomllib` features we use in config loading. Use pyenv or uv to
pin it.

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
make bootstrap
```

`make bootstrap` is **not optional**: it generates the protobuf stubs for the
bank settlement feed (`src/contoso_payments/_proto/`) and installs the git
hooks. A plain `pip install -e .` leaves `_proto/` empty and you will get
`ModuleNotFoundError: contoso_payments._proto.settlement_pb2` from roughly half
the test suite. This catches almost every new contributor.

## Tests

```bash
make test            # unit tests, hermetic
make test-integration  # needs docker compose up -d postgres simulator
```

Integration tests hit the **bank simulator** container. The simulator rate
limits per API key (30 req/min). The default compose file gives every pytest
worker the same key, so `-n auto` runs will see 429s. Export
`SIMULATOR_KEY_PREFIX=worker` so the fixture in `tests/conftest.py` derives a
**per-worker key** — this is the fix, do not add retries around the client.

## Lint and style

- `ruff check .` with the repo config — line length 100, `E501` enforced,
  `ANN` ignored in tests.
- Functions are typed; `mypy --strict` runs in CI on `src/` only.
- Import order: stdlib / third-party / first-party, enforced by ruff isort.

## CI

GitHub Actions runs the matrix on push + PR. The aggregate job is literally
named `test` and is a required check in the branch ruleset — if you rename it
in `ci.yml`, merges silently block for everyone. Don't.
