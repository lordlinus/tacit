"""Azure OpenAI embeddings — the vector half of hybrid search.

Keyless like everything else: the same credential that reaches AI Search mints
Cognitive Services tokens, so no key is ever configured or logged.

This is **optional**. Without ``TACIT_EMBEDDING_ENDPOINT`` the store indexes and
queries exactly as it did before — BM25 candidates, semantically reranked. With
it, the same section text is also stored as a vector and every search becomes a
hybrid one. Optional because an embedding deployment is a second Azure resource
and a per-call cost, and a memory store that cannot be stood up without one is
harder to adopt than one that gets better when you add it.
"""

from __future__ import annotations

from .azure_common import COGNITIVE_SCOPE, bearer_headers, request_json

#: GA embeddings API. Pinned rather than tracking latest: an api-version bump
#: can change response shape, and this runs on a write path.
EMBEDDINGS_API_VERSION = "2024-10-21"

#: text-embedding-3-* accept a `dimensions` argument (Matryoshka truncation),
#: so this is a deliberate choice rather than a property of the model: 1536 is
#: the accuracy/size knee, and halving it would halve vector storage.
DEFAULT_DIMENSIONS = 1536

#: Inputs per request. Sections are small, so this is about bounding the blast
#: radius of one failed call during a re-chunk, not about API limits.
BATCH = 16


class Embedder:
    """One embedding deployment, addressed over REST."""

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        credential,
        *,
        dimensions: int = DEFAULT_DIMENSIONS,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._credential = credential
        self.dimensions = dimensions

    def _url(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            f"/embeddings?api-version={EMBEDDINGS_API_VERSION}"
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed in input order, batched. Empty input costs no call.

        Only the write path calls this: queries are embedded by the search
        service through the index's vectorizer.
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            result = request_json(
                method="POST",
                url=self._url(),
                headers=bearer_headers(self._credential, COGNITIVE_SCOPE),
                body={"input": batch, "dimensions": self.dimensions},
            )
            data = sorted((result or {}).get("data", []), key=lambda d: d.get("index", 0))
            if len(data) != len(batch):
                raise RuntimeError(
                    f"embedding deployment returned {len(data)} vectors for {len(batch)} inputs"
                )
            vectors.extend(d["embedding"] for d in data)
        return vectors
