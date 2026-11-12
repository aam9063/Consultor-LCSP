"""Test doubles shared by unit and integration tests.

Nothing here touches the network: `FakeLLMClient` derives deterministic
vectors from the text itself so tests can assert exact values.
"""

import hashlib
from typing import Any


class FakeLLMClient:
    """Deterministic `LLMClient` for tests: sha256-derived vectors.

    `rerank` scores are also deterministic, derived from the document text
    itself, so tests can assert exact orders. Specific document texts can be
    pinned through `rerank_scores`. Generation responses come from an
    ordered script (`generation_responses`); every call is counted in
    `generation_calls` and recorded in `generation_requests` so tests can
    assert retry counts and prompt contents.
    """

    def __init__(
        self,
        dimensions: int = 4096,
        *,
        rerank_scores: dict[str, float] | None = None,
        generation_responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []
        self.rerank_calls: list[tuple[str, list[str]]] = []
        self._rerank_scores = dict(rerank_scores or {})
        self.generation_calls = 0
        self.generation_requests: list[dict[str, Any]] = []
        self._generation_responses = list(generation_responses or [])

    async def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the next scripted response, in order; record the call."""
        self.generation_calls += 1
        self.generation_requests.append({"system": system, "user": user, "schema": schema})
        if not self._generation_responses:
            raise AssertionError(
                "FakeLLMClient.generate_json called with no scripted generation response"
            )
        return self._generation_responses.pop(0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        self.rerank_calls.append((query, list(documents)))
        scores: list[float] = []
        for document in documents:
            if document in self._rerank_scores:
                scores.append(self._rerank_scores[document])
            else:
                digest = hashlib.sha256(f"rerank:{query}:{document}".encode()).digest()
                # Deterministic score in [0.0, 1.0) derived from the text.
                scores.append(int.from_bytes(digest[:8], "big") / float(2**64))
        return scores

    def _vector(self, text: str) -> list[float]:
        out: list[float] = []
        salt = 0
        while len(out) < self.dimensions:
            digest = hashlib.sha256(f"{salt}:{text}".encode()).digest()
            out.extend(byte / 255.0 for byte in digest)
            salt += 1
        return out[: self.dimensions]
