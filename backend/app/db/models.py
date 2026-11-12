"""ORM models for the LCSP ingestion (CL-02, BRIEF section 8).

`fuente` keeps one row per imported consolidated norm; `chunk` keeps one
row per retrieval chunk. `tsv` is a generated column so the Spanish
full-text vector is maintained by Postgres itself, and the unique index on
(`fuente_id`, `articulo`, `apartado`) makes re-ingestion idempotent (S9).
"""

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Fuente(Base):
    """An imported consolidated norm (e.g. the LCSP)."""

    __tablename__ = "fuente"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    boe_id: Mapped[str] = mapped_column(String(64), unique=True)
    fecha_version: Mapped[date]
    importado_en: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )


class Chunk(Base):
    """One retrieval chunk of the LCSP with its search vectors."""

    __tablename__ = "chunk"
    __table_args__ = (
        Index(
            "uq_chunk_fuente_articulo_apartado",
            "fuente_id",
            "articulo",
            text("coalesce(apartado, '')"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fuente_id: Mapped[int] = mapped_column(ForeignKey("fuente.id"))
    articulo: Mapped[str] = mapped_column(String(64))
    apartado: Mapped[str | None] = mapped_column(String(32))
    titulo: Mapped[str] = mapped_column(Text)
    ruta: Mapped[list[str]] = mapped_column(JSONB)
    texto: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('spanish_unaccent'::regconfig, texto)", persisted=True)
    )
    embedding: Mapped[Vector | None] = mapped_column(Vector(4096))
