import sys

import pytest

from app.config import Settings, get_settings


def make_settings() -> Settings:
    # pydantic-settings accepts `_env_file` at runtime; the generated signature omits it.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_expose_the_stack_defaults() -> None:
    settings = make_settings()

    assert settings.nan_base_url == "https://api.nan.builders/v1"
    assert settings.chat_model == "deepseek-v4-flash"
    assert settings.embedding_model == "qwen3-embedding"
    assert settings.rerank_model == "rerank"
    assert settings.embedding_dimensions == 4096
    # Calibrated on real rerank scores: answerable questions >= 0.958,
    # out-of-law questions <= 0.757.
    assert settings.rerank_threshold == pytest.approx(0.85)
    assert settings.retrieval_top_k == 6


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAN_API_KEY", "sk-test")
    monkeypatch.setenv("NAN_CHAT_MODEL", "qwen3.6")

    settings = make_settings()

    assert settings.nan_api_key.get_secret_value() == "sk-test"
    assert settings.chat_model == "qwen3.6"
    assert "sk-test" not in repr(settings)


def test_the_test_database_url_is_part_of_the_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The integration conftest reads it through Settings so a value in the
    # local environment file counts, not only an exported variable.
    # CI exports the variable for the whole job, so the default has to be
    # asserted with it removed rather than assumed absent.
    monkeypatch.delenv("DATABASE_URL_TEST", raising=False)
    settings = make_settings()

    assert settings.database_url_test == ""


def test_the_test_database_url_can_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL_TEST", "postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp_test"
    )

    settings = make_settings()

    assert settings.database_url_test.endswith("/lcsp_test")


def test_integration_conftest_leaves_settings_pointing_at_the_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The integration conftest must leave the routed database on the test URL."""
    # Regression guard for the corpus-wiping bug: the conftest consulted the
    # (cached) settings before reassigning DATABASE_URL, so every later
    # get_settings() kept serving the working database and the integration
    # suites truncated the real corpus. Executing the real conftest module
    # must end with the application settings resolving to the test database.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://lcsp:lcsp@localhost:5432/lcsp")
    monkeypatch.setenv(
        "DATABASE_URL_TEST", "postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp_test"
    )

    # Reproduce the incident faithfully: start with the settings cache empty and
    # DATABASE_URL pointing at the working database, then execute the real
    # conftest module once. Its guard consults get_settings() (which caches)
    # before reassigning the environment — exactly as it runs in the suite.
    get_settings.cache_clear()
    sys.modules.pop("tests.integration.conftest", None)
    try:
        import tests.integration.conftest  # noqa: F401  (executed for its side effects)
    except pytest.exit.Exception as error:  # pragma: no cover - guards must pass
        pytest.fail(f"integration conftest exited under controlled env: {error}")

    try:
        assert get_settings().database_url.endswith("/lcsp_test"), (
            "integration conftest left get_settings() pointing away from the test database"
        )
    finally:
        # Do not leak the re-executed module or a poisoned settings cache into
        # the rest of the suite.
        sys.modules.pop("tests.integration.conftest", None)
        get_settings.cache_clear()
