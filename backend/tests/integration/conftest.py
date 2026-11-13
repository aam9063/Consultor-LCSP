import os
from collections.abc import AsyncGenerator

import pytest

from app.config import get_settings

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Step 1 — resolve and guard the dedicated test database.
# ---------------------------------------------------------------------------
# Integration tests truncate the corpus tables to keep retrieval deterministic.
# If they run against the working database, every `pytest tests/integration`
# destroys the ingested statute and the embeddings already paid for, so they
# require an explicit dedicated database instead of falling back silently.
# Read through Settings, so the value can live in the local environment file as
# well as in the shell.
_TEST_DATABASE_URL = get_settings().database_url_test.strip()
if not _TEST_DATABASE_URL:
    pytest.exit(
        "Integration tests need a dedicated database: set DATABASE_URL_TEST "
        "(for example postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp_test) "
        "so they never wipe the working corpus.",
        returncode=2,
    )

# The tests must never point at the database the application works with: that is
# exactly how the ingested corpus gets destroyed. Checking presence is not
# enough, because a value that duplicates DATABASE_URL passes the first guard.
_WORKING_DATABASE_URL = get_settings().database_url.strip()
if _TEST_DATABASE_URL == _WORKING_DATABASE_URL:
    pytest.exit(
        "DATABASE_URL_TEST points at the working database. The integration "
        "suites truncate the corpus, so it must name a different database "
        "(for example .../lcsp_test).",
        returncode=2,
    )

# ---------------------------------------------------------------------------
# Step 2 — point the application at the test database.
# ---------------------------------------------------------------------------
# The environment wins over the local environment file, which is exactly what
# the application settings already do, so pointing DATABASE_URL at the test
# database is enough for every module that builds an engine later.
#
# The settings instance consulted by the step-1 guards was built BEFORE this
# reassignment and `get_settings()` is `@lru_cache`-decorated, so without
# invalidating the cache every later `get_settings()` keeps serving that stale
# instance with the working database URL. That is exactly how the integration
# suites once truncated the real ingested corpus: the routing silently stayed
# on the working database while the tests believed they ran against the test
# one. Clear the cache so the next call rebuilds Settings from the reassigned
# environment.
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
get_settings.cache_clear()

# Fail closed: read the routed URL back fresh and refuse to run at all if it
# does not name the dedicated test database. A future regression must destroy
# nothing silently — aborting the session is cheaper than truncating the
# working corpus again.
if get_settings().database_url.strip() != _TEST_DATABASE_URL:
    pytest.exit(
        "After reassigning DATABASE_URL the settings still resolve to a "
        "different database; the integration suites would run against "
        f"{get_settings().database_url!r} instead of the dedicated test "
        "database. Aborting so the working corpus is never truncated by "
        "mistake.",
        returncode=2,
    )

from app.db.session import dispose_engine  # noqa: E402  (after DATABASE_URL is fixed)


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests() -> AsyncGenerator[None]:
    """Each test runs in its own event loop, so the cached engine must not leak."""
    yield
    await dispose_engine()
