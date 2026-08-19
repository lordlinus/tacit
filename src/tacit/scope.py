"""Search scope: how wide a query reaches.

Cross-team retrieval only works if "who may see what" has exactly one
definition. Every OData filter sent to Azure AI Search is generated here, so
reads, lists, searches and the overlap graph cannot drift apart — a drift
would either hide a team's knowledge or leak a private note, and neither
failure is visible from a passing search.

Two independent things decide what a query returns:

* the **shape**, from the scope — which projects are even candidates;
* the **permission**, from the viewer — which of those the caller may read.

They are kept separate because the caller controls one and not the other. An
MCP client picks the project it is asking about (a routing hint, unverifiable
on a shared endpoint), but permission is always evaluated against the *viewer*:
the project and team this server was configured with. Folding the two together
is what would let a caller read another team's private notes simply by naming
that team's project.

The three scopes answer three different questions:

* ``PROJECT``        — "what does *this repo* know?"
* ``PROJECT+ORG``    — "what does anyone I can see know?" (the default)
* ``ORG``            — "what do *other teams* know that we don't?"
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Memory, SearchScope, Visibility


def odata_quote(value: str) -> str:
    """Escape a string literal for an OData filter (single quotes double up)."""
    return value.replace("'", "''")


@dataclass(frozen=True)
class Viewer:
    """Who is asking, as configured on the server — never caller-supplied.

    An MCP client picks the project it is asking about, but that is a routing
    hint: on a shared endpoint it cannot be verified, and the agent sending it
    is itself steerable by repository content. So the hint decides *what is
    operated on* and this decides *what may be seen*.

    A team that runs one server across several of its own repos does not need
    an escape hatch here — that is what ``visibility="team"`` is for. Reserving
    ``private`` for "this repo only" keeps the rule with no exceptions to it.
    """

    project: str
    team: str = ""

    def sees(self, memory: Memory) -> bool:
        return memory.readable_by(self.project, self.team)


def _permission_odata(viewer: Viewer) -> str:
    """What this viewer may read, regardless of which projects are candidates."""
    clauses = [
        f"project eq '{odata_quote(viewer.project)}'",
        f"visibility eq '{Visibility.ORG}'",
    ]
    if viewer.team:
        clauses.append(
            f"(visibility eq '{Visibility.TEAM}' and team eq '{odata_quote(viewer.team)}')"
        )
    return " or ".join(clauses)


def _shape_odata(scope: SearchScope, target_project: str) -> str:
    """Which projects the scope admits as candidates, before permission."""
    own = f"project eq '{odata_quote(target_project)}'"
    if scope is SearchScope.PROJECT:
        return own
    if scope is SearchScope.ORG:
        return f"not ({own})"
    return ""  # project+org constrains nothing; permission does the work


def scope_filter(
    scope: SearchScope,
    project: str,
    team: str = "",
    viewer: "Viewer | None" = None,
) -> str:
    """OData filter restricting a chunk query to what ``scope`` admits.

    Every clause is parenthesised so callers can safely ``and`` a category or
    entity filter onto the result — an unparenthesised ``or`` chain would
    otherwise swallow it.
    """
    resolved = viewer or Viewer(project=project, team=team)
    shape = _shape_odata(scope, project)
    permission = _permission_odata(resolved)
    if not shape:
        return f"({permission})"
    return f"({shape}) and ({permission})"


def parse_scope(value: "str | SearchScope | None") -> SearchScope:
    """Coerce a tool argument into a scope, defaulting to project+org.

    Agents pass strings, and an unrecognised one must not silently widen or
    narrow what they see — so anything unknown raises rather than guessing.
    """
    if value is None or value == "":
        return SearchScope.PROJECT_PLUS_ORG
    if isinstance(value, SearchScope):
        return value
    normalized = str(value).strip().lower().replace("_", "+").replace(" ", "")
    aliases = {
        "project": SearchScope.PROJECT,
        "local": SearchScope.PROJECT,
        "project+org": SearchScope.PROJECT_PLUS_ORG,
        "default": SearchScope.PROJECT_PLUS_ORG,
        "all": SearchScope.PROJECT_PLUS_ORG,
        "org": SearchScope.ORG,
        "organization": SearchScope.ORG,
        "other": SearchScope.ORG,
    }
    if normalized not in aliases:
        raise ValueError(
            f"unknown scope {value!r}; use one of: "
            f"{', '.join(s.value for s in SearchScope)}"
        )
    return aliases[normalized]
