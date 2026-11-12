"""LLM adapters: the `LLMClient` port and the NaN Builders client (CL-03/04/05).

The port is a `Protocol` that grows with the project: CL-05 adds
`generate_json` (one JSON-schema-constrained chat completion), and existing
callers are unaffected because a protocol only requires the methods a
caller actually uses. No domain module imports this file; services depend
on the port, not the concrete client.
"""

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# NaN Builders limits (AGENTS.md section 2): 60 req/min and 7 concurrent
# requests per key. We stay below both with a semaphore of 5.
_MAX_CONCURRENCY = 5
_REQUEST_TIMEOUT_S = 60.0
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 20.0


class LLMError(Exception):
    """Base class for typed LLM adapter errors."""


class MissingAPIKeyError(LLMError):
    """The real client needs NAN_API_KEY and none is configured."""


class LLMRetriesExhaustedError(LLMError):
    """The provider kept returning a retryable status after bounded attempts."""


class EmbeddingDimensionError(LLMError):
    """An embedding vector does not have the configured number of components."""


class RerankResponseError(LLMError):
    """The rerank response cannot be aligned to the input documents."""


class ChatResponseError(LLMError):
    """The chat completion payload is missing, unreadable or not a JSON object."""


class LLMClient(Protocol):
    """Port for LLM providers; services must depend on this, not on NaN."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts`, preserving order. Raises `LLMError` subclasses."""
        ...

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Score `documents` against `query`, one score per document in input order.

        Raises `LLMError` subclasses.
        """
        ...

    async def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """One JSON-schema-constrained chat completion, decoded to an object.

        Raises `LLMError` subclasses.
        """
        ...


class _EmbeddingsTransport(Protocol):
    """The slice of the OpenAI SDK client this adapter touches (tests stub it)."""

    @property
    def embeddings(self) -> Any: ...


class _RerankTransport(Protocol):
    """The generic `POST` slice of the OpenAI SDK used by `rerank`.

    The SDK has no rerank method, so the adapter calls the provider's
    `/rerank` endpoint through the SDK's generic `client.post(...)`.
    """

    async def post(self, path: str, *, cast_to: Any, body: Any = None) -> Any: ...


class _ChatTransport(Protocol):
    """The generic `POST` slice of the OpenAI SDK used by `generate_json`.

    Chat completions go through the same generic `client.post(...)` seam
    so tests can script the raw provider responses.
    """

    async def post(self, path: str, *, cast_to: Any, body: Any = None) -> Any: ...


class NanLLMClient:
    """Official `openai` SDK client against the NaN Builders API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: _EmbeddingsTransport | _RerankTransport | _ChatTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        resolved = settings if settings is not None else get_settings()
        self._model = resolved.embedding_model
        self._rerank_model = resolved.rerank_model
        self._chat_model = resolved.chat_model
        self._batch_size = resolved.embedding_batch_size
        self._dimensions = resolved.embedding_dimensions
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._client: Any
        if client is not None:
            # Test seam: an injected transport never needs a real key.
            self._client = client
            return
        api_key = resolved.nan_api_key.get_secret_value()
        if not api_key:
            raise MissingAPIKeyError(
                "NAN_API_KEY is not set: the real NaN client cannot run. "
                "Set it in the environment or use --dry-run."
            )
        self._client = AsyncOpenAI(
            base_url=resolved.nan_base_url,
            api_key=api_key,
            timeout=_REQUEST_TIMEOUT_S,
            max_retries=0,  # retries are handled here, with our own backoff
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches of `EMBEDDING_BATCH_SIZE`, order preserved.

        Batches run up to 5 at a time; each request retries on 429/5xx with
        exponential backoff and jitter. Every returned vector is validated
        against `EMBEDDING_DIMENSIONS`.
        """
        if not texts:
            return []
        batches = [texts[i : i + self._batch_size] for i in range(0, len(texts), self._batch_size)]
        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        batch_results: list[list[list[float]] | None] = [None] * len(batches)

        async def run_batch(index: int, batch: list[str]) -> None:
            async with semaphore:
                batch_results[index] = await self._embed_batch(batch)

        await asyncio.gather(*(run_batch(i, batch) for i, batch in enumerate(batches)))
        vectors: list[list[float]] = []
        for result in batch_results:
            if result is None:  # pragma: no cover - gather guarantees every batch ran
                raise LLMError("embedding batch did not produce a result")
            vectors.extend(result)
        for index, vector in enumerate(vectors):
            if len(vector) != self._dimensions:
                raise EmbeddingDimensionError(
                    f"embedding {index} has {len(vector)} components, "
                    f"expected {self._dimensions} (model={self._model})"
                )
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        response = await self._request_with_retry(batch)
        latency_s = time.perf_counter() - started
        usage = getattr(response, "usage", None)
        logger.info(
            "embedding batch model=%s texts=%d latency_s=%.3f prompt_tokens=%s total_tokens=%s",
            self._model,
            len(batch),
            latency_s,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "total_tokens", None),
        )
        return [list(item.embedding) for item in response.data]

    async def _request_with_retry(self, batch: list[str]) -> Any:
        return await self._send_with_retry(
            lambda: self._client.embeddings.create(model=self._model, input=batch),
            operation="embedding",
            model=self._model,
        )

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Score documents against `query`; one score per document, input order.

        The provider answers `{"results": [{"index", "relevance_score"}, ...]}`
        sorted by score descending, but neither that ordering nor the
        completeness of `results` is trusted: the adapter validates every
        index and rebuilds the list aligned to the input order. Document
        text and the API key are never logged.
        """
        if not documents:
            return []
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self._rerank_model,
            "query": query,
            "documents": documents,
        }
        response = await self._send_with_retry(
            lambda: self._client.post("/rerank", cast_to=object, body=payload),
            operation="rerank",
            model=self._rerank_model,
        )
        scores = _aligned_rerank_scores(response, len(documents))
        logger.info(
            "rerank model=%s documents=%d latency_s=%.3f",
            self._rerank_model,
            len(documents),
            time.perf_counter() - started,
        )
        return scores

    async def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one JSON-schema-constrained chat completion and decode the object.

        The request uses `response_format` of type `json_schema` and **never
        sends `tools`**: the provider's strict json_schema mode only works on
        `/chat/completions` without tools (AGENTS.md section 2). The bounded
        retry helper backs 429/5xx, and the key and the full prompt/answer
        text are never logged. A payload that is not a JSON object raises
        `ChatResponseError`.
        """
        body: dict[str, Any] = {
            "model": self._chat_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "respuesta",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        started = time.perf_counter()
        response = await self._send_with_retry(
            lambda: self._client.post("/chat/completions", cast_to=object, body=body),
            operation="chat",
            model=self._chat_model,
        )
        payload = _decoded_chat_json(response)
        logger.info("chat model=%s latency_s=%.3f", self._chat_model, time.perf_counter() - started)
        return payload

    async def _send_with_retry(
        self, send: Callable[[], Awaitable[Any]], *, operation: str, model: str
    ) -> Any:
        """Run one provider request with bounded retries on transient failures.

        Shared by embeddings and rerank. Transient means a 429, a 5xx, or a
        transport failure (`APIConnectionError`, which also covers timeouts):
        none of those are the caller's fault and any of them would otherwise
        abort a 37-batch ingestion on the first network hiccup. Backoff is
        exponential with jitter, attempts are bounded, and the final error is
        typed. A non-retryable status (400, 401, 404...) propagates untouched.
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await send()
            except APIStatusError as error:
                status = error.status_code
                if not (status == 429 or status >= 500):
                    raise
                failure: Exception = error
                reason = f"status={status}"
            except APIConnectionError as error:
                failure = error
                reason = "connection error"
            if attempt == _MAX_ATTEMPTS:
                raise LLMRetriesExhaustedError(
                    f"{operation} request failed after {attempt} attempts "
                    f"(last {reason}, model={model})"
                ) from failure
            delay = self._backoff_delay(attempt)
            logger.warning(
                "%s request retryable failure attempt=%d reason=%s retry_in_s=%.2f model=%s",
                operation,
                attempt,
                reason,
                delay,
                model,
            )
            await self._sleep(delay)
        raise LLMRetriesExhaustedError("unreachable retry loop end")  # pragma: no cover

    def _backoff_delay(self, attempt: int) -> float:
        exponential: float = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1))
        jitter_factor: float = 0.5 + self._rng.random()
        # Jitter spreads retries over [0.5x, 1.5x] of the exponential slot.
        return exponential * jitter_factor


