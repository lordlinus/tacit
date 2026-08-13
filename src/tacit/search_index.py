"""Index schemas + provisioning for the Azure AI Search backend.

**One organization = one index set.** ``tacit-memories`` holds the latest state
of every memory in every project (one doc per ``(project, path)``) and is the
system of record for reads and sha preconditions; ``tacit-versions`` is the
append-only audit trail; ``tacit-chunks`` is a derived, section-level projection
of the active memories and is the index queries actually run against, so a hit
points at the part of a memory that matched; ``tacit-ontology`` holds the shared
vocabulary. Creation is idempotent (PUT = create-or-update).

Shared rather than per-project for two reasons: a search that cannot cross a
project boundary is a team memory, not an organizational one; and three indexes
per project would exhaust a Basic service (15 indexes) at five teams and a
Standard one (50) at sixteen. With ``project``/``team``/``visibility`` as
filterable fields, a cross-team query is one request and a scoped one is the
same request with a narrower filter, and onboarding a team costs no indexes.

The searchable indexes carry a semantic configuration (L2 reranking plus
extractive captions) and a scoring profile that weights title and tags over
body text and freshens recently updated memories — the same ranking bias the
local backend applies, so both backends order results alike.
"""

from __future__ import annotations

from .azure_common import SEARCH_API_VERSION, request_json, search_headers
from .config import Settings

SEMANTIC_CONFIG = "tacit-semantic"
SCORING_PROFILE = "tacit-relevance"

#: The shared index set. Named once for the whole organization rather than per
#: project, so one service hosts every team's memory.
MEMORIES_INDEX = "tacit-memories"
VERSIONS_INDEX = "tacit-versions"
CHUNKS_INDEX = "tacit-chunks"
#: The organization's controlled vocabulary. One per service, like the rest —
#: a vocabulary that differed per team would defeat its own purpose.
ONTOLOGY_INDEX = "tacit-ontology"


def index_names() -> tuple[str, str, str]:
    """The shared (memories, versions, chunks) index names."""
    return MEMORIES_INDEX, VERSIONS_INDEX, CHUNKS_INDEX


def _scope_fields() -> list[dict]:
    """The fields that make one index set serve a whole organization.

    ``project`` and ``team`` are facetable so adoption can be reported across
    the org without scanning documents; ``visibility`` is filterable because
    every cross-project query filters on it.
    """
    return [
        {
            "name": "project",
            "type": "Edm.String",
            "searchable": False,
            "filterable": True,
            "facetable": True,
            "sortable": True,
        },
        {
            "name": "team",
            "type": "Edm.String",
            "searchable": False,
            "filterable": True,
            "facetable": True,
        },
        {
            "name": "visibility",
            "type": "Edm.String",
            "searchable": False,
            "filterable": True,
            "facetable": True,
        },
    ]


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
            *_scope_fields(),
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
            {"name": "created_by", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "updated_by", "type": "Edm.String", "filterable": True, "facetable": True},
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
            {"name": "project", "type": "Edm.String", "filterable": True},
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


def _entity_fields() -> list[dict]:
    """Vocabulary annotations written onto every chunk.

    ``entities`` is the canonical id list, for exact filtering ("everything we
    know about the payments gateway"). ``entity_vocabulary`` carries every
    alias of those entities as plain searchable text, which is what lets a
    question phrased in one team's words match a memory written in another's —
    the normalization happens here, on write, not in the query path.
    """
    return [
        {
            "name": "entities",
            "type": "Collection(Edm.String)",
            "searchable": False,
            "filterable": True,
            "facetable": True,
        },
        {
            "name": "entity_vocabulary",
            "type": "Edm.String",
            "searchable": True,
            "filterable": False,
        },
    ]


def _chunks_schema(name: str) -> dict:
    """Derived: one doc per section of every active memory. Rebuilt from the
    memories index on every write, so it is disposable."""
    return {
        "name": name,
        "fields": [
            {"name": "key", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "path", "type": "Edm.String", "filterable": True, "sortable": True},
            *_scope_fields(),
            {"name": "section", "type": "Edm.String", "filterable": True},
            *_entity_fields(),
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


def _ontology_schema(name: str) -> dict:
    """The controlled vocabulary: one document per canonical entity."""
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "name", "type": "Edm.String", "searchable": True, "filterable": True},
            {
                "name": "aliases",
                "type": "Collection(Edm.String)",
                "searchable": True,
                "filterable": True,
            },
            {"name": "kind", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "description", "type": "Edm.String", "searchable": True},
        ],
    }


def provision(settings: Settings, credential) -> tuple[str, str, str]:
    """Create (or update) the shared index set; returns their names.

    Idempotent and project-independent: every project writes into the same
    indexes, so this runs once per Azure AI Search service rather than
    once per team.
    """
    memories, versions, chunks = index_names()
    endpoint = settings.search_endpoint.rstrip("/")
    headers = search_headers(credential)
    for schema in (
        _memories_schema(memories),
        _versions_schema(versions),
        _chunks_schema(chunks),
        _ontology_schema(ONTOLOGY_INDEX),
    ):
        request_json(
            method="PUT",
            url=f"{endpoint}/indexes('{schema['name']}')?api-version={SEARCH_API_VERSION}",
            headers=headers,
            body=schema,
        )
    return memories, versions, chunks
