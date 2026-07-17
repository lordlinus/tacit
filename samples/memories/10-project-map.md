---
path: /onboarding/project-map.md
category: onboarding
tags: architecture, map
---
# Contoso Payments — project map

Payments orchestration service: FastAPI + SQLAlchemy + Postgres, deployed to
Azure App Service (staging/production slots) via azd. Bank connectivity goes
through the Contoso Bank Simulator in non-prod.

- `src/contoso_payments/charges.py` — charge orchestration (ADR-007 flow)
- `src/contoso_payments/idempotency.py` — idempotency-key reserve/replay
- `src/contoso_payments/webhooks.py` — inbound HMAC-verified bank webhooks
- `src/contoso_payments/bank_client.py` — bank/simulator HTTP client
- `docs/` — ADRs, deploy guide, incident postmortems (read before touching
  webhooks or deploys)
