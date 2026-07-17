"""FastAPI wiring."""

from __future__ import annotations

from fastapi import FastAPI

from . import webhooks

app = FastAPI(title="Contoso Payments", version="3.4.1")
app.include_router(webhooks.router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
