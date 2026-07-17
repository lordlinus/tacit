---
path: /gotchas/simulator-429.md
category: gotcha
tags: testing, 429, simulator, xdist
---
# Bank simulator 429s in parallel tests: use per-worker API keys

The simulator rate limits **30 req/min per API key** and docker-compose gives
everything the same `local-dev-key`, so `pytest -n auto` hits 429 instantly.

Fix: `export SIMULATOR_KEY_PREFIX=worker` — `tests/conftest.py` then derives
a distinct key per xdist worker (`worker-gw0`, `worker-gw1`, ...), each with
its own rate bucket.

Do **not** add retry loops to `bank_client.py` to paper over this: 429s in
production mean real bank throttling and must surface, and retries were
explicitly rejected in review before.
