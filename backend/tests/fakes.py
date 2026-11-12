"""Test doubles shared by unit and integration tests.

Nothing here touches the network: `FakeLLMClient` derives deterministic
vectors from the text itself so tests can assert exact values.
"""

import hashlib


class FakeLLMClient:
    """Deterministic `LLMClient` for tests: sha256-derived vectors."""

    def __init__(self, dimensions: int = 4096) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        out: list[float] = []
        salt = 0
        while len(out) < self.dimensions:
            digest = hashlib.sha256(f"{salt}:{text}".encode()).digest()
            out.extend(byte / 255.0 for byte in digest)
            salt += 1
        return out[: self.dimensions]
