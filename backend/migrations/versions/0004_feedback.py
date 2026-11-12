"""feedback table for user votes (S8, FB-01)

One self-contained row per vote: the BRIEF (§6) forbids persisting the
consultation history, so no session or user is stored, only the valued
answer. `huella` (sha256 hex of `pregunta + respuesta`) is the idempotency
key: re-evaluating the same answer updates the row instead of adding a
duplicate (S3). The check constraint restricts `voto` to 1 or -1 at the
database level, not only in the API validation.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("huella", sa.String(length=64), nullable=False, unique=True),
        sa.Column("pregunta", sa.Text(), nullable=False),
        sa.Column("respuesta", sa.Text(), nullable=False),
        sa.Column("citas", JSONB, nullable=False),
        sa.Column("modelo", sa.String(length=200), nullable=False),
        sa.Column("voto", sa.SmallInteger(), nullable=False),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column(
            "creada_en",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "actualizada_en",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("voto IN (1, -1)", name="ck_feedback_voto"),
    )


def downgrade() -> None:
    op.drop_table("feedback")
