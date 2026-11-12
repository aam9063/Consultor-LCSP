"""fuente and chunk tables for the LCSP ingestion

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fuente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("boe_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("fecha_version", sa.Date(), nullable=False),
        sa.Column(
            "importado_en",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fuente_id",
            sa.Integer(),
            sa.ForeignKey("fuente.id"),
            nullable=False,
        ),
        sa.Column("articulo", sa.String(length=64), nullable=False),
        sa.Column("apartado", sa.String(length=32), nullable=True),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("ruta", JSONB, nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('spanish', texto)", persisted=True),
            nullable=True,
        ),
        sa.Column("embedding", Vector(4096), nullable=True),
    )
    # Idempotency key for re-ingestion (S9): apartado NULL means
    # "whole article", so it is folded to '' for uniqueness.
    op.create_index(
        "uq_chunk_fuente_articulo_apartado",
        "chunk",
        ["fuente_id", "articulo", sa.text("coalesce(apartado, '')")],
        unique=True,
    )
    op.create_index(
        "ix_chunk_tsv",
        "chunk",
        ["tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_tsv", table_name="chunk")
    op.drop_index("uq_chunk_fuente_articulo_apartado", table_name="chunk")
    op.drop_table("chunk")
    op.drop_table("fuente")
