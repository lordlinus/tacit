"""Idempotency-key storage (ADR-007).

A key row is reserved before any side effect and resolved with the final
response afterwards. Keys expire after 24h (bank requirement); the reconciler
re-drives keys that were reserved but never resolved (crash between reserve
and bank call).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IdempotencyKey

KEY_TTL = timedelta(hours=24)


async def replay_or_reserve(session: AsyncSession, key: str) -> dict | None:
    """Return the stored response for a seen key, or reserve it and return None."""
    statement = (
        insert(IdempotencyKey)
        .values(key=key, reserved_at=datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(IdempotencyKey.key)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()
    if inserted is not None:
        return None  # fresh reservation
    row = (
        await session.execute(select(IdempotencyKey).where(IdempotencyKey.key == key))
    ).scalar_one()
    return row.response  # may be None if still in flight; caller surfaces 409


async def store_response(session: AsyncSession, key: str, response: dict) -> None:
    row = (
        await session.execute(select(IdempotencyKey).where(IdempotencyKey.key == key))
    ).scalar_one()
    row.response = response
    row.resolved_at = datetime.now(UTC)
    await session.commit()
