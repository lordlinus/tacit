"""Azure AI Search backend — same MemoryStore protocol as LocalStore.

Latest state is mergeOrUpload-ed into ``tm-<project>`` (key = path slug);
every mutation also uploads an immutable doc to ``tm-<project>-versions``
(key = path slug + version). Search is service-side BM25.

Note: AI Search indexing is near-real-time, not transactional — a doc becomes
searchable within seconds of upload. ``get`` uses the lookup API (consistent),
so the concurrency contract (sha preconditions) is not affected by search lag.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .azure_common import SEARCH_API_VERSION, build_credential, request_json, search_headers
from .config import Settings
from .models import Memory, MemoryStatus, MemoryVersion, SearchHit, path_key
from .search_index import index_names


class SearchStore:
    def __init__(self, settings: Settings, credential: Any | None = None) -> None:
        self._endpoint = settings.search_endpoint.rstrip("/")
        self._credential = credential or build_credential(settings.auth_mode, settings.tenant_id)
        self._memories_index, self._versions_index = index_names(settings.project)

    # -- REST plumbing ---------------------------------------------------------

    def _url(self, index: str, suffix: str) -> str:
        return f"{self._endpoint}/indexes('{index}'){suffix}?api-version={SEARCH_API_VERSION}"

    def _post(self, index: str, suffix: str, body: dict) -> dict | None:
        return request_json(
            method="POST",
            url=self._url(index, suffix),
            headers=search_headers(self._credential),
            body=body,
        )

    # -- MemoryStore protocol ---------------------------------------------------

    def get(self, path: str) -> Memory | None:
        from urllib.error import HTTPError

        url = (
            f"{self._endpoint}/indexes('{self._memories_index}')"
            f"/docs('{quote(path_key(path), safe='')}')?api-version={SEARCH_API_VERSION}"
        )
        try:
            doc = request_json(
                method="GET", url=url, headers=search_headers(self._credential)
            )
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        except HTTPError:  # pragma: no cover - defensive
            return None
        return _memory_from_doc(doc) if doc else None

    def put(self, memory: Memory, version: MemoryVersion) -> None:
        self._post(
            self._memories_index,
            "/docs/search.index",
            {"value": [{"@search.action": "mergeOrUpload", **_memory_doc(memory)}]},
        )
        self._post(
            self._versions_index,
            "/docs/search.index",
            {"value": [{"@search.action": "upload", **_version_doc(version)}]},
        )

    def list(self, prefix: str = "/") -> list[Memory]:
        result = self._post(
            self._memories_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": "status eq 'active'",
                "orderby": "path asc",
                "top": 1000,
            },
        )
        memories = [_memory_from_doc(d) for d in (result or {}).get("value", [])]
        return [m for m in memories if m.path.startswith(prefix)]

    def search(self, query: str, *, top: int = 5, category: str = "") -> list[SearchHit]:
        filters = "status eq 'active'"
        if category:
            filters += f" and category eq '{category}'"
        result = self._post(
            self._memories_index,
            "/docs/search.post.search",
            {
                "search": query,
                "filter": filters,
                "searchFields": "title,tags,content",
                "top": top,
            },
        )
        hits = []
        for doc in (result or {}).get("value", []):
            hits.append(
                SearchHit(
                    path=doc["path"],
                    title=doc.get("title") or doc["path"],
                    category=doc.get("category") or "general",
                    tags=doc.get("tags") or [],
                    score=float(doc.get("@search.score") or 0.0),
                    content=doc.get("content") or "",
                )
            )
        return hits

    def versions(self, path: str) -> list[MemoryVersion]:
        result = self._post(
            self._versions_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": f"path eq '{path}'",
                "orderby": "version asc",
                "top": 1000,
            },
        )
        return [_version_from_doc(d) for d in (result or {}).get("value", [])]

    def count(self) -> int:
        result = self._post(
            self._memories_index,
            "/docs/search.post.search",
            {"search": "*", "filter": "status eq 'active'", "top": 0, "count": True},
        )
        return int((result or {}).get("@odata.count") or 0)


def _memory_doc(memory: Memory) -> dict:
    return {
        "key": memory.key,
        "path": memory.path,
        "title": memory.title,
        "content": memory.content,
        "category": memory.category,
        "tags": list(memory.tags),
        "version": memory.version,
        "content_sha256": memory.content_sha256,
        "status": str(memory.status),
        "created_by": memory.created_by,
        "updated_by": memory.updated_by,
        "created": memory.created.isoformat(),
        "updated": memory.updated.isoformat(),
    }


def _memory_from_doc(doc: dict) -> Memory:
    return Memory(
        path=doc["path"],
        content=doc.get("content") or "",
        category=doc.get("category") or "general",
        tags=doc.get("tags") or [],
        version=int(doc.get("version") or 1),
        content_sha256=doc.get("content_sha256") or "",
        status=MemoryStatus(doc.get("status") or "active"),
        created_by=doc.get("created_by") or "unknown",
        updated_by=doc.get("updated_by") or "unknown",
        created=doc.get("created"),
        updated=doc.get("updated"),
    )


def _version_doc(version: MemoryVersion) -> dict:
    return {
        "key": f"{path_key(version.path)}-v{version.version}",
        "path": version.path,
        "version": version.version,
        "operation": version.operation,
        "content": version.content,
        "content_sha256": version.content_sha256,
        "actor": version.actor,
        "timestamp": version.timestamp.isoformat(),
    }


def _version_from_doc(doc: dict) -> MemoryVersion:
    return MemoryVersion(
        path=doc["path"],
        version=int(doc["version"]),
        operation=doc.get("operation") or "update",
        content=doc.get("content") or "",
        content_sha256=doc.get("content_sha256") or "",
        actor=doc.get("actor") or "unknown",
        timestamp=doc.get("timestamp"),
    )
