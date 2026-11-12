"""User feedback persistence (S8, S1-S3): one self-contained row per vote.

The BRIEF (§6) forbids persisting the consultation history, so the vote is
stored as a single row with no session and no user (S2). Idempotency (S3):
the fingerprint (sha256 hex) of the stripped `pregunta + respuesta` is the
key, so re-evaluating the same answer updates the existing vote instead of
accumulating rows. Validation helpers are pure and unit-testable; the save
function owns the transaction, like the rest of the services.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback


class VotoInvalidoError(ValueError):
    """The vote is not exactly `1` or `-1`."""


class CitaInvalidaError(ValueError):
    """A citation is not `{"articulo": str, "apartado": str | None}`."""


def huella_de(pregunta: str, respuesta: str) -> str:
    """Stable sha256 hex fingerprint of the question plus the answer (S3)."""
    return hashlib.sha256(f"{pregunta}{respuesta}".encode()).hexdigest()


def normalize_voto(value: int | float | str | None) -> int:
    """Restrict the vote to exactly the integers `1` and `-1`.

    Booleans, floats (even `1.0`), numeric strings and `None` are all
    rejected: the API contract says `voto: 1 | -1`, nothing else.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise VotoInvalidoError(f"'voto' debe ser el entero 1 o -1, no {value!r}.")
    if value not in (1, -1):
        raise VotoInvalidoError(f"'voto' debe ser 1 o -1, no {value}.")
    return value


def normalize_citas(value: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    """Validate the citation shape: `{"articulo": str, "apartado": str | None}`.

    An empty list is valid: a vote on an abstention carries no citations.
    Everything else (missing or empty `articulo`, non-text `apartado`,
    unknown keys, non-object entries) is rejected with the position in the
    message so the client can locate the offending citation.
    """
    citas: list[dict[str, str | None]] = []
    for position, cita in enumerate(value, start=1):
        if not isinstance(cita, dict):
            raise CitaInvalidaError(
                f"La cita {position} debe ser un objeto con 'articulo' y opcionalmente 'apartado'."
            )
        unknown = set(cita) - {"articulo", "apartado"}
        if unknown or "articulo" not in cita:
            raise CitaInvalidaError(
                f"La cita {position} debe tener solo 'articulo' y opcionalmente 'apartado'."
            )
        articulo = cita["articulo"]
        apartado = cita.get("apartado")
        if not isinstance(articulo, str) or not articulo.strip():
            raise CitaInvalidaError(f"La cita {position} necesita un 'articulo' no vacío.")
        if apartado is not None and (not isinstance(apartado, str) or not apartado.strip()):
            raise CitaInvalidaError(f"El 'apartado' de la cita {position} debe ser texto o null.")
        citas.append({"articulo": articulo, "apartado": apartado})
    return citas


@dataclass(frozen=True, slots=True)
class FeedbackResult:
    """The outcome of storing one vote, as the API reports it."""

    id: int
    voto: int
    actualizado: bool
    creada_en: datetime
    actualizada_en: datetime


async def save_feedback(
    session: AsyncSession,
    *,
    pregunta: str,
    respuesta: str,
    citas: list[dict[str, str | None]],
    modelo: str,
    voto: int,
    comentario: str | None,
) -> FeedbackResult:
    """Create the vote row, or update it when the fingerprint already exists."""
    huella = huella_de(pregunta, respuesta)
    existing = await session.scalar(select(Feedback).where(Feedback.huella == huella))
    if existing is None:
        row = Feedback(
            huella=huella,
            pregunta=pregunta,
            respuesta=respuesta,
            citas=citas,
            modelo=modelo,
            voto=voto,
            comentario=comentario,
        )
        session.add(row)
        # The flush makes the server defaults (`now()`) come back with the row.
        await session.flush()
        result = FeedbackResult(
            id=row.id,
            voto=row.voto,
            actualizado=False,
            creada_en=row.creada_en,
            actualizada_en=row.actualizada_en,
        )
        await session.commit()
        return result
    existing.voto = voto
    existing.comentario = comentario
    existing.actualizada_en = func.now()
    await session.flush()
    await session.refresh(existing)
    await session.commit()
    return FeedbackResult(
        id=existing.id,
        voto=existing.voto,
        actualizado=True,
        creada_en=existing.creada_en,
        actualizada_en=existing.actualizada_en,
    )
