"""Charge creation orchestration.

The core flow implements ADR-007 (idempotent charges via key table + outbox):

    1. Upsert the idempotency key row; if it exists with a response, replay it.
    2. Insert the charge row and an outbox row IN THE SAME TRANSACTION.
    3. Call the bank. On success, store the response against the key.
    4. The outbox relay publishes events; publishing is NOT done inline.

Retries are therefore safe end-to-end: a client retry with the same
Idempotency-Key gets the stored response; a crash between 2 and 3 is repaired
by the reconciler which walks unresolved keys.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .bank_client import BankClient
from .idempotency import replay_or_reserve, store_response
from .models import Charge, OutboxEvent


async def create_charge(
    session: AsyncSession,
    bank: BankClient,
    *,
    idempotency_key: str,
    amount_minor: int,
    currency: str,
    merchant_id: str,
) -> dict:
    replayed = await replay_or_reserve(session, idempotency_key)
    if replayed is not None:
        return replayed

    charge = Charge(
        id=str(uuid.uuid4()),
        amount_minor=amount_minor,
        currency=currency,
        merchant_id=merchant_id,
        status="pending",
    )
    session.add(charge)
    session.add(
        OutboxEvent(
            id=str(uuid.uuid4()),
            kind="charge.created",
            payload={"charge_id": charge.id, "amount_minor": amount_minor},
        )
    )
    await session.commit()

    bank_result = await bank.create_charge(
        charge_id=charge.id, amount_minor=amount_minor, currency=currency
    )
    response = {"charge_id": charge.id, "status": bank_result["status"]}
    await store_response(session, idempotency_key, response)
    return response
