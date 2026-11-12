"""LLM adapters: the `LLMClient` port and the NaN Builders client (CL-03, S1/S2).

The port is a `Protocol` that grows with the project: CL-04/CL-05 will add
`rerank` and `generate` methods, and existing callers are unaffected because
a protocol only requires the methods a caller actually uses. No domain
module imports this file; services depend on the port, not the concrete
client.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from openai import APIStatusError, AsyncOpenAI

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


class LLMClient(Protocol):
    """Port for LLM providers; services must depend on this, not on NaN."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts`, preserving order. Raises `LLMError` subclasses."""
        ...


class _EmbeddingsTransport(Protocol):
    """The slice of the OpenAI SDK client this adapter touches (tests stub it)."""

    @property
    def embeddings(self) -> Any: ...


class NanLLMClient:
    """Official `openai` SDK client against the NaN Builders API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: _EmbeddingsTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        resolved = settings if settings is not None else get_settings()
        self._model = resolved.embedding_model
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
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._client.embeddings.create(model=self._model, input=batch)
            except APIStatusError as error:
                status = error.status_code
                retryable = status == 429 or (status is not None and status >= 500)
                if not retryable:
                    raise
                if attempt == _MAX_ATTEMPTS:
                    raise LLMRetriesExhaustedError(
                        f"embedding request failed after {attempt} attempts "
                        f"(last status={status}, model={self._model})"
                    ) from error
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "embedding request retryable failure attempt=%d status=%s "
                    "retry_in_s=%.2f model=%s",
                    attempt,
                    status,
                    delay,
                    self._model,
                )
                await self._sleep(delay)
        raise LLMRetriesExhaustedError("unreachable retry loop end")  # pragma: no cover

    def _backoff_delay(self, attempt: int) -> float:
        exponential: float = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1))
        jitter_factor: float = 0.5 + self._rng.random()
        # Jitter spreads retries over [0.5x, 1.5x] of the exponential slot.
        return exponential * jitter_factor
