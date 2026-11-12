import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.db import session as session_module


@pytest.fixture(autouse=True)
def reset_engine() -> None:
    session_module.reset_for_tests()


def test_concurrent_initialisation_builds_a_single_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creation_calls: list[str] = []

    def slow_create_engine(url: str, **_: Any) -> object:
        creation_calls.append(url)
        time.sleep(0.05)
        return object()

    monkeypatch.setattr(session_module, "create_async_engine", slow_create_engine)

    def build_factory(_: int) -> object:
        return session_module.get_session_factory()

    with ThreadPoolExecutor(max_workers=4) as pool:
        factories = list(pool.map(build_factory, range(4)))

    assert len(creation_calls) == 1
    assert all(factory is factories[0] for factory in factories)


def test_reset_for_tests_discards_the_cached_factory() -> None:
    first = session_module.get_session_factory()
    session_module.reset_for_tests()
    second = session_module.get_session_factory()

    assert second is not first
