import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.adapters.llm import MissingAPIKeyError, NanLLMClient
from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client_without_api_key(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    # No key in the environment: the real client must not be built silently.
    settings = Settings(_env_file=None, nan_api_key=SecretStr(""))  # type: ignore[call-arg]
    get_settings.cache_clear()
    monkeypatch.setattr("app.adapters.llm.get_settings", lambda: settings)
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_missing_api_key_returns_a_typed_error_not_a_500(
    client_without_api_key: AsyncClient,
) -> None:
    async with client_without_api_key as client:
        response = await client.get("/buscar", params={"q": "garantia definitiva"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "llm_not_configured",
            "message": "NAN_API_KEY is not configured; the LLM-backed endpoints are unavailable.",
        }
    }


def test_missing_api_key_error_is_the_typed_adapter_error() -> None:
    with pytest.raises(MissingAPIKeyError):
        NanLLMClient(
            Settings(_env_file=None, nan_api_key=SecretStr(""))  # type: ignore[call-arg]
        )
