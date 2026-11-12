"""Integration tests for `POST /consultas` (CL-05, S3/S12/S13, AC-06/AC-07).

The real Postgres 18 + pgvector container serves the retrieval path; the
LLM dependency is overridden with `FakeLLMClient` (scripted generation,
no network):

    DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp \
        uv run pytest tests/integration/test_answers.py
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

ABSTENTION = "No encuentro base en la LCSP para responder esto"


def _payload(respuesta: str) -> dict[str, Any]:
    return {
        "respuesta": respuesta,
        "citas": [],
        "abstencion": False,
        "motivo_abstencion": None,
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


# --- AC-07: abstention with zero generation calls -----------------------------


async def test_low_best_score_abstains_with_the_exact_message_and_no_generation() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores={chunk.texto: 0.05 for chunk in chunks},
        generation_responses=[],  # must never be reached
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/consultas", json={"pregunta": "¿Cómo se calcula la garantía definitiva?"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["abstencion"] is True
    assert body["respuesta"] == ABSTENTION
    assert body["motivo_abstencion"] == ABSTENTION
    assert body["citas"] == []
    assert llm.generation_calls == 0


# --- AC-06: validation, exactly one retry, unsupported marking ----------------


async def test_answering_without_any_backed_citation_abstains_after_one_retry() -> None:
    chunks = await _ingest_fixture()
    bad_answer = "La garantía definitiva es el 5 por 100 del importe de adjudicación [art. 999]."
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[_payload(bad_answer), _payload(bad_answer)],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/consultas", json={"pregunta": "¿Qué importe tiene la garantía definitiva?"}
        )

    assert response.status_code == 200
    body = response.json()
    assert llm.generation_calls == 2, "exactly one retry"
    assert "art. 999" in llm.generation_requests[1]["user"], "the retry carries the feedback"
    # An answer with no backed citation is worse than no answer: the service
    # abstains instead of shipping it with a warning.
    assert body["abstencion"] is True
    assert body["respuesta"] == "No encuentro base en la LCSP para responder esto"
    assert body["motivo_abstencion"] is not None and "art. 999" in body["motivo_abstencion"]
    assert body["afirmaciones_no_respaldadas"] == []
    assert body["advertencia"] is None
    assert body["citas"] == []


async def test_the_retry_can_fix_the_citation() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[
            _payload("Primera afirmación [art. 999]."),
            _payload("La garantía definitiva es el 5 por 100 [art. 107]."),
        ],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/consultas", json={"pregunta": "¿Qué importe tiene la garantía definitiva?"}
        )

    assert response.status_code == 200
    body = response.json()
    assert llm.generation_calls == 2
    assert body["advertencia"] is None
    assert body["afirmaciones_no_respaldadas"] == []
    assert body["citas"] == [{"articulo": "107", "apartado": None}]


# --- the good path: 200 with citations and the retrieved chunks ---------------


async def test_good_answer_returns_the_cited_answer_with_chunks() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[_payload("La garantía definitiva es el 5 por 100 [art. 107].")],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/consultas", json={"pregunta": "¿Qué importe tiene la garantía definitiva?"}
        )

    assert response.status_code == 200
    body = response.json()
    assert llm.generation_calls == 1
    assert body["abstencion"] is False
    assert body["respuesta"] == "La garantía definitiva es el 5 por 100 [art. 107]."
    assert body["citas"] == [{"articulo": "107", "apartado": None}]
    assert body["advertencia"] is None
    assert body["afirmaciones_no_respaldadas"] == []
    assert isinstance(body["modelo"], str) and body["modelo"]
    assert next(chunk["articulo"] for chunk in body["chunks"]) == "107"
    assert all(0.0 <= chunk["score"] <= 1.0 for chunk in body["chunks"])


# --- a predictable generation failure is a typed error, not a bare 500 --------


async def test_malformed_generation_payload_returns_a_typed_502() -> None:
    chunks = await _ingest_fixture()
    llm = FakeLLMClient(
        rerank_scores=_rerank_scores(chunks, good="107"),
        generation_responses=[{"respuesta": 42}],
    )
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/consultas", json={"pregunta": "¿Qué importe tiene la garantía definitiva?"}
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_unavailable"
