from collections.abc import AsyncGenerator

import pytest

from app.db.session import dispose_engine

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests() -> AsyncGenerator[None]:
    """Each test runs in its own event loop, so the cached engine must not leak."""
    yield
    await dispose_engine()
