import pytest

from app.config import Settings


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


def test_the_test_database_url_is_part_of_the_configuration() -> None:
    # The integration conftest reads it through Settings so a value in the
    # local environment file counts, not only an exported variable.
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
