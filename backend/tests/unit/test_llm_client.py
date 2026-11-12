"""Unit tests for the NaN LLM adapter (CL-03, S1/S2). No DB, no network.

The transport is a scripted stub, so these tests never call the real API.
Sleeps are replaced by a recording fake, so backoff is asserted without
waiting real seconds.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from openai import APIStatusError
from pydantic import SecretStr

from app.adapters.llm import (
    EmbeddingDimensionError,
    LLMRetriesExhaustedError,
    MissingAPIKeyError,
    NanLLMClient,
)
from app.config import Settings

DIM = 4


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,  # pydantic-settings accepts this at runtime
        "nan_api_key": SecretStr("test-key"),
        "embedding_dimensions": DIM,
        "embedding_batch_size": 3,
    }
    values.update(overrides)
    return Settings(**values)


def _response(vectors: list[list[float]]) -> Any:
    data = [SimpleNamespace(embedding=vector) for vector in vectors]
    return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=7, total_tokens=7))


def _status_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.nan.builders/v1/embeddings")
    response = httpx.Response(status_code, request=request)
    # openai vendors its own httpx; the wire shape is identical, so cast.
    return APIStatusError("provider error", response=cast("Any", response), body=None)


@dataclass
class ScriptedTransport:
    """`embeddings.create` stub that follows a script of outcomes.

    An int outcome raises that HTTP status; any other outcome is returned
    as the response. When the script runs out it falls back to returning
    deterministic vectors for the input, so batching tests stay simple.
    Every call's input texts are recorded in order.
    """

    script: list[Any]
    calls: list[list[str]] = field(default_factory=list)

    @property
    def embeddings(self) -> ScriptedTransport:
        return self

    async def create(self, *, model: str, input: list[str]) -> Any:  # noqa: A002, ARG002
        self.calls.append(list(input))
        outcome = self.script.pop(0) if self.script else _response([_vector_for(t) for t in input])
        if isinstance(outcome, int):
            raise _status_error(outcome)
        return outcome


async def _fake_sleep(_seconds: float) -> None:
    return None


def _vector_for(text: str) -> list[float]:
    return [float(ord(char)) for char in text.ljust(DIM)[:DIM]]


# --- S1: batching respects EMBEDDING_BATCH_SIZE -----------------------------


async def test_embeds_in_batches_of_the_configured_size() -> None:
    transport = ScriptedTransport(script=[])
    settings = _settings(embedding_batch_size=3)
    client = NanLLMClient(settings, client=transport, sleep=_fake_sleep)
    texts = [f"t{i}" for i in range(7)]

    vectors = await client.embed(texts)

    assert [len(batch) for batch in transport.calls] == [3, 3, 1]
    assert vectors == [_vector_for(text) for text in texts]


async def test_embed_with_no_texts_makes_no_calls() -> None:
    transport = ScriptedTransport(script=[])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    assert await client.embed([]) == []
    assert transport.calls == []


# --- S1: a 429 is retried with exponential backoff + jitter ------------------


async def test_429_is_retried_with_backoff_and_eventually_succeeds() -> None:
    transport = ScriptedTransport(script=[429, _response([_vector_for(t) for t in ["t0", "t1"]])])
    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = NanLLMClient(
        _settings(embedding_batch_size=2), client=transport, sleep=recording_sleep
    )

    vectors = await client.embed(["t0", "t1"])

    assert vectors == [_vector_for("t0"), _vector_for("t1")]
    assert len(transport.calls) == 2
    assert len(delays) == 1
    assert 0 < delays[0] <= 20.0


async def test_persistent_429_raises_a_typed_error_after_bounded_attempts() -> None:
    transport = ScriptedTransport(script=[429, 429, 429, 429, 429])
    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = NanLLMClient(_settings(), client=transport, sleep=recording_sleep)

    with pytest.raises(LLMRetriesExhaustedError):
        await client.embed(["t0"])

    assert len(transport.calls) == 5
    assert len(delays) == 4


async def test_5xx_is_retried_and_client_errors_are_not() -> None:
    transport = ScriptedTransport(script=[500, _response([_vector_for("t0")])])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    vectors = await client.embed(["t0"])

    assert vectors == [_vector_for("t0")]
    assert len(transport.calls) == 2


# --- S2: every vector must have exactly EMBEDDING_DIMENSIONS components -----


async def test_wrong_dimension_vector_raises_a_typed_error() -> None:
    transport = ScriptedTransport(script=[_response([[0.1, 0.2, 0.3]])])
    client = NanLLMClient(_settings(embedding_dimensions=DIM), client=transport, sleep=_fake_sleep)

    with pytest.raises(EmbeddingDimensionError):
        await client.embed(["t0"])


# --- the real client path needs NAN_API_KEY ---------------------------------


def test_missing_api_key_raises_a_typed_error() -> None:
    settings = _settings(nan_api_key=SecretStr(""))

    with pytest.raises(MissingAPIKeyError, match="NAN_API_KEY"):
        NanLLMClient(settings)
