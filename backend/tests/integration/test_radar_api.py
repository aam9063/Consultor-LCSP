"""Integration tests for `POST /revisiones/radar` (S7-04, S6).

The real Postgres 18 + pgvector container serves the retrieval path; the
LLM dependency is overridden with `FakeLLMClient` (scripted generation,
no network):

    DATABASE_URL_TEST=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp_test \
        DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp_test \
        uv run pytest tests/integration/test_radar_api.py
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.deps import get_llm
from app.config import get_settings
from app.db.models import Chunk, Fuente
from app.db.session import get_session_factory
from app.domain.lcsp_parser import LcspChunk, parse_lcsp
from app.domain.radar_ficha import MAX_FICHA_WORDS
from app.main import create_app
from app.services.ingest import ingest_chunks
from tests.fakes import FakeLLMClient

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "retrieval_lcsp.xml"

PENALIDAD = "El órgano de contratación podrá imponer penalidades por demora en la ejecución."
GARANTIA = "La garantía definitiva será del 5 por ciento del importe de adjudicación."
EXPEDIENTE = "EXP-2026-042"
LICITACION_ID = 42


def _ficha_payload() -> dict[str, Any]:
    """The ficha Radar pushes: one penalty and the definitive guarantee."""
    return {
        "licitacion_id": LICITACION_ID,
        "expediente": EXPEDIENTE,
        "penalidades": [PENALIDAD],
        "garantia_definitiva": GARANTIA,
    }


def _aviso(cita: str, fragmento: str) -> dict[str, Any]:
    return {
        "tipo": "posible_incumplimiento",
        "explicacion": "El pliego fija condiciones que deben contrastarse con la ley.",
        "articulos_citados": [cita],
        "cita_de_la_clausula": fragmento,
    }


async def _cleanup() -> None:
    async with get_session_factory()() as session:
        await session.execute(delete(Chunk))
        await session.execute(delete(Fuente))
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_db() -> AsyncGenerator[None]:
    await _cleanup()
    yield
    await _cleanup()


async def _ingest_fixture() -> list[LcspChunk]:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    async with get_session_factory()() as session:
        await ingest_chunks(session, chunks, FakeLLMClient())
    return chunks


def _app_with_fake_llm(fake: FakeLLMClient) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_llm] = lambda: fake
    return app


def _rerank_scores(chunks: list[LcspChunk], *, good: str) -> dict[str, float]:
    """Pin the reranker so `good`'s chunks clear the abstention threshold."""
    return {chunk.texto: (0.9 if chunk.articulo == good else 0.05) for chunk in chunks}


# --- S1/S4: happy path, the aviso is accepted with its origin field ----------


async def test_radar_ficha_returns_the_aviso_with_its_origin_field_and_echo() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="159"),
        generation_responses=[{"avisos": [_aviso("[art. 159]", PENALIDAD)]}],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones/radar", json=_ficha_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["licitacion_id"] == LICITACION_ID, "the entry is echoed for Radar"
    assert body["expediente"] == EXPEDIENTE, "the entry is echoed for Radar"
    retrieved_articles = {chunk["articulo"] for chunk in body["chunks"]}
    assert len(body["avisos"]) == 1
    aviso = body["avisos"][0]
    assert aviso["tipo"] == "posible_incumplimiento"
    assert aviso["cita_de_la_clausula"] == PENALIDAD
    assert aviso["campo_origen"] == "penalidades", "the quote lives in the penalties section"
    for citation in aviso["articulos_citados"]:
        assert citation["articulo"] in retrieved_articles, "only retrieved articles"
    assert body["avisos_invalidos"] == []
    assert body["sin_observaciones"] is False
    assert body["modelo"]
    assert llm.generation_calls == 1


# --- S3: an invented citation is dropped, never surfaced as valid -------------


async def test_an_invented_citation_is_dropped_and_reported_as_invalid() -> None:
    chunks = await _ingest_fixture()
    invented = {"avisos": [_aviso("[art. 999]", PENALIDAD)]}
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="159"),
        generation_responses=[invented, invented],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones/radar", json=_ficha_payload())

    assert response.status_code == 200
    body = response.json()
    assert llm.generation_calls == 2, "exactly one retry before dropping"
    assert body["avisos"] == [], "a citation that does not exist is never shown"
    assert len(body["avisos_invalidos"]) == 1
    invalido = body["avisos_invalidos"][0]
    assert "articulo_no_recuperado" in invalido["motivos"]
    assert "[art. 999]" in invalido["articulos_citados"], "the raw invented citation is reported"


# --- S3: no base in the LCSP → abstention before generating -------------------


async def test_a_ficha_without_retrieval_base_abstains_with_zero_generation_calls() -> None:
    chunks = await _ingest_fixture()
    threshold = get_settings().rerank_threshold
    llm = FakeLLMClient(
        rerank_scores={chunk.texto: threshold - 0.05 for chunk in chunks},
        generation_responses=[],  # must never be reached
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones/radar", json=_ficha_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["sin_observaciones"] is True
    assert body["observaciones"] == "sin observaciones fundadas"
    assert body["model_called"] is False
    assert body["avisos"] == []
    assert body["avisos_invalidos"] == []
    assert llm.generation_calls == 0, "the model is never called without retrieval base"


# --- S5: typed 422s, rejected before any retrieval or generation --------------


async def test_a_ficha_without_usable_data_returns_a_typed_422() -> None:
    llm = FakeLLMClient()  # no scripted responses: nothing may be called
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/revisiones/radar",
            json={"licitacion_id": 1, "penalidades": ["   "], "garantia_definitiva": "  "},
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "ficha_sin_datos"
    assert error["message"]
    assert llm.generation_calls == 0


async def test_a_ficha_over_the_reviewer_limit_returns_a_typed_422() -> None:
    # Derived from the imported limit, never a second hardcoded word count.
    over_limit = " ".join(["palabra"] * (MAX_FICHA_WORDS + 50))
    llm = FakeLLMClient()  # no scripted responses: nothing may be called
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/revisiones/radar",
            json={"licitacion_id": 1, "penalidades": [over_limit]},
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "ficha_demasiado_larga"
    assert error["message"]
    assert llm.generation_calls == 0
