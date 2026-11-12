"""Integration tests for `POST /revisiones` (CL-06, S4/S14, AC-08).

The real Postgres 18 + pgvector container serves the retrieval path; the
LLM dependency is overridden with `FakeLLMClient` (scripted generation,
no network):

    DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp \
        uv run pytest tests/integration/test_revisions.py
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.deps import get_llm
from app.db.models import Chunk, Fuente
from app.db.session import get_session_factory
from app.domain.lcsp_parser import LcspChunk, parse_lcsp
from app.main import create_app
from app.services.ingest import ingest_chunks
from tests.fakes import FakeLLMClient

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "retrieval_lcsp.xml"

CLAUSE = "El contratista quedará exento de constituir la garantía definitiva."
FRAGMENT = "garantía definitiva"


def _aviso(
    tipo: str = "posible_incumplimiento",
    cita: str = "[art. 107]",
    fragmento: str = FRAGMENT,
) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "explicacion": "La cláusula elimina la garantía definitiva exigida por la ley.",
        "articulos_citados": [cita],
        "cita_de_la_clausula": fragmento,
    }


def _payload(avisos: list[dict[str, Any]]) -> dict[str, Any]:
    return {"avisos": avisos}


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


# --- AC-08: typed warnings whose citations all belong to the retrieved chunks --


async def test_clause_review_returns_typed_warnings_backed_by_retrieved_chunks() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[_payload([_aviso(), _aviso(tipo="ok", cita="[art. 159]")])],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones", json={"clausula": CLAUSE})

    assert response.status_code == 200
    body = response.json()
    retrieved_articles = {chunk["articulo"] for chunk in body["chunks"]}
    assert len(body["avisos"]) == 2
    assert body["avisos"][0]["tipo"] == "posible_incumplimiento"
    assert body["avisos"][0]["cita_de_la_clausula"] == FRAGMENT
    for aviso in body["avisos"]:
        for citation in aviso["articulos_citados"]:
            assert citation["articulo"] in retrieved_articles, "only retrieved articles"
    assert body["avisos_invalidos"] == []
    assert body["sin_observaciones"] is False
    assert llm.generation_calls == 1


# --- invented citations: exactly one retry, then drop and report ---------------


async def test_invented_citation_is_retried_exactly_once_and_then_dropped() -> None:
    chunks = await _ingest_fixture()
    invented = _payload([_aviso(cita="[art. 999]")])
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[invented, invented],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones", json={"clausula": CLAUSE})

    assert response.status_code == 200
    body = response.json()
    assert llm.generation_calls == 2, "exactly one retry"
    assert "art. 999" in llm.generation_requests[1]["user"], "the retry carries the feedback"
    assert body["avisos"] == [], "a citation that does not exist is never shown"
    assert len(body["avisos_invalidos"]) == 1
    assert "articulo_no_recuperado" in body["avisos_invalidos"][0]["motivos"]


async def test_the_retry_can_fix_the_citation() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[
            _payload([_aviso(cita="[art. 999]")]),
            _payload([_aviso(cita="[art. 107]")]),
        ],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones", json={"clausula": CLAUSE})

    assert response.status_code == 200
    body = response.json()
    assert llm.generation_calls == 2
    assert len(body["avisos"]) == 1
    assert body["avisos"][0]["articulos_citados"] == [{"articulo": "107", "apartado": None}]
    assert body["avisos_invalidos"] == []


# --- typed request errors ------------------------------------------------------


async def test_an_oversized_clause_returns_a_typed_422() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(rerank_scores=_rerank_scores(chunks, good="107"))
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones", json={"clausula": " ".join(["palabra"] * 801)})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "clausula_demasiado_larga"
    assert llm.generation_calls == 0


async def test_a_missing_clause_returns_a_typed_422() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(rerank_scores=_rerank_scores(chunks, good="107"))
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/revisiones", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "clausula_ausente"
    assert llm.generation_calls == 0
