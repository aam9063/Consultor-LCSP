from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import dispose_engine, get_engine

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    engine = get_engine()
    yield engine
    await dispose_engine()


async def test_pgvector_extension_is_installed(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )

    assert result.scalar_one() == "vector"
