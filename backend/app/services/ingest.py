"""Idempotent ingestion of parsed LCSP chunks into Postgres (CL-03, S1/S9).

`ingest_chunks` takes parsed `LcspChunk`s, an `LLMClient` port and an async
session; it creates or updates the `Fuente` row and writes only the chunks
that are new or changed, embedding just those. Running it twice over the
same file leaves the chunk count unchanged and performs zero embed calls
(AC-03 / S9).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient
from app.db.models import Chunk, Fuente
from app.domain.lcsp_parser import LcspChunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Counts of what one ingestion run did, for CLI and test assertions."""

    inserted: int
    updated: int
    skipped: int
    embedded: int


def _key(chunk: LcspChunk) -> tuple[str, str]:
    # Mirrors the unique expression index on (fuente_id, articulo, coalesce(apartado,'')).
    return (chunk.articulo, chunk.apartado or "")


async def ingest_chunks(
    session: AsyncSession,
    chunks: Sequence[LcspChunk],
    llm: LLMClient,
    *,
    fuente_nombre: str = "LCSP",
) -> IngestResult:
    """Ingest parsed chunks idempotently; embed only new or changed chunks."""
    if not chunks:
        return IngestResult(inserted=0, updated=0, skipped=0, embedded=0)

    first = chunks[0]
    if not first.fecha_version:
        raise ValueError("chunk has no consolidated version date; cannot record Fuente")
    fecha_version = date.fromisoformat(first.fecha_version)

    fuente_result = await session.execute(select(Fuente).where(Fuente.boe_id == first.boe_id))
    fuente = fuente_result.scalar_one_or_none()
    if fuente is None:
        fuente = Fuente(nombre=fuente_nombre, boe_id=first.boe_id, fecha_version=fecha_version)
        session.add(fuente)
        await session.flush()
    elif fuente.fecha_version != fecha_version:
        fuente.fecha_version = fecha_version

    existing = await session.execute(select(Chunk).where(Chunk.fuente_id == fuente.id))
    # Keys are (articulo, apartado-or-"") to match the unique index.
    existing_by_key: dict[tuple[str, str], Chunk] = {}
    for row in existing.scalars():
        existing_by_key[(row.articulo, row.apartado or "")] = row

    to_insert: list[LcspChunk] = []
    to_update: list[tuple[Chunk, LcspChunk]] = []
    skipped = 0
    for chunk in chunks:
        current = existing_by_key.get(_key(chunk))
        if current is None:
            to_insert.append(chunk)
        elif current.texto != chunk.texto:
            to_update.append((current, chunk))
        else:
            skipped += 1

    texts = [chunk.texto for chunk in to_insert] + [parsed.texto for _, parsed in to_update]
    vectors = await llm.embed(texts) if texts else []

    index = 0
    for chunk in to_insert:
        session.add(
            Chunk(
                fuente_id=fuente.id,
                articulo=chunk.articulo,
                apartado=chunk.apartado,
                titulo=chunk.titulo,
                ruta=list(chunk.ruta),
                texto=chunk.texto,
                url=chunk.url,
                embedding=cast("Any", vectors[index]),
            )
        )
        index += 1
    for row, chunk in to_update:
        row.titulo = chunk.titulo
        row.ruta = list(chunk.ruta)
        row.texto = chunk.texto
        row.url = chunk.url
        row.embedding = cast("Any", vectors[index])
        index += 1

    await session.commit()
    result = IngestResult(
        inserted=len(to_insert), updated=len(to_update), skipped=skipped, embedded=len(texts)
    )
    logger.info(
        "ingested fuente=%s boe_id=%s inserted=%d updated=%d skipped=%d embedded=%d",
        fuente_nombre,
        first.boe_id,
        result.inserted,
        result.updated,
        result.skipped,
        result.embedded,
    )
    return result
