from datetime import date

import pytest
from sqlalchemy import delete, func, select, text

from app.db.models import Chunk, Fuente
from app.db.session import get_session_factory

pytestmark = pytest.mark.integration

ACCENTED_TEXT = (
    "Artículo 107. Exigencia de la garantía definitiva.\n"
    "1. Aceptada la adjudicación, el contratista deberá constituir una garantía definitiva "
    "del 5 por ciento del importe de adjudicación."
)


async def _cleanup() -> None:
    async with get_session_factory()() as session:
        await session.execute(delete(Chunk))
        await session.execute(delete(Fuente))
        await session.commit()


async def _store_accented_chunk() -> None:
    async with get_session_factory()() as session:
        fuente = Fuente(nombre="LCSP", boe_id="BOE-A-2017-12902", fecha_version=date(2018, 3, 9))
        session.add(fuente)
        await session.flush()
        session.add(
            Chunk(
                fuente_id=fuente.id,
                articulo="107",
                apartado=None,
                titulo="Artículo 107. Exigencia de la garantía definitiva.",
                ruta=["LIBRO PRIMERO", "TÍTULO IV"],
                texto=ACCENTED_TEXT,
                url="https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-19",
            )
        )
        await session.commit()


async def test_unaccented_query_matches_accented_statutory_text() -> None:
    await _cleanup()
    await _store_accented_chunk()
    try:
        async with get_session_factory()() as session:
            found = (
                (
                    await session.execute(
                        select(Chunk.id).where(
                            Chunk.tsv.op("@@")(
                                func.plainto_tsquery("spanish_unaccent", "garantia definitiva")
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await _cleanup()

    assert found, "an unaccented query must match accented statutory text"


async def test_spanish_unaccent_configuration_is_installed() -> None:
    async with get_session_factory()() as session:
        installed = await session.scalar(
            text("SELECT count(*) FROM pg_ts_config WHERE cfgname = 'spanish_unaccent'")
        )

    assert installed == 1
