"""Integration tests for hybrid retrieval (CL-04, S2/S10/S11, AC-04/AC-05).

Run against the real Postgres 18 + pgvector container with the
`FakeLLMClient` (no network):

    DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp \
        uv run pytest tests/integration/test_retrieval.py
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy import delete, update

from app.db.models import Chunk, Fuente
from app.db.session import get_session_factory
from app.domain.lcsp_parser import LcspChunk, parse_lcsp
from app.services.ingest import ingest_chunks
from app.services.retrieval import hybrid_search
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


async def _ingest_fixture() -> list[LcspChunk]:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    async with get_session_factory()() as session:
        await ingest_chunks(session, chunks, FakeLLMClient())
    return chunks


async def test_direct_article_question_puts_article_107_first() -> None:
    await _ingest_fixture()
    llm = FakeLLMClient()

    async with get_session_factory()() as session:
        result = await hybrid_search(session, llm, "¿Qué dice el artículo 107?")

    assert result.chunks, "the article named in the question must be retrieved"
    assert result.chunks[0].articulo == "107"
    assert "direct" in result.chunks[0].branches
    assert result.best_score is not None


async def test_hybrid_query_ranks_lexical_match_first_with_pinned_rerank() -> None:
    chunks = await _ingest_fixture()
    # Pin the reranker: article 107's text must win over article 159's.
    llm = FakeLLMClient(
        rerank_scores={chunk.texto: (0.9 if chunk.articulo == "107" else 0.1) for chunk in chunks}
    )

    async with get_session_factory()() as session:
        result = await hybrid_search(session, llm, "garantía definitiva", top_k=2)

    assert result.chunks[0].articulo == "107"
    assert len(result.chunks) <= 2
    assert result.best_score == pytest.approx(0.9)


async def test_retrieved_chunks_expose_parser_metadata_and_branches() -> None:
    await _ingest_fixture()
    llm = FakeLLMClient()

    async with get_session_factory()() as session:
        result = await hybrid_search(session, llm, "¿Qué dice el artículo 159?")

    chunk = result.chunks[0]
    assert chunk.articulo == "159"
    assert chunk.apartado is None
    assert "Artículo 159" in chunk.titulo
    assert chunk.url.startswith("https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902")
    assert chunk.texto.startswith("Artículo 159")
    assert chunk.id > 0
    assert chunk.branches


async def test_a_null_embedding_does_not_break_the_search() -> None:
    await _ingest_fixture()
    async with get_session_factory()() as session:
        await session.execute(update(Chunk).values(embedding=None).where(Chunk.articulo == "159"))
        await session.commit()
    llm = FakeLLMClient()

    async with get_session_factory()() as session:
        result = await hybrid_search(session, llm, "¿Qué dice el artículo 107?")

    assert result.chunks[0].articulo == "107"
    # The NULL-embedding chunk may still surface through the lexical branch,
    # but never through the vector branch.
    assert all("vector" not in chunk.branches for chunk in result.chunks if chunk.articulo == "159")


async def test_two_search_runs_return_the_same_order() -> None:
    await _ingest_fixture()
    llm = FakeLLMClient()

    async with get_session_factory()() as session:
        first = await hybrid_search(session, llm, "¿Qué dice el artículo 107?")
        second = await hybrid_search(session, llm, "¿Qué dice el artículo 107?")

    assert [chunk.id for chunk in first.chunks] == [chunk.id for chunk in second.chunks]