def _decoded_chat_json(response: Any) -> dict[str, Any]:
    """Decode a chat completion into a JSON object, with typed errors.

    The provider answers `{"choices": [{"message": {"content": "..."}}]}`
    where `content` is the JSON document as text. Anything else — no
    choices, no textual content, invalid JSON, or a non-object payload —
    raises `ChatResponseError`. The text itself is never logged.
    """
    if not isinstance(response, dict):
        raise ChatResponseError("chat response is not a JSON object")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChatResponseError("chat response has no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ChatResponseError("chat response has no textual content")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ChatResponseError("chat content is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ChatResponseError("chat content is not a JSON object")
    return payload


def _aligned_rerank_scores(response: Any, document_count: int) -> list[float]:
    """Validate the provider's rerank results and rebuild them in input order."""
    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
        raise RerankResponseError("rerank response does not contain a 'results' list")
    scores = [0.0] * document_count
    seen: set[int] = set()
    for entry in response["results"]:
        index = entry.get("index") if isinstance(entry, dict) else None
        score = entry.get("relevance_score") if isinstance(entry, dict) else None
        if not isinstance(index, int) or isinstance(index, bool):
            raise RerankResponseError(f"rerank result has a non-integer index: {index!r}")
        if not 0 <= index < document_count:
            raise RerankResponseError(
                f"rerank result index {index} is out of range for {document_count} documents"
            )
        if index in seen:
            raise RerankResponseError(f"rerank response repeats index {index}")
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise RerankResponseError(
                f"rerank result for index {index} has no numeric relevance_score"
            )
        seen.add(index)
        scores[index] = float(score)
    missing = [index for index in range(document_count) if index not in seen]
    if missing:
        raise RerankResponseError(f"rerank response is missing results for indices {missing}")
    return scores
