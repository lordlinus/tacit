"""The cross-team overlap graph: which teams already know about which systems.

This is the picture that argues for the whole product. Entities from the shared
vocabulary sit in the middle; the projects that have written about them sit
around the outside; an entity touched by more than one project is the thing
somebody is about to rediscover the hard way.

Two deliberate choices:

* **Entities, not memories, are the hubs.** A memory-level graph is a hairball
  that shows activity; an entity-level one shows *overlap*, which is the only
  thing a viewer can act on ("payments already solved this").
* **Annotation is recomputed here from the current vocabulary**, not read from
  the stored chunk annotations. The graph is then always consistent with the
  vocabulary as it stands, rather than with whenever ``reindex`` last ran. If
  the two disagree, the graph is right and the chunks are stale — which is
  exactly the direction that makes the discrepancy self-correcting.

Everything here is a pure function of (memories, ontology). The caller is
responsible for having already filtered ``memories`` to what the viewer may
see; :meth:`MemoryStore.visible_memories` is what does that, using the same
rules as search.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field

from .models import Memory
from .ontology import Ontology

#: Entities mentioned by no visible memory are dropped: a vocabulary entry
#: nobody has written about is noise on a graph about what teams know.
MIN_MENTIONS = 1


@dataclass
class GraphNode:
    id: str
    kind: str  # "entity" | "project"
    label: str
    memories: int = 0
    projects: int = 0
    shared: bool = False
    team: str = ""
    kind_of_entity: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class GraphEdge:
    source: str
    target: str
    weight: int = 1


def entity_node_id(entity_id: str) -> str:
    return f"entity:{entity_id}"


def project_node_id(project: str) -> str:
    return f"project:{project}"


def build_overlap_graph(
    memories: list[Memory],
    ontology: Ontology,
    *,
    home_project: str = "",
) -> dict:
    """Nodes, edges and per-entity drill-down for the visible memory set.

    ``home_project`` only marks which project the viewer is looking from, so
    the UI can orient itself; it grants nothing and filters nothing.
    """
    # entity id -> project -> [memory refs]
    hits: dict[str, dict[str, list[Memory]]] = defaultdict(lambda: defaultdict(list))
    project_totals: dict[str, int] = defaultdict(int)
    project_team: dict[str, str] = {}
    annotated_total = 0

    for memory in memories:
        project_totals[memory.project] += 1
        # Last writer wins on team; a project has one owning team in practice,
        # and disagreement is a data problem the graph should not paper over
        # by inventing a merge rule.
        if memory.team:
            project_team[memory.project] = memory.team
        found = ontology.annotate(f"{memory.title}\n{memory.content}")
        if found:
            annotated_total += 1
        for entity_id in found:
            hits[entity_id][memory.project].append(memory)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    drilldown: dict[str, list[dict]] = {}

    for entity_id, by_project in sorted(hits.items()):
        mentions = sum(len(v) for v in by_project.values())
        if mentions < MIN_MENTIONS:
            continue
        entity = ontology.get(entity_id)
        node_id = entity_node_id(entity_id)
        nodes.append(
            GraphNode(
                id=node_id,
                kind="entity",
                label=entity.name if entity else entity_id,
                memories=mentions,
                projects=len(by_project),
                shared=len(by_project) > 1,
                kind_of_entity=entity.kind if entity else "concept",
                aliases=list(entity.aliases) if entity else [],
            )
        )
        for project, mems in sorted(by_project.items()):
            edges.append(
                GraphEdge(source=project_node_id(project), target=node_id, weight=len(mems))
            )
        drilldown[node_id] = [
            {
                "path": m.path,
                "title": m.title,
                "project": m.project,
                "team": m.team,
                "category": m.category,
                "visibility": str(m.visibility),
                "updated": m.updated.isoformat(),
            }
            for m in sorted(
                (m for mems in by_project.values() for m in mems),
                key=lambda m: (m.project, m.path),
            )
        ]

    linked_projects = {p for by_project in hits.values() for p in by_project}
    for project in sorted(project_totals):
        # A project with no vocabulary hits would float unconnected and say
        # nothing about overlap, so it is left off rather than drawn adrift.
        if project not in linked_projects:
            continue
        nodes.append(
            GraphNode(
                id=project_node_id(project),
                kind="project",
                label=project,
                memories=project_totals[project],
                team=project_team.get(project, ""),
                shared=project == home_project,
            )
        )

    shared_entities = sum(1 for n in nodes if n.kind == "entity" and n.shared)
    return {
        "nodes": [asdict(n) for n in nodes],
        "edges": [asdict(e) for e in edges],
        "memories": drilldown,
        "stats": {
            "visible_memories": len(memories),
            "annotated_memories": annotated_total,
            "projects": len(linked_projects),
            "entities": sum(1 for n in nodes if n.kind == "entity"),
            "shared_entities": shared_entities,
            "vocabulary_size": len(ontology),
            "home_project": home_project,
        },
    }
