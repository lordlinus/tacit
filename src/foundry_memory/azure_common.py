"""Keyless auth + tiny REST helper (lifted from foundry-iq-cli's azure_common).

DefaultAzureCredential everywhere: az login locally, managed identity in the
Functions app. No api-keys, ever.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import USER_AGENT

SEARCH_SCOPE = "https://search.azure.com/.default"
SEARCH_API_VERSION = "2024-07-01"


def build_credential(auth_mode: str = "default-credential", tenant_id: str = ""):
    from azure.identity import AzureCliCredential, DefaultAzureCredential

    if auth_mode == "azure-cli":
        return AzureCliCredential(tenant_id=tenant_id or None)
    return DefaultAzureCredential()


def search_headers(credential: Any) -> dict[str, str]:
    token = credential.get_token(SEARCH_SCOPE).token
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict | None = None,
) -> dict | None:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url=url, data=payload, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode("utf-8", errors="replace")
        hint = ""
        if exc.code == 403:
            hint = (
                "\n\nHTTP 403 on the search data plane usually means your identity "
                "lacks a data-plane role (grant 'Search Index Data Contributor') or "
                "the service is api-key-only (enable: az search service update "
                "--auth-options aadOrApiKey)."
            )
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code} {detail}{hint}") from exc
