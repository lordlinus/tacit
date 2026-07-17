# Troubleshooting

## `ModuleNotFoundError: contoso_payments._proto.settlement_pb2`

You skipped `make bootstrap`. The protobuf stubs are generated, not committed.
Run `make bootstrap` (or just `make proto`).

## 429 Too Many Requests from the bank simulator

The simulator enforces **30 requests/minute per API key** and the default
compose file gives everything the same key (`local-dev-key`). Parallel test
runs (`pytest -n auto`) burn through it instantly.

Fix: `export SIMULATOR_KEY_PREFIX=worker` — the conftest fixture then derives
`worker-gw0`, `worker-gw1`, ... per xdist worker, each with its own bucket.
Do **not** wrap the client in retries; 429s in production mean real
throttling and must surface.

## Webhook signature failures

- Behind any proxy/gateway: check header-name casing first — see
  `docs/incidents/2026-03-11-webhook-signatures.md`.
- Clock skew: verification rejects timestamps older than 5 minutes; WSL2 VMs
  that slept drift badly (`sudo hwclock -s`).

## Config changes ignored after deploy

You (or your pipeline) forgot to bump `CONTOSO_APP_CONFIG_SENTINEL` after the
slot swap. See `docs/deploy.md`.
