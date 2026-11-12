import os
from collections.abc import AsyncGenerator

import pytest

pytestmark = pytest.mark.integration

# Integration tests truncate the corpus tables to keep retrieval deterministic.
# If they run against the working database, every `pytest tests/integration`
# destroys the ingested statute and the embeddings already paid for, so they
# require an explicit dedicated database instead of falling back silently.
_TEST_DATABASE_URL = os.environ.get("DATABASE_URL_TEST", "").strip()
if not _TEST_DATABASE_URL:
    pytest.exit(
        "Integration tests need a dedicated database: set DATABASE_URL_TEST "
        "(for example postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp_test) "
        "so they never wipe the working corpus.",
        returncode=2,
    )

# The environment wins over the local environment file, which is exactly what
# the application settings already do, so pointing DATABASE_URL at the test
# database is enough for every module that builds an engine later.
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

from app.db.session import dispose_engine  # noqa: E402  (after the guard on purpose)


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests() -> AsyncGenerator[None]:
    """Each test runs in its own event loop, so the cached engine must not leak."""
    yield
    await dispose_engine()
