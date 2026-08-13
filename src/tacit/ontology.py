"""The organization's shared vocabulary.

Cross-team memory has a second failure mode after reach: two teams describe the
same thing differently. Payments writes "the gateway", platform writes
"pmt-gw", the new hire's agent asks about "the Stripe proxy" — three names, one
system, and no lexical or semantic ranker reliably bridges them, because the
connection is a fact about *this organization*, not about English.

An ``Ontology`` is a small controlled vocabulary of those facts: canonical
entities and the aliases each team actually types. It is applied at **write
time** — every chunk is annotated with the canonical ids it mentions and with
every alias of those entities as searchable text. A memory written in one
team's vocabulary therefore carries all of them, and a query in any team's
words matches it through ordinary ranking. Normalizing on write rather than
expanding on read keeps query latency flat, keeps the semantic ranker seeing
the user's real question, and means the vocabulary can grow without any query
path changing.

Matching is deterministic (longest alias first, on word boundaries) so the
hermetic tests cover it exactly and nothing here needs a model. Curating the
vocabulary is a human act; ``tacit ontology`` is its interface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Entity kinds the CLI suggests. Free-form in storage: an organization that
#: needs "vendor" or "dataset" should not have to patch the package to say so.
KINDS = ("system", "service", "technology", "team", "concept")

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WORD_EDGE = r"(?<![A-Za-z0-9]){}(?![A-Za-z0-9])"


def slugify_entity(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "entity"


@dataclass(frozen=True)
class Entity:
    """One thing the organization has more than one name for."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    kind: str = "concept"
    description: str = ""

    def __post_init__(self) -> None:
        if not _SLUG.match(self.id):
            raise ValueError(f"entity id must be a kebab-case slug; got {self.id!r}")

    @property
    def surface_forms(self) -> tuple[str, ...]:
        """Every string that should resolve to this entity, longest first.

        The canonical name is included: a memory that only ever says "pmt-gw"
        must still be findable by the name the rest of the org uses.
        """
        forms = {self.name, *self.aliases}
        return tuple(sorted((f for f in forms if f.strip()), key=lambda f: (-len(f), f)))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": list(self.aliases),
            "kind": self.kind,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Entity":
        name = str(data.get("name") or data.get("id") or "").strip()
        return cls(
            id=str(data.get("id") or slugify_entity(name)),
            name=name,
            aliases=tuple(
                str(a).strip() for a in (data.get("aliases") or []) if str(a).strip()
            ),
            kind=str(data.get("kind") or "concept"),
            description=str(data.get("description") or ""),
        )


@dataclass
class Ontology:
    """The organization's entities, with a compiled surface-form matcher."""

    entities: list[Entity] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._compile()

    # -- construction ----------------------------------------------------------

    def _compile(self) -> None:
        self._by_id = {e.id: e for e in self.entities}
        # Longest surface form first so "payments gateway" wins over "gateway"
        # and an entity is never shadowed by a shorter, more generic alias.
        pairs: list[tuple[str, str]] = [
            (form, entity.id) for entity in self.entities for form in entity.surface_forms
        ]
        pairs.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        self._forms = pairs
        self._pattern = (
            re.compile(
                "|".join(_WORD_EDGE.format(re.escape(form)) for form, _ in pairs),
                re.IGNORECASE,
            )
            if pairs
            else None
        )
        # Resolution map is lowercased; aliases are matched case-insensitively
        # because nobody types a system's name consistently.
        self._form_to_id = {form.lower(): eid for form, eid in pairs}

    def get(self, entity_id: str) -> Entity | None:
        return self._by_id.get(entity_id)

    def __len__(self) -> int:
        return len(self.entities)

    def __bool__(self) -> bool:
        return bool(self.entities)

    # -- matching --------------------------------------------------------------

    def annotate(self, text: str) -> list[str]:
        """Canonical ids of every entity mentioned in ``text``, in id order.

        Overlaps resolve to the longest surface form, so text containing
        "payments gateway" yields the gateway, not a generic "payments" entity
        that happens to share a prefix.
        """
        if not self._pattern or not text:
            return []
        found: set[str] = set()
        for match in self._pattern.finditer(text):
            entity_id = self._form_to_id.get(match.group(0).lower())
            if entity_id:
                found.add(entity_id)
        return sorted(found)

    def vocabulary_for(self, entity_ids: list[str]) -> str:
        """Every surface form of the given entities, as one searchable string.

        This is what makes a memory written in one team's words findable in
        another's: the text is indexed alongside the chunk, so the alias the
        asker happens to use is present even though the author never wrote it.
        """
        forms: list[str] = []
        for entity_id in entity_ids:
            entity = self._by_id.get(entity_id)
            if entity:
                forms.extend(entity.surface_forms)
        return " ".join(dict.fromkeys(forms))

    # -- persistence -----------------------------------------------------------

    def to_dict(self) -> dict:
        return {"entities": [e.to_dict() for e in self.entities]}

    @classmethod
    def from_dict(cls, data: dict) -> "Ontology":
        raw = data.get("entities", data if isinstance(data, list) else [])
        return cls(entities=[Entity.from_dict(e) for e in raw])

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        file = Path(path)
        if not file.is_file():
            return cls()
        return cls.from_dict(json.loads(file.read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> Path:
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return file


EMPTY = Ontology()
