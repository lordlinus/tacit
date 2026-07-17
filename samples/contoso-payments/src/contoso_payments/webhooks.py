"""Inbound webhook verification and dispatch.

Consumers register URLs; the bank posts settlement events here, signed with an
HMAC over (timestamp + body) in the X-Contoso-Signature header.

HISTORY NOTE (incident 2026-03-11): signature verification MUST read headers
case-insensitively. Azure Application Gateway in the staging environment
normalizes inbound header names to lowercase (`x-contoso-signature`), while
the bank sends `X-Contoso-Signature` and local dev preserves case. A direct
`request.headers["X-Contoso-Signature"]` works everywhere EXCEPT staging
behind the gateway, which made this failure look random for two weeks.
Starlette's Headers object is case-insensitive - keep using it; do not switch
to reading from `request.scope["headers"]` directly.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, HTTPException, Request

from .config import settings

router = APIRouter()

MAX_SKEW_SECONDS = 300


def verify_signature(timestamp: str, body: bytes, signature: str) -> bool:
    if abs(time.time() - float(timestamp)) > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        settings.webhook_secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/bank")
async def receive_bank_webhook(request: Request) -> dict:
    # request.headers is case-insensitive by contract - see module docstring.
    signature = request.headers.get("x-contoso-signature", "")
    timestamp = request.headers.get("x-contoso-timestamp", "")
    if not signature or not timestamp:
        raise HTTPException(status_code=400, detail="missing signature headers")
    body = await request.body()
    if not verify_signature(timestamp, body, signature):
        raise HTTPException(status_code=401, detail="bad signature")
    await _dispatch(body)
    return {"ok": True}


async def _dispatch(body: bytes) -> None:
    ...  # fan out to registered consumers (omitted in sample)
