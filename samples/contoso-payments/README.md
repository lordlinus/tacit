# Contoso Payments

Internal payments orchestration service: accepts charge requests from product
teams, talks to the acquiring bank, and fans out webhook events to consumers.

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2.x, Postgres
- Deployed to Azure App Service (staging + production slots) via `azd`
- Bank connectivity through the Contoso Bank Simulator in non-prod

## Layout

```
src/contoso_payments/
    app.py            FastAPI wiring + middleware
    charges.py        charge creation orchestration
    idempotency.py    idempotency-key storage + replay
    webhooks.py       inbound webhook verification + dispatch
    bank_client.py    HTTP client for the bank / simulator
    config.py         settings (CONTOSO_* env)
    models.py         SQLAlchemy models
docs/                 ADRs, deploy guide, incident postmortems
```

## Quick start

```bash
make bootstrap   # NOT optional - see CONTRIBUTING.md
make test
docker compose up -d postgres simulator
make run
```

See `CONTRIBUTING.md` for environment details and `docs/deploy.md` for releases.
