"""Unit tests for the Radar review service (S7-02, S3/S4).

No DB: `hybrid_search` is stubbed with deterministic `RetrievalResult`s, the
same way `test_clause_service.py` stubs it. The service under test reuses the
existing clause-review engine; every generation runs on `FakeLLMClient`.
"""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient
from app.config import Settings
from app.domain.clauses import REASON_ARTICULO_NO_RECUPERADO
from app.domain.radar_ficha import (
    MAX_FICHA_WORDS,
    REASON_FICHA_DEMASIADO_LARGA,
    RadarFichaError,
    RadarFichaInput,
)
from app.services import clauses as clause_service
from app.services import radar as radar_service
from app.services.retrieval import RetrievalResult, RetrievedChunk
from tests.fakes import FakeLLMClient

PENALIDAD = "El contratista que no respete el plazo de ejecución sufrirá una penalidad del 10%."
GARANTIA = "La garantía definitiva se fija en el 5% del importe de licitación."
PENALIDAD_FRAGMENT = "penalidad del 10%"
GARANTIA_FRAGMENT = "5% del importe"


def _payload(avisos: list[dict[str, object]]) -> dict[str, object]:
    return {"avisos": avisos}


def _aviso(
    fragmento: str = PENALIDAD_FRAGMENT,
    citas: list[str] | None = None,
) -> dict[str, object]:
    return {
        "tipo": "posible_incumplimiento",
        "explicacion": "La cláusula se aparta de lo que permite la ley.",
        "articulos_citados": ["[art. 107]"] if citas is None else citas,
        "cita_de_la_clausula": fragmento,
    }


def _input(
    penalidades: list[str] | None = None,
    garantia_definitiva: str | None = GARANTIA,
) -> RadarFichaInput:
    return RadarFichaInput(
        licitacion_id=42,
        expediente="EXP-2026-001",
        penalidades=[PENALIDAD] if penalidades is None else penalidades,
        garantia_definitiva=garantia_definitiva,
    )


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
    return RetrievalResult(query="ficha de radar", chunks=chunks, best_score=best_score)


async def _review(
    monkeypatch: pytest.MonkeyPatch,
    llm: FakeLLMClient,
    retrieval: RetrievalResult,
    ficha: RadarFichaInput | None = None,
) -> radar_service.RadarReviewResult:
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
    return await radar_service.review_radar_ficha(session, llm, ficha or _input())


# --- one generation pass, avisos carry their origin field ---------------------


async def test_one_generation_call_and_each_aviso_carries_its_origin_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient(
        generation_responses=[
            _payload([_aviso(), _aviso(fragmento=GARANTIA_FRAGMENT)]),
        ]
    )

    result = await _review(monkeypatch, llm, _retrieval([_chunk()]))

    assert llm.generation_calls == 1, "one generation pass per request"
    assert result.model_called is True
    assert result.sin_observaciones is False
    assert len(result.avisos) == 2
    assert result.avisos[0][0].cita_de_la_clausula == PENALIDAD_FRAGMENT
    assert result.avisos[0][1] == "penalidades"
    assert result.avisos[1][0].cita_de_la_clausula == GARANTIA_FRAGMENT
    assert result.avisos[1][1] == "garantia_definitiva"
    assert result.avisos_invalidos == ()
    assert result.licitacion_id == 42
    assert result.expediente == "EXP-2026-001"


# --- invented citations: the engine drops them, never accepted ----------------


async def test_an_aviso_with_a_non_retrieved_citation_surfaces_as_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invented = _payload([_aviso(citas=["[art. 999]"])])
    llm = FakeLLMClient(generation_responses=[invented, invented])

    result = await _review(monkeypatch, llm, _retrieval([_chunk()]))

    assert result.avisos == (), "the offending warning is never accepted"
    assert len(result.avisos_invalidos) == 1
    assert REASON_ARTICULO_NO_RECUPERADO in result.avisos_invalidos[0].motivos
    assert llm.generation_calls == 2, "the engine's bounded retry still applies"


# --- no basis: abstention before generation -----------------------------------


async def test_sub_threshold_retrieval_returns_sin_observaciones_without_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()

    result = await _review(monkeypatch, llm, _retrieval([_chunk()], best_score=0.1))

    assert result.sin_observaciones is True
    assert result.observaciones == "sin observaciones fundadas"
    assert result.avisos == ()
    assert result.model_called is False
    assert llm.generation_calls == 0


# --- invalid ficha: rejected before any call ----------------------------------


async def test_an_oversized_ficha_is_rejected_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLLMClient()
    ficha = _input(
        penalidades=[],
        garantia_definitiva=" ".join(["palabra"] * (MAX_FICHA_WORDS + 1)),
    )

    with pytest.raises(RadarFichaError) as excinfo:
        await _review(monkeypatch, llm, _retrieval([_chunk()]), ficha=ficha)

    assert excinfo.value.motivo == REASON_FICHA_DEMASIADO_LARGA
    assert llm.calls == [], "not even an embedding call"
    assert llm.generation_calls == 0
