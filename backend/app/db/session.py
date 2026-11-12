import threading
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# The engine and its factory are process-wide singletons built on first use.
# The lock makes that first build atomic: two concurrent callers can never
# create two engines (and two connection pools) for the same URL.
_init_lock = threading.Lock()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_once() -> None:
    global _engine, _session_factory
    with _init_lock:
        if _session_factory is None:
            engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
            _engine = engine
            _session_factory = async_sessionmaker(engine, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    _build_once()
    engine = _engine
    if engine is None:  # pragma: no cover - guard for a broken invariant
        raise RuntimeError("Database engine was not initialised")
    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    _build_once()
    factory = _session_factory
    if factory is None:  # pragma: no cover - guard for a broken invariant
        raise RuntimeError("Session factory was not initialised")
    return factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def reset_for_tests() -> None:
    global _engine, _session_factory
    _engine = None
    _session_factory = None


async def dispose_engine() -> None:
    engine = _engine
    reset_for_tests()
    if engine is not None:
        await engine.dispose()
