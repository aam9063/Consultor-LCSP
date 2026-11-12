"""User feedback endpoints (S8, S4): store and list votes with typed errors.

`POST /feedback` stores one self-contained vote per `pregunta + respuesta`
fingerprint: re-posting the same pair updates the stored vote and answers
`actualizado: true`. `GET /feedback` lists the stored votes, most recent
first, capped at 200 items (documented contract). Every predictable input
problem is a typed 422 with the project envelope `{"error": {"code",
"message"}}`, never a bare validation dump or a 500.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback
from app.db.session import get_session
from app.services.feedback import (
    CitaInvalidaError,
    VotoInvalidoError,
    normalize_citas,
    normalize_voto,
    save_feedback,
)

router = APIRouter(tags=["feedback"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# GET /feedback page size: default 50, hard cap 200 (documented contract).
FEEDBACK_DEFAULT_LIMIT = 50
FEEDBACK_MAX_LIMIT = 200


class FeedbackRequest(BaseModel):
    # Every field is optional at the pydantic level so the router can reject
    # each problem with the typed envelope instead of FastAPI's bare dump.
    pregunta: str | None = None
    respuesta: str | None = None
    citas: list[dict[str, Any]] = Field(default_factory=list)
    modelo: str | None = None
    voto: int | float | str | None = None
    comentario: str | None = None


class FeedbackItem(BaseModel):
    id: int
    pregunta: str
    respuesta: str
    citas: list[dict[str, Any]]
    modelo: str
    voto: int
    comentario: str | None
    creada_en: str
    actualizada_en: str


def _error(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": code, "message": message}})


@router.post("/feedback")
async def create_feedback(body: FeedbackRequest, session: SessionDep) -> JSONResponse:
    """Store or update a vote; 201 with `{id, voto, actualizado, creada_en, actualizada_en}`."""
    pregunta = (body.pregunta or "").strip()
    if not pregunta:
        return _error("pregunta_ausente", "Falta el texto de la pregunta en el campo 'pregunta'.")
    respuesta = (body.respuesta or "").strip()
    if not respuesta:
        return _error(
            "respuesta_ausente", "Falta el texto de la respuesta en el campo 'respuesta'."
        )
    modelo = (body.modelo or "").strip()
    if not modelo:
        return _error("modelo_ausente", "Falta el modelo en el campo 'modelo'.")
    try:
        voto = normalize_voto(body.voto)
    except VotoInvalidoError as exc:
        return _error("voto_invalido", str(exc))
    try:
        citas = normalize_citas(body.citas)
    except CitaInvalidaError as exc:
        return _error("cita_invalida", str(exc))

    result = await save_feedback(
        session,
        pregunta=pregunta,
        respuesta=respuesta,
        citas=citas,
        modelo=modelo,
        voto=voto,
        comentario=body.comentario,
    )
    return JSONResponse(
        status_code=201,
        content={
            "id": result.id,
            "voto": result.voto,
            "actualizado": result.actualizado,
            "creada_en": result.creada_en.isoformat(),
            "actualizada_en": result.actualizada_en.isoformat(),
        },
    )


@router.get("/feedback", response_model=list[FeedbackItem])
async def list_feedback(
    session: SessionDep,
    limit: int = Query(default=FEEDBACK_DEFAULT_LIMIT, ge=1),
) -> list[FeedbackItem]:
    """List the stored votes, most recent first, capped at `FEEDBACK_MAX_LIMIT`."""
    rows = (
        (
            await session.execute(
                select(Feedback)
                .order_by(Feedback.creada_en.desc(), Feedback.id.desc())
                .limit(min(limit, FEEDBACK_MAX_LIMIT))
            )
        )
        .scalars()
        .all()
    )
    return [
        FeedbackItem(
            id=row.id,
            pregunta=row.pregunta,
            respuesta=row.respuesta,
            citas=row.citas,
            modelo=row.modelo,
            voto=row.voto,
            comentario=row.comentario,
            creada_en=row.creada_en.isoformat(),
            actualizada_en=row.actualizada_en.isoformat(),
        )
        for row in rows
    ]
