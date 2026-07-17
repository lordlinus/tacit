"""HTTP client for the acquiring bank (the simulator in non-prod).

The simulator rate limits 30 req/min PER API KEY. Integration tests running
under pytest-xdist must use per-worker keys (SIMULATOR_KEY_PREFIX) - do NOT
add retry loops here to paper over 429s; they mask real production throttling
and blow up test wall-clock time.
"""

from __future__ import annotations

import httpx

from .config import settings


class BankClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.bank_base_url,
            headers={"Authorization": f"Bearer {api_key or settings.bank_api_key}"},
            timeout=10.0,
        )

    async def create_charge(self, *, charge_id: str, amount_minor: int, currency: str) -> dict:
        response = await self._client.post(
            "/v2/charges",
            json={"ref": charge_id, "amount": amount_minor, "currency": currency},
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
