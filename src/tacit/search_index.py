"""Index schemas + provisioning for the Azure AI Search backend.

One store = three indexes. ``tm-<project>`` holds the latest state of each
memory (one doc per path) and is the system of record for reads and sha
preconditions; ``tm-<project>-versions`` is the append-only audit trail;
``tm-<project>-chunks`` is a derived, section-level projection of the active
memories and is the index queries actually run against, so a hit points at the
part of a memory that matched. Creation is idempotent (PUT = create-or-update).

The searchable indexes carry a semantic configuration (L2 reranking plus
extractive captions) and a scoring profile that weights title and tags over
body text and freshens recently updated memories — the same ranking bias the
local backend applies, so both backends order results alike.
"""

from __future__ import annotations

import re

from .azure_common import SEARCH_API_VERSION, request_json, search_headers
from .config import Settings

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SEMANTIC_CONFIG = "tm-semantic"
SCORING_PROFILE = "tm-relevance"


def index_names(project: str) -> tuple[str, str, str]:
    if not _SLUG.match(project):
        raise ValueError(f"project must be a kebab-case slug; got {project!r}")
    return f"tm-{project}", f"tm-{project}-versions", f"tm-{project}-chunks"


def _semantic(content_fields: list[str]) -> dict:
    return {
        "configurations": [
            {
                "name": SEMANTIC_CONFIG,
                "prioritizedFields": {
                    "titleField": {"fieldName": "title"},
                    "prioritizedContentFields": [{"fieldName": f} for f in content_fields],
                    "prioritizedKeywordsFields": [{"fieldName": "tags"}],
                },
            }
        ]
    }


def _scoring_profiles() -> list[dict]:
    return [
        {
            "name": SCORING_PROFILE,
            "text": {"weights": {"title": 3.0, "tags": 2.0, "content": 1.0}},
            "functions": [
                {
                    "type": "freshness",
                    "fieldName": "updated",
                    "boost": 1.5,
                    "interpolation": "quadratic",
                    "freshness": {"boostingDuration": "P180D"},
                }
            ],
        }
    ]


def _memories_schema(name: str) -> dict:
    return {
        "name": name,
        "fields": [
            {"name": "key", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "path", "type": "Edm.String", "filterable": True, "sortable": True},
            {"name": "title", "type": "Edm.String", "searchable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "category", "type": "Edm.String", "filterable": True, "facetable": True},
            {
                "name": "tags",
                "type": "Collection(Edm.String)",
                "searchable": True,
                "filterable": True,
            },
            {"name": "version", "type": "Edm.Int32", "filterable": True},
            {"name": "content_sha256", "type": "Edm.String"},
            {"name": "status", "type": "Edm.String", "filterable": True},
            {"name": "created_by", "type": "Edm.String", "filterable": True},
            {"name": "updated_by", "type": "Edm.String", "filterable": True},
            {"name": "created", "type": "Edm.DateTimeOffset", "filterable": True},
            {"name": "updated", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True},
        ],
        "scoringProfiles": _scoring_profiles(),
        "semantic": _semantic(["content"]),
    }


def _versions_schema(name: str) -> dict:
    return {
        "name": name,
        "fields": [
            {"name": "key", "type": "Edm.String", "key": True},
            {"name": "path", "type": "Edm.String", "filterable": True},
            {"name": "version", "type": "Edm.Int32", "filterable": True, "sortable": True},
            {"name": "operation", "type": "Edm.String", "filterable": True},
            {"name": "content", "type": "Edm.String"},
            {"name": "content_sha256", "type": "Edm.String"},
            {"name": "actor", "type": "Edm.String", "filterable": True},
            {
                "name": "timestamp",
                "type": "Edm.DateTimeOffset",
                "filterable": True,
                "sortable": True,
            },
        ],
    }


def _chunks_schema(name: str) -> dict:
    """Derived: one doc per section of every active memory. Rebuilt from the
    memories index on every write, so it is disposable."""
    return {
        "name": name,
        "fields": [
            {"name": "key", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "path", "type": "Edm.String", "filterable": True, "sortable": True},
            {"name": "section", "type": "Edm.String", "filterable": True},
            {"name": "heading", "type": "Edm.String", "searchable": True},
            {"name": "title", "type": "Edm.String", "searchable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "category", "type": "Edm.String", "filterable": True, "facetable": True},
            {
                "name": "tags",
                "type": "Collection(Edm.String)",
                "searchable": True,
                "filterable": True,
            },
            {"name": "updated", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True},
        ],
        "scoringProfiles": _scoring_profiles(),
        "semantic": _semantic(["content", "heading"]),
    }


def provision(settings: Settings, credential) -> tuple[str, str, str]:
    """Create (or update) all three indexes; returns their names."""
    memories, versions, chunks = index_names(settings.project)
    endpoint = settings.search_endpoint.rstrip("/")
    headers = search_headers(credential)
    for schema in (
        _memories_schema(memories),
        _versions_schema(versions),
        _chunks_schema(chunks),
    ):
        request_json(
            method="PUT",
            url=f"{endpoint}/indexes('{schema['name']}')?api-version={SEARCH_API_VERSION}",
            headers=headers,
            body=schema,
        )
    return memories, versions, chunks
