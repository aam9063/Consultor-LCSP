"""Integration tests for idempotent ingestion (CL-03, S1/S9, AC-03).

Run against the real Postgres 18 + pgvector container with the
`FakeLLMClient` (no network):

    DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp \
        uv run pytest tests/integration/test_ingest.py
"""

from collections.abc import AsyncGenerator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text

from app.db.models import Chunk, Fuente
from app.db.session import get_session_factory
from app.domain.lcsp_parser import LcspChunk, parse_lcsp
from app.services.ingest import IngestResult, ingest_chunks
from tests.fakes import FakeLLMClient

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "small_lcsp.xml"


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


async def _ingest(llm: FakeLLMClient, chunks: list[LcspChunk]) -> IngestResult:
    async with get_session_factory()() as session:
        return await ingest_chunks(session, chunks, llm)


async def _chunk_count() -> int:
    async with get_session_factory()() as session:
        result = await session.execute(select(func.count()).select_from(Chunk))
        return int(result.scalar_one())


async def test_ingesting_the_same_file_twice_changes_nothing() -> None:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    assert len(chunks) == 2
    llm = FakeLLMClient()

    first = await _ingest(llm, chunks)
    assert (first.inserted, first.updated, first.skipped, first.embedded) == (2, 0, 0, 2)
    assert await _chunk_count() == 2
    assert len(llm.calls) == 1  # one embed call for the initial 2 chunks

    second = await _ingest(llm, chunks)

    assert (second.inserted, second.updated, second.skipped, second.embedded) == (0, 0, 2, 0)
    assert await _chunk_count() == 2
    assert len(llm.calls) == 1  # unchanged chunks are never re-embedded


async def test_changing_one_chunk_updates_only_that_chunk() -> None:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    llm = FakeLLMClient()
    await _ingest(llm, chunks)

    changed = [replace(chunks[1], texto=chunks[1].texto + "\n1 ter. Párrafo añadido.")]
    updated_chunks = [chunks[0], *changed]
    result = await _ingest(llm, updated_chunks)

    assert (result.inserted, result.updated, result.skipped, result.embedded) == (0, 1, 1, 1)
    assert llm.calls[-1] == [changed[0].texto]  # only the changed chunk is embedded

    async with get_session_factory()() as session:
        rows = (await session.execute(select(Chunk))).scalars().all()
    by_articulo = {row.articulo: row for row in rows}
    assert by_articulo["2"].texto == changed[0].texto
    assert by_articulo["1"].texto == chunks[0].texto  # the untouched chunk keeps its text


async def test_ingested_chunks_carry_embeddings_and_metadata() -> None:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    llm = FakeLLMClient()

    await _ingest(llm, chunks)

    async with get_session_factory()() as session:
        fuente = (await session.execute(select(Fuente))).scalar_one()
        assert fuente.boe_id == "BOE-A-2017-12902"
        # Check dimensions where they matter: inside the pgvector column.
        count = await session.execute(
            text("SELECT count(*) FROM chunk WHERE vector_dims(embedding) = :dimensions"),
            {"dimensions": llm.dimensions},
        )
        rows = (await session.execute(select(Chunk))).scalars().all()
    assert count.scalar_one() == len(rows)
    assert all(row.embedding is not None for row in rows)
    assert all(row.fuente_id == fuente.id for row in rows)


async def test_service_reports_a_typed_result() -> None:
    chunks = parse_lcsp(FIXTURE.read_bytes())
    llm = FakeLLMClient()

    async with get_session_factory()() as session:
        result = await ingest_chunks(session, chunks, llm)

    assert isinstance(result, IngestResult)
    assert result.embedded == result.inserted + result.updated
