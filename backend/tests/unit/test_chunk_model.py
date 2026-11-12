"""Unit tests for the `fuente` and `chunk` persistence models (CL-02).

The tests compile the table DDL against the PostgreSQL dialect without a
database, so they are pure unit tests and run in CI.
"""

from typing import cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, Table

from app.db.models import Chunk, Fuente


def _chunk_table() -> Table:
    return cast(Table, Chunk.__table__)


def _chunk_ddl() -> str:
    # CreateTable.compile is untyped in the SQLAlchemy 2 stubs even though
    # compile() is callable at runtime; documented per AGENTS.md section 10.
    return str(
        CreateTable(_chunk_table()).compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    )


def test_chunk_table_matches_brief_data_model() -> None:
    columns = {column.name for column in _chunk_table().columns}

    assert columns == {
        "id",
        "fuente_id",
        "articulo",
        "apartado",
        "titulo",
        "ruta",
        "texto",
        "url",
        "tsv",
        "embedding",
    }


def test_chunk_tsv_is_generated_with_the_unaccented_spanish_configuration() -> None:
    # 'spanish' alone stems 'garantía' and 'garantia' to different lexemes, so a
    # question typed without accents would never match the statute.
    assert (
        "GENERATED ALWAYS AS (to_tsvector('spanish_unaccent'::regconfig, texto)) STORED"
        in _chunk_ddl()
    )


def test_chunk_embedding_is_a_4096_dimension_vector() -> None:
    assert "VECTOR(4096)" in _chunk_ddl().upper()


def test_chunk_has_unique_key_for_ingest_idempotency() -> None:
    unique_indexes = [
        index
        for index in _chunk_table().indexes
        if index.unique and "fuente_id" in [column.name for column in index.columns]
    ]

    assert len(unique_indexes) == 1
    names = {column.name for column in unique_indexes[0].columns}
    assert {"fuente_id", "articulo"} <= names


def test_fuente_table_matches_brief_data_model() -> None:
    columns = {column.name for column in Fuente.__table__.columns}

    assert columns == {"id", "nombre", "boe_id", "fecha_version", "importado_en"}
    boe_id = Fuente.__table__.columns["boe_id"]
    assert boe_id.unique is True
