"""Integration tests for the retrieval API endpoints (CL-04, BRIEF section 9).

`GET /buscar` is the debug ranking view (no generation) and
`GET /articulos/{numero}` returns the full text of an article. The real
LLM dependency is overridden with `FakeLLMClient`; no network is touched.

    DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp \
        uv run pytest tests/integration/test_api_search.py
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.deps import get_llm
from app.db.models import Chunk, Fuente
from app.db.session import get_session_factory
from app.domain.lcsp_parser import parse_lcsp
from app.main import create_app
from app.services.ingest import ingest_chunks
from tests.fakes import FakeLLMClient

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "retrieval_lcsp.xml"


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


async def _ingest_fixture() -> None:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    async with get_session_factory()() as session:
        await ingest_chunks(session, chunks, FakeLLMClient())


def _app_with_fake_llm(fake: FakeLLMClient) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_llm] = lambda: fake
    return app


async def test_buscar_returns_the_hybrid_ranking_with_scores() -> None:
    await _ingest_fixture()
    llm = FakeLLMClient(rerank_scores={})
    app = _app_with_fake_llm(llm)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/buscar", params={"q": "garantía definitiva"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "garantía definitiva"
    assert body["results"], "expected at least one ranked chunk"
    first = body["results"][0]
    assert first["articulo"] == "107"
    assert 0.0 <= first["score"] <= 1.0
    assert first["branches"]
    assert body["best_score"] is not None


async def test_buscar_direct_article_question_returns_article_107_first() -> None:
    await _ingest_fixture()
    app = _app_with_fake_llm(FakeLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/buscar", params={"q": "¿Qué dice el artículo 107?"})

    assert response.status_code == 200
    body = response.json()
    assert body["results"], "the article named in the question must be retrieved"
    assert body["results"][0]["articulo"] == "107"
    assert "direct" in body["results"][0]["branches"]


async def test_articulo_returns_the_full_text_of_every_chunk() -> None:
    await _ingest_fixture()
    app = _app_with_fake_llm(FakeLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/articulos/107")

    assert response.status_code == 200
    body = response.json()
    assert body["articulo"] == "107"
    assert body["chunks"], "the article's chunks carry its full text"
    assert all(chunk["articulo"] == "107" for chunk in body["chunks"])
    assert all(chunk["texto"] for chunk in body["chunks"])
    assert all(chunk["url"].startswith("https://www.boe.es/") for chunk in body["chunks"])
    assert all("Artículo 107" in chunk["titulo"] for chunk in body["chunks"])


async def test_unknown_article_returns_404_with_a_typed_error_body() -> None:
    await _ingest_fixture()
    app = _app_with_fake_llm(FakeLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/articulos/999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "article_not_found"
    assert "999" in response.json()["error"]["message"]
