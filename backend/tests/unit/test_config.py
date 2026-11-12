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
    assert settings.rerank_threshold == pytest.approx(0.35)
    assert settings.retrieval_top_k == 6


def test_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAN_API_KEY", "sk-test")
    monkeypatch.setenv("NAN_CHAT_MODEL", "qwen3.6")

    settings = make_settings()

    assert settings.nan_api_key.get_secret_value() == "sk-test"
    assert settings.chat_model == "qwen3.6"
    assert "sk-test" not in repr(settings)
