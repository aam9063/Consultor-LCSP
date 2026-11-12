from typing import Any

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def _get(query: str) -> tuple[int, Any]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/feedback{query}")
    return response.status_code, response.json()


def _assert_typed_envelope(status: int, body: Any) -> None:
    # FastAPI's own validation envelope (`{"detail": [...]}`) must never leak:
    # every predictable input gets the project's {"error": {"code", "message"}}.
    assert status == 422, f"expected 422, got {status}"
    assert isinstance(body, dict), f"expected the project envelope, got {body}"
    error = body.get("error")
    assert isinstance(error, dict), f"expected the project envelope, got {body}"
    assert error.get("code") == "limite_invalido"
    assert isinstance(error.get("message"), str) and error["message"]


async def test_a_non_positive_limit_uses_the_typed_error_envelope() -> None:
    status, body = await _get("?limit=0")

    _assert_typed_envelope(status, body)


async def test_a_non_numeric_limit_uses_the_typed_error_envelope() -> None:
    status, body = await _get("?limit=abc")

    _assert_typed_envelope(status, body)
