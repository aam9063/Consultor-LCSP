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
from openai import APIConnectionError, APIStatusError
from pydantic import SecretStr

from app.adapters.llm import (
    ChatResponseError,
    EmbeddingDimensionError,
    LLMRetriesExhaustedError,
    MissingAPIKeyError,
    NanLLMClient,
    RerankResponseError,
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


def _connection_error() -> APIConnectionError:
    request = httpx.Request("POST", "https://api.nan.builders/v1/embeddings")
    return APIConnectionError(request=cast("Any", request))


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
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class RerankTransport:
    """`client.post` stub for the `/rerank` endpoint, scripted like above.

    An int outcome raises that HTTP status; any other outcome is returned
    as the parsed JSON body. Every call's path and body are recorded.
    """

    script: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def post(self, path: str, *, cast_to: Any, body: Any = None) -> Any:  # noqa: ARG002
        self.calls.append({"path": path, "body": body})
        outcome = self.script.pop(0) if self.script else {"results": []}
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


# --- network failures must be retried, not surface as a dead ingestion --------


async def test_a_connection_error_is_retried_and_eventually_succeeds() -> None:
    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    transport = ScriptedTransport(script=[_connection_error(), _connection_error()])
    client = NanLLMClient(_settings(), client=transport, sleep=recording_sleep)

    vectors = await client.embed(["t0"])

    assert len(transport.calls) == 3, "two failures then the successful fallback"
    assert len(delays) == 2, "each failed attempt backs off"
    assert len(vectors) == 1


async def test_a_persistent_connection_error_raises_the_typed_error() -> None:
    transport = ScriptedTransport(script=[_connection_error() for _ in range(10)])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    with pytest.raises(LLMRetriesExhaustedError):
        await client.embed(["t0"])

    assert len(transport.calls) == 5, "bounded attempts, not an infinite loop"


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


# --- CL-04 / S2: rerank on the port -----------------------------------------


def _rerank_response(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"results": results}


async def test_rerank_rebuilds_scores_in_input_order() -> None:
    # The provider answers sorted by score descending; the adapter must not
    # trust that order and must align one score per input document.
    transport = RerankTransport(
        script=[
            _rerank_response(
                [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.4},
                    {"index": 1, "relevance_score": 0.7},
                ]
            )
        ]
    )
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    scores = await client.rerank("plazos", ["d1", "d2", "d3"])

    assert scores == [0.4, 0.7, 0.9]


async def test_rerank_sends_model_query_and_documents_without_the_key() -> None:
    transport = RerankTransport(script=[_rerank_response([{"index": 0, "relevance_score": 0.5}])])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    await client.rerank("plazo", ["documento"])

    assert transport.calls[0]["path"] == "/rerank"
    assert transport.calls[0]["body"] == {
        "model": "rerank",
        "query": "plazo",
        "documents": ["documento"],
    }


async def test_rerank_retries_429_with_backoff_and_succeeds() -> None:
    transport = RerankTransport(
        script=[429, _rerank_response([{"index": 0, "relevance_score": 0.6}])]
    )
    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = NanLLMClient(_settings(), client=transport, sleep=recording_sleep)

    scores = await client.rerank("q", ["d"])

    assert scores == [0.6]
    assert len(transport.calls) == 2
    assert len(delays) == 1
    assert 0 < delays[0] <= 20.0


async def test_rerank_persistent_429_raises_a_typed_error_after_bounded_attempts() -> None:
    transport = RerankTransport(script=[429, 429, 429, 429, 429])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    with pytest.raises(LLMRetriesExhaustedError):
        await client.rerank("q", ["d"])

    assert len(transport.calls) == 5


@pytest.mark.parametrize(
    "results",
    [
        # duplicated index
        [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.6}],
        # out of range and negative indices
        [{"index": 3, "relevance_score": 0.5}],
        [{"index": -1, "relevance_score": 0.5}],
        # missing indices (a gap)
        [{"index": 0, "relevance_score": 0.5}, {"index": 2, "relevance_score": 0.1}],
        # everything missing
        [],
        # relevance_score absent
        [{"index": 0}],
    ],
)
async def test_rerank_rejects_malformed_results_with_a_typed_error(
    results: list[dict[str, Any]],
) -> None:
    transport = RerankTransport(script=[_rerank_response(results)])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    with pytest.raises(RerankResponseError):
        await client.rerank("q", ["a", "b", "c"])


async def test_rerank_with_no_documents_makes_no_call() -> None:
    transport = RerankTransport(script=[])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    assert await client.rerank("q", []) == []
    assert transport.calls == []


# --- CL-05 / S3: generate_json on the port -----------------------------------


def _chat_response(content: str | None) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


async def test_generate_json_posts_chat_completions_with_json_schema_and_never_tools() -> None:
    transport = RerankTransport(script=[_chat_response('{"respuesta": "hola"}')])
    client = NanLLMClient(
        _settings(chat_model="deepseek-v4-flash"), client=transport, sleep=_fake_sleep
    )

    payload = await client.generate_json(system="sys", user="usr", schema={"type": "object"})

    assert payload == {"respuesta": "hola"}
    assert transport.calls[0]["path"] == "/chat/completions"
    body = transport.calls[0]["body"]
    assert body["model"] == "deepseek-v4-flash"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}
    # The provider's strict json_schema mode only works without tools.
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_generate_json_retries_429_and_succeeds() -> None:
    transport = RerankTransport(script=[429, _chat_response('{"ok": true}')])
    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = NanLLMClient(_settings(), client=transport, sleep=recording_sleep)

    assert await client.generate_json(system="s", user="u", schema={}) == {"ok": True}
    assert len(transport.calls) == 2
    assert len(delays) == 1
    assert 0 < delays[0] <= 20.0


async def test_generate_json_persistent_429_raises_a_typed_error() -> None:
    transport = RerankTransport(script=[429, 429, 429, 429, 429])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    with pytest.raises(LLMRetriesExhaustedError):
        await client.generate_json(system="s", user="u", schema={})

    assert len(transport.calls) == 5


@pytest.mark.parametrize(
    "content",
    ["[1, 2]", '"texto"', "no soy json", None],
)
async def test_generate_json_rejects_non_object_payloads_with_a_typed_error(
    content: str | None,
) -> None:
    transport = RerankTransport(script=[_chat_response(content)])
    client = NanLLMClient(_settings(), client=transport, sleep=_fake_sleep)

    with pytest.raises(ChatResponseError):
        await client.generate_json(system="s", user="u", schema={})
