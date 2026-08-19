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
body text and freshens recently updated memories.

When an embedding deployment is configured, ``tacit-chunks`` also carries a
``content_vector`` field, which turns every query into a hybrid one: BM25 and
vector candidates fused by RRF, then semantically reranked. That is the
combination Azure documents as the strongest for relevance, and it is what
makes "the thing that rewrites webhook headers" find a memory that only ever
says "lowercases the signature header".
"""

from __future__ import annotations

from .azure_common import SEARCH_API_VERSION, request_json, search_headers
from .config import Settings

SEMANTIC_CONFIG = "tacit-semantic"
SCORING_PROFILE = "tacit-relevance"
VECTOR_PROFILE = "tacit-vector"
VECTOR_ALGORITHM = "tacit-hnsw"
VECTORIZER = "tacit-vectorizer"

#: Field holding the section embedding. Present only when the deployment
#: configures an embedding model; adding a field to a live index is one of the
#: schema changes Azure applies without a rebuild, so switching vectors on
#: later is a `provision` + `reindex`, not a migration.
VECTOR_FIELD = "content_vector"

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


def _vector_search(vectorizer: dict | None = None) -> dict:
    """HNSW with cosine similarity — the default pairing for normalized
    text embeddings, and the one text-embedding-3-* is trained for.

    A vectorizer, when present, is what lets a query arrive as plain text: the
    service embeds it. It is declared here but only ever used at query time —
    indexing vectors still happens on the write path, because memories are
    pushed rather than crawled by an indexer.
    """
    profile: dict = {"name": VECTOR_PROFILE, "algorithm": VECTOR_ALGORITHM}
    config = {
        "algorithms": [
            {
                "name": VECTOR_ALGORITHM,
                "kind": "hnsw",
                "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500,
                                    "metric": "cosine"},
            }
        ],
        "profiles": [profile],
    }
    if vectorizer:
        profile["vectorizer"] = VECTORIZER
        config["vectorizers"] = [vectorizer]
    return config


def azure_openai_vectorizer(endpoint: str, deployment: str, model: str) -> dict:
    """Query-time embedding by the search service, over its own identity.

    ``apiKey`` and ``authIdentity`` are both omitted deliberately: that is what
    selects the search service's system-assigned identity, which needs
    Cognitive Services OpenAI User on the target resource and nothing more.
    """
    return {
        "name": VECTORIZER,
        "kind": "azureOpenAI",
        "azureOpenAIParameters": {
            "resourceUri": endpoint.rstrip("/"),
            "deploymentId": deployment,
            "modelName": model,
        },
    }


def _chunks_schema(
    name: str, vector_dimensions: int = 0, vectorizer: dict | None = None
) -> dict:
    """Derived: one doc per section of every active memory. Rebuilt from the
    memories index on every write, so it is disposable."""
    schema = {
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
    if vector_dimensions:
        schema["fields"].append(
            {
                "name": VECTOR_FIELD,
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,  # never returned: it would dwarf the hit
                "stored": False,
                "dimensions": vector_dimensions,
                "vectorSearchProfile": VECTOR_PROFILE,
            }
        )
        schema["vectorSearch"] = _vector_search(vectorizer)
    return schema


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


def provision(settings: Settings, credential) -> tuple[str, str, str, str]:
    """Create (or update) the shared index set; returns every name it touched.

    Idempotent and project-independent: every project writes into the same
    indexes, so this runs once per Azure AI Search service rather than
    once per team.
    """
    memories, versions, chunks = index_names()
    endpoint = settings.search_endpoint.rstrip("/")
    headers = search_headers(credential)
    dimensions = settings.embedding_dimensions if settings.vectors_enabled else 0
    vectorizer = (
        azure_openai_vectorizer(
            settings.embedding_endpoint,
            settings.embedding_deployment,
            settings.embedding_model,
        )
        if settings.vectors_enabled
        else None
    )
    for schema in (
        _memories_schema(memories),
        _versions_schema(versions),
        _chunks_schema(chunks, dimensions, vectorizer),
        _ontology_schema(ONTOLOGY_INDEX),
    ):
        request_json(
            method="PUT",
            url=f"{endpoint}/indexes('{schema['name']}')?api-version={SEARCH_API_VERSION}",
            headers=headers,
            body=schema,
        )
    return memories, versions, chunks, ONTOLOGY_INDEX
