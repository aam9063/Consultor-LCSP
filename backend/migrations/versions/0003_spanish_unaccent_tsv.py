"""spanish_unaccent text search configuration for chunk.tsv

The stock `spanish` configuration stems accented and unaccented words to
different lexemes ('garantía' -> 'garant', 'garantia' -> 'garanti'), so a
question typed without accents never matches the statute. The new
configuration keeps the Spanish stemmer and adds `unaccent` to the token
mapping, so both sides normalise the same way.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOKEN_TYPES = "asciiword, asciihword, hword_asciipart, word, hword, hword_part"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'spanish_unaccent') THEN
                CREATE TEXT SEARCH CONFIGURATION spanish_unaccent (COPY = spanish);
                ALTER TEXT SEARCH CONFIGURATION spanish_unaccent
                    ALTER MAPPING FOR """
        + _TOKEN_TYPES
        + """
                    WITH unaccent, spanish_stem;
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_chunk_tsv")
    op.execute("ALTER TABLE chunk DROP COLUMN tsv")
    op.execute(
        "ALTER TABLE chunk ADD COLUMN tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('spanish_unaccent'::regconfig, texto)) STORED"
    )
    op.execute("CREATE INDEX ix_chunk_tsv ON chunk USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_tsv")
    op.execute("ALTER TABLE chunk DROP COLUMN tsv")
    op.execute(
        "ALTER TABLE chunk ADD COLUMN tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('spanish'::regconfig, texto)) STORED"
    )
    op.execute("CREATE INDEX ix_chunk_tsv ON chunk USING gin (tsv)")
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS spanish_unaccent")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
