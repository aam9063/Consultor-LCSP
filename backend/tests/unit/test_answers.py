"""Unit tests for the answering service (CL-05, S3/S12/S13, AC-06/AC-07).

No DB: `hybrid_search` is stubbed with deterministic `RetrievalResult`s
(the service is the unit under test, retrieval is a collaborator). The
integration suite covers the real retrieval path. All generation runs on
`FakeLLMClient` with scripted payloads.
"""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient, LLMError
from app.config import Settings, get_settings
from app.domain.citations import Citation
from app.services import answers
from app.services.retrieval import RetrievalResult, RetrievedChunk
from tests.fakes import FakeLLMClient

ABSTENTION = "No encuentro base en la LCSP para responder esto"


def _payload(respuesta: str, *, abstencion: bool = False) -> dict[str, object]:
    return {
        "respuesta": respuesta,
        "citas": [],
        "abstencion": abstencion,
        "motivo_abstencion": None if not abstencion else "no hay base",
    }


def _chunk(articulo: str = "107", texto: str = "texto del 107") -> RetrievedChunk:
    return RetrievedChunk(
        id=1,
        articulo=articulo,
        apartado=None,
        titulo=f"Artículo {articulo}",
        url="https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902",
        texto=texto,
        score=0.9,
        branches=("direct",),
    )


def _retrieval(chunks: list[RetrievedChunk], best_score: float | None = 0.9) -> RetrievalResult:
    return RetrievalResult(query="¿pregunta?", chunks=chunks, best_score=best_score)


async def _answer(
    monkeypatch: pytest.MonkeyPatch,
    llm: FakeLLMClient,
    retrieval: RetrievalResult,
    question: str = "¿Qué importe tiene la garantía definitiva?",
) -> answers.AnswerResult:
    async def fake_search(
        _session: AsyncSession,
        _llm: LLMClient,
        _query: str,
        *,
        top_k: int = 6,  # noqa: ARG001 - must match the real signature
    ) -> RetrievalResult:
        return retrieval

    monkeypatch.setattr(answers, "hybrid_search", fake_search)
    monkeypatch.setattr(answers, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    session = cast("AsyncSession", object())
    return await answers.answer_question(session, llm, question)


# --- AC-07: abstention before any generation ---------------------------------


async def test_low_best_score_abstains_without_calling_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()

    result = await _answer(monkeypatch, llm, _retrieval([_chunk()], best_score=0.1))

    assert result.abstencion is True
    assert result.respuesta == ABSTENTION
    assert result.motivo_abstencion == ABSTENTION
    assert result.citas == ()
    assert llm.generation_calls == 0


async def test_nothing_retrieved_abstains_without_calling_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()

    result = await _answer(monkeypatch, llm, _retrieval([], best_score=None))

    assert result.abstencion is True
    assert result.respuesta == ABSTENTION
    assert llm.generation_calls == 0


async def test_a_best_score_equal_to_the_threshold_does_not_abstain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient(generation_responses=[_payload("La garantía es del 5 por 100 [art. 107].")])

    # Derived from the configured threshold, so recalibrating it never turns a
    # boundary test into a false failure.
    threshold = get_settings().rerank_threshold
    result = await _answer(monkeypatch, llm, _retrieval([_chunk()], best_score=threshold))

    assert result.abstencion is False
    assert llm.generation_calls == 1


# --- AC-06: validation, exactly one retry, unsupported marking ---------------


async def test_answering_without_any_backed_citation_abstains_after_one_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = _payload("La garantía es del 5 por 100 [art. 999].")
    llm = FakeLLMClient(generation_responses=[bad, bad])

    result = await _answer(monkeypatch, llm, _retrieval([_chunk()]))

    assert llm.generation_calls == 2, "exactly one retry, no more"
    assert "art. 999" in llm.generation_requests[1]["user"], "the retry carries the feedback"
    # An answer with no backed citation is worse than no answer for a legal tool.
    assert result.abstencion is True
    assert result.respuesta == "No encuentro base en la LCSP para responder esto"
    assert result.citas == ()
    assert result.unsupported_claims == ()
    assert result.motivo_abstencion is not None
    assert "art. 999" in result.motivo_abstencion


async def test_the_retry_can_fix_the_citation(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLMClient(
        generation_responses=[
            _payload("Primera [art. 999]."),
            _payload("La garantía es del 5 por 100 [art. 107]."),
        ]
    )

    result = await _answer(monkeypatch, llm, _retrieval([_chunk()]))

    assert llm.generation_calls == 2
    assert result.warning is None
    assert result.unsupported_claims == ()
    assert result.citas == (Citation("107", None),)


# --- model-driven abstention and malformed payloads --------------------------


async def test_a_model_abstention_is_honoured_without_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient(generation_responses=[_payload("", abstencion=True)])

    result = await _answer(monkeypatch, llm, _retrieval([_chunk()]))

    assert result.abstencion is True
    assert result.motivo_abstencion == "no hay base"
    assert result.citas == ()
    assert llm.generation_calls == 1


async def test_a_malformed_payload_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient(generation_responses=[{"respuesta": 42}])

    with pytest.raises(LLMError):
        await _answer(monkeypatch, llm, _retrieval([_chunk()]))
