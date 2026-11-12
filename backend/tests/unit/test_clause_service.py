"""Unit tests for the clause-review service (CL-06, S4/S14, AC-08).

No DB: `hybrid_search` is stubbed with deterministic `RetrievalResult`s (the
service is the unit under test, retrieval is a collaborator). The integration
suite covers the real retrieval path. All generation runs on `FakeLLMClient`
with scripted payloads.
"""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient, LLMError
from app.config import Settings
from app.domain.clauses import REASON_ARTICULO_NO_RECUPERADO, ClauseTooLongError
from app.services import clauses as clause_service
from app.services.retrieval import RetrievalResult, RetrievedChunk
from tests.fakes import FakeLLMClient

SIN_OBSERVACIONES = "sin observaciones fundadas"
CLAUSE = "El contratista quedará exento de constituir la garantía definitiva."
FRAGMENT = "garantía definitiva"


def _payload(avisos: list[dict[str, object]]) -> dict[str, object]:
    return {"avisos": avisos}


def _aviso(
    tipo: str = "posible_incumplimiento",
    cita: str = "[art. 107]",
    fragmento: str = FRAGMENT,
) -> dict[str, object]:
    return {
        "tipo": tipo,
        "explicacion": "La cláusula elimina una garantía exigida por la ley.",
        "articulos_citados": [cita],
        "cita_de_la_clausula": fragmento,
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
    return RetrievalResult(query=CLAUSE, chunks=chunks, best_score=best_score)


async def _review(
    monkeypatch: pytest.MonkeyPatch,
    llm: FakeLLMClient,
    retrieval: RetrievalResult,
    clause: str = CLAUSE,
) -> clause_service.ReviewResult:
    async def fake_search(
        _session: AsyncSession,
        _llm: LLMClient,
        _query: str,
        *,
        top_k: int = 6,  # noqa: ARG001 - must match the real signature
    ) -> RetrievalResult:
        return retrieval

    monkeypatch.setattr(clause_service, "hybrid_search", fake_search)
    monkeypatch.setattr(clause_service, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    session = cast("AsyncSession", object())
    return await clause_service.review_clause(session, llm, clause)


# --- no basis: no generation at all ------------------------------------------


async def test_low_best_score_returns_sin_observaciones_fundadas_without_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()

    result = await _review(monkeypatch, llm, _retrieval([_chunk()], best_score=0.1))

    assert result.sin_observaciones is True
    assert result.observaciones == SIN_OBSERVACIONES
    assert result.avisos == ()
    assert result.model_called is False
    assert llm.generation_calls == 0
    assert result.chunks == tuple(_retrieval([_chunk()]).chunks)


async def test_nothing_retrieved_returns_sin_observaciones_fundadas_without_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()

    result = await _review(monkeypatch, llm, _retrieval([], best_score=None))

    assert result.observaciones == SIN_OBSERVACIONES
    assert result.model_called is False
    assert llm.generation_calls == 0


# --- happy path ---------------------------------------------------------------


async def test_happy_path_returns_the_validated_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLMClient(generation_responses=[_payload([_aviso()])])

    result = await _review(monkeypatch, llm, _retrieval([_chunk()]))

    assert llm.generation_calls == 1
    assert result.model_called is True
    assert result.sin_observaciones is False
    assert result.observaciones is None
    assert len(result.avisos) == 1
    assert result.avisos[0].tipo == "posible_incumplimiento"
    assert result.avisos[0].cita_de_la_clausula == FRAGMENT
    assert result.avisos_invalidos == ()
    assert result.chunks == tuple(_retrieval([_chunk()]).chunks)
    assert result.model == "deepseek-v4-flash"


# --- invented citations: exactly one retry, then drop and report --------------


async def test_invented_citation_is_retried_once_and_then_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invented = _payload([_aviso(cita="[art. 999]")])
    llm = FakeLLMClient(generation_responses=[invented, invented])

    result = await _review(monkeypatch, llm, _retrieval([_chunk()]))

    assert llm.generation_calls == 2, "exactly one retry, no more"
    assert "art. 999" in llm.generation_requests[1]["user"], "the retry carries the feedback"
    assert result.avisos == (), "the offending warning is dropped"
    assert len(result.avisos_invalidos) == 1
    assert REASON_ARTICULO_NO_RECUPERADO in result.avisos_invalidos[0].motivos
    assert result.model_called is True


async def test_the_retry_can_fix_the_citation(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLMClient(
        generation_responses=[
            _payload([_aviso(cita="[art. 999]")]),
            _payload([_aviso(cita="[art. 107]")]),
        ]
    )

    result = await _review(monkeypatch, llm, _retrieval([_chunk()]))

    assert llm.generation_calls == 2
    assert len(result.avisos) == 1
    assert result.avisos_invalidos == ()


# --- input checks happen before any call --------------------------------------


async def test_an_oversized_clause_is_rejected_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()
    clause = " ".join(["palabra"] * 801)

    with pytest.raises(ClauseTooLongError):
        await _review(monkeypatch, llm, _retrieval([_chunk()]), clause=clause)

    assert llm.calls == [], "not even an embedding call"
    assert llm.generation_calls == 0


async def test_a_malformed_payload_raises_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient(generation_responses=[cast("dict[str, object]", {"avisos": 42})])

    with pytest.raises(LLMError):
        await _review(monkeypatch, llm, _retrieval([_chunk()]))
