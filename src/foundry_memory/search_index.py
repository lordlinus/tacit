"""Index schemas + provisioning for the Azure AI Search backend.

One store = two indexes: ``tm-<project>`` holds the latest state of each
memory (one doc per path); ``tm-<project>-versions`` is the append-only audit
trail. Creation is idempotent (PUT = create-or-update).
"""

from __future__ import annotations

import re

from .azure_common import SEARCH_API_VERSION, request_json, search_headers
from .config import Settings

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def index_names(project: str) -> tuple[str, str]:
    if not _SLUG.match(project):
        raise ValueError(f"project must be a kebab-case slug; got {project!r}")
    return f"tm-{project}", f"tm-{project}-versions"


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
            {"name": "timestamp", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True},
        ],
    }


def provision(settings: Settings, credential) -> tuple[str, str]:
    """Create (or update) both indexes; returns their names."""
    memories, versions = index_names(settings.project)
    endpoint = settings.search_endpoint.rstrip("/")
    headers = search_headers(credential)
    for schema in (_memories_schema(memories), _versions_schema(versions)):
        request_json(
            method="PUT",
            url=f"{endpoint}/indexes('{schema['name']}')?api-version={SEARCH_API_VERSION}",
            headers=headers,
            body=schema,
        )
    return memories, versions
