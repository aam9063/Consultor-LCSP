"""Integration tests for POST/GET /feedback against real Postgres (S8, S7/FB-02).

    DATABASE_URL=postgresql+asyncpg://lcsp:lcsp@localhost:5433/lcsp \
        uv run pytest tests/integration/test_feedback.py
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Feedback
from app.db.session import get_session_factory
from app.main import create_app

pytestmark = pytest.mark.integration

BODY: dict[str, Any] = {
    "pregunta": "¿Cuál es la garantía definitiva?",
    "respuesta": "El art. 107 fija el 5% del precio final ofertado.",
    "citas": [{"articulo": "107", "apartado": None}],
    "modelo": "deepseek-v4-flash",
    "voto": -1,
    "comentario": None,
}


async def _cleanup() -> None:
    async with get_session_factory()() as session:
        await session.execute(delete(Feedback))
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_db() -> AsyncGenerator[None]:
    await _cleanup()
    yield
    await _cleanup()


async def _row_count() -> int:
    async with get_session_factory()() as session:
        return int(await session.scalar(select(func.count()).select_from(Feedback)) or 0)


def _app() -> FastAPI:
    return create_app()


# --- S3: idempotency — same pregunta + respuesta updates, never duplicates ----


async def test_first_vote_creates_and_second_updates_the_same_row() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        first = await client.post("/feedback", json=BODY)
        assert first.status_code == 201
        created = first.json()
        assert created["actualizado"] is False
        assert created["voto"] == -1
        assert datetime.fromisoformat(created["creada_en"])
        assert datetime.fromisoformat(created["actualizada_en"])
        assert await _row_count() == 1

        second = await client.post("/feedback", json={**BODY, "voto": 1, "comentario": "Ahora sí"})
        assert second.status_code == 201
        updated = second.json()
        assert updated["actualizado"] is True
        assert updated["id"] == created["id"]
        assert updated["voto"] == 1
        assert await _row_count() == 1

    async with get_session_factory()() as session:
        row = await session.scalar(select(Feedback))
        assert row is not None
        assert row.voto == 1
        assert row.comentario == "Ahora sí"
        assert row.actualizada_en >= row.creada_en


async def test_a_different_answer_creates_a_second_row() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        first = await client.post("/feedback", json=BODY)
        second = await client.post(
            "/feedback", json={**BODY, "respuesta": "Otra respuesta distinta"}
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["actualizado"] is False
    assert second.json()["id"] != first.json()["id"]
    assert await _row_count() == 2


# --- S4: invalid input is a typed 422 and writes nothing ----------------------


async def test_an_invalid_vote_returns_422_and_writes_nothing() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post("/feedback", json={**BODY, "voto": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "voto_invalido"
    assert await _row_count() == 0


async def test_a_malformed_citation_returns_422_and_writes_nothing() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post("/feedback", json={**BODY, "citas": [{"articulo": ""}]})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "cita_invalida"
    assert await _row_count() == 0


# --- S4: GET lists the stored votes, most recent first ------------------------


async def test_get_returns_the_votes_most_recent_first() -> None:
    ids: list[int] = []
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        for letter in "ABC":
            response = await client.post(
                "/feedback",
                json={**BODY, "pregunta": f"Pregunta {letter}", "respuesta": f"Respuesta {letter}"},
            )
            ids.append(response.json()["id"])

        listing = await client.get("/feedback")

    assert listing.status_code == 200
    items = listing.json()
    assert [item["id"] for item in items] == list(reversed(ids))
    assert items[0]["pregunta"] == "Pregunta C"
    assert items[0]["respuesta"] == "Respuesta C"
    assert items[0]["citas"] == [{"articulo": "107", "apartado": None}]
    assert items[0]["modelo"] == "deepseek-v4-flash"
    assert items[0]["voto"] == -1
    assert items[0]["comentario"] is None
    assert datetime.fromisoformat(items[0]["creada_en"])
    assert datetime.fromisoformat(items[0]["actualizada_en"])


async def test_get_caps_the_page_size_at_the_documented_limit() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        for letter in "ABC":
            await client.post(
                "/feedback",
                json={**BODY, "pregunta": f"Pregunta {letter}", "respuesta": f"Respuesta {letter}"},
            )
        capped = await client.get("/feedback", params={"limit": 2})
        over_cap = await client.get("/feedback", params={"limit": 10_000})

    assert len(capped.json()) == 2
    assert capped.json()[0]["pregunta"] == "Pregunta C"
    assert len(over_cap.json()) == 3, "the documented hard cap is 200 and there are only 3 rows"


# --- FB-01: the check constraint backs the vote validation at the DB level ----


async def test_the_database_rejects_votes_outside_1_and_minus_1() -> None:
    async with get_session_factory()() as session:
        session.add(
            Feedback(
                huella="huella-fuera-de-rango",
                pregunta="pregunta",
                respuesta="respuesta",
                citas=[],
                modelo="modelo",
                voto=2,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
