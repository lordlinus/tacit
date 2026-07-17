"""The MCP tool surface, defined once.

Both runtimes — the Azure Functions app and the local stdio server — dispatch
through ``call_tool`` so the tool contract can't drift between them, and unit
tests cover the real handlers without either transport.
"""

from __future__ import annotations

from typing import Any

from .errors import DuplicatePathError, MemoryNotFoundError, ShaConflictError, StoreFullError
from .models import Memory
from .service import MemoryService

# name -> (description, [(property, type, description), ...])
TOOL_DEFINITIONS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "memory_search": (
        "Search the team's shared project memory. ALWAYS try this before exploring "
        "the repo — gotchas, conventions, and architecture learned by previous "
        "engineers' agents are stored here.",
        [
            ("query", "string", "What you want to know, in plain words."),
            ("top", "number", "Max results (default 3)."),
            ("category", "string", "Optional filter: onboarding|gotcha|architecture|convention|general."),
        ],
    ),
    "memory_brief": (
        "One-call onboarding pack: every 'onboarding'-category team memory. "
        "Call this once when starting work on an unfamiliar project.",
        [],
    ),
    "memory_read": (
        "Read one memory in full by path. Returns content_sha256 (needed to update/delete).",
        [("path", "string", "Memory path, e.g. /gotchas/stale-wheel.md")],
    ),
    "memory_list": (
        "List active memories (paths, titles, categories).",
        [("prefix", "string", "Optional path prefix filter, e.g. /gotchas/")],
    ),
    "memory_create": (
        "Store a NEW learning for the team (fails if the path exists). Write one "
        "focused fact per memory, with a '# Title' heading.",
        [
            ("path", "string", "Where to file it, e.g. /gotchas/retry-on-429.md"),
            ("content", "string", "Markdown body starting with '# Title'."),
            ("category", "string", "onboarding|gotcha|architecture|convention|general."),
            ("tags", "string", "Comma-separated tags."),
        ],
    ),
    "memory_update": (
        "Append a new version to an existing memory. Requires expected_sha256 from "
        "the latest memory_read; on sha_conflict, re-read and retry.",
        [
            ("path", "string", "Memory path."),
            ("expected_sha256", "string", "content_sha256 from your latest read."),
            ("content", "string", "Replacement markdown body."),
        ],
    ),
    "memory_delete": (
        "Tombstone a memory (history is preserved). Requires expected_sha256.",
        [
            ("path", "string", "Memory path."),
            ("expected_sha256", "string", "content_sha256 from your latest read."),
        ],
    ),
    "memory_versions": (
        "Audit trail of a memory: who wrote each version and when.",
        [("path", "string", "Memory path.")],
    ),
}


def _memory_result(memory: Memory) -> dict[str, Any]:
    return {
        "path": memory.path,
        "title": memory.title,
        "category": memory.category,
        "tags": list(memory.tags),
        "version": memory.version,
        "status": str(memory.status),
        "content_sha256": memory.content_sha256,
        "created_by": memory.created_by,
        "updated_by": memory.updated_by,
        "updated": memory.updated.isoformat(),
        "content": memory.content,
    }


def _split_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [t.strip() for t in str(raw or "").split(",") if t.strip()]


def call_tool(service: MemoryService, name: str, arguments: dict[str, Any]) -> Any:
    """Dispatch one tool call; errors come back as structured results."""
    args = arguments or {}
    try:
        if name == "memory_search":
            hits = service.search(
                str(args.get("query", "")),
                top=int(args.get("top") or 3),
                category=str(args.get("category") or ""),
            )
            return [h.model_dump() for h in hits]
        if name == "memory_brief":
            return {"brief": service.brief()}
        if name == "memory_read":
            return _memory_result(service.read(str(args["path"])))
        if name == "memory_list":
            return [
                {"path": m.path, "title": m.title, "category": m.category, "tags": m.tags}
                for m in service.list(str(args.get("prefix") or "/"))
            ]
        if name == "memory_create":
            return _memory_result(
                service.create(
                    str(args["path"]),
                    str(args["content"]),
                    category=str(args.get("category") or "general"),
                    tags=_split_tags(args.get("tags")),
                )
            )
        if name == "memory_update":
            return _memory_result(
                service.update(
                    str(args["path"]),
                    str(args["expected_sha256"]),
                    content=str(args["content"]) if args.get("content") is not None else None,
                )
            )
        if name == "memory_delete":
            return _memory_result(
                service.delete(str(args["path"]), str(args["expected_sha256"]))
            )
        if name == "memory_versions":
            return [
                {
                    "version": v.version,
                    "operation": v.operation,
                    "actor": v.actor,
                    "timestamp": v.timestamp.isoformat(),
                    "content_sha256": v.content_sha256,
                }
                for v in service.versions(str(args["path"]))
            ]
    except ShaConflictError as exc:
        return exc.as_result()
    except MemoryNotFoundError as exc:
        return {"error": "not_found", "path": exc.path, "tombstoned": exc.tombstoned}
    except DuplicatePathError as exc:
        return {"error": "duplicate_path", "path": exc.path, "hint": "Use memory_update."}
    except StoreFullError as exc:
        return {"error": "store_full", "limit": exc.limit}
    raise ValueError(f"unknown tool {name!r}")
