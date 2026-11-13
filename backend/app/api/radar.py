"""Radar ficha review endpoint (S7-03, S1/S4/S5): Radar pushes its extraction.

`POST /revisiones/radar` runs the pushed fields through the clause-review
engine with origin-labelled sections. `ficha_sin_datos` and
`ficha_demasiado_larga` are typed 422s in the same envelope as
`/revisiones`; predictable generation failures surface as typed error
envelopes through the global handlers in `app.main` (502 `llm_unavailable` /
503 `llm_not_configured`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.answers import CitationBody
from app.api.deps import LLMDep
from app.api.retrieval import ScoredChunkBody, scored_body
from app.config import get_settings
from app.db.session import get_session
from app.domain.radar_ficha import RadarFichaError, RadarFichaInput
from app.services.radar import review_radar_ficha

router = APIRouter(tags=["revisiones"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class AvisoInvalidoBody(BaseModel):
    tipo: str | None
    explicacion: str | None
    cita_de_la_clausula: str | None
    articulos_citados: list[str]
    motivos: list[str]


class AvisoRadarBody(BaseModel):
    tipo: str
    explicacion: str
    articulos_citados: list[CitationBody]
    cita_de_la_clausula: str
    campo_origen: str | None


class RadarReviewResponse(BaseModel):
    licitacion_id: int
    expediente: str | None
    avisos: list[AvisoRadarBody]
    avisos_invalidos: list[AvisoInvalidoBody]
    sin_observaciones: bool
    observaciones: str | None
    modelo: str
    chunks: list[ScoredChunkBody]
    model_called: bool


@router.post("/revisiones/radar", response_model=RadarReviewResponse)
async def revisiones_radar(
    body: RadarFichaInput,
    session: SessionDep,
    llm: LLMDep,
) -> JSONResponse:
    """Review the pushed ficha and return its avisos with their origin field."""
    try:
        result = await review_radar_ficha(session, llm, body, top_k=get_settings().retrieval_top_k)
    except RadarFichaError as error:
        return JSONResponse(
            status_code=422, content={"error": {"code": error.motivo, "message": error.message}}
        )
    return JSONResponse(
        content=RadarReviewResponse(
            licitacion_id=result.licitacion_id,
            expediente=result.expediente,
            avisos=[
                AvisoRadarBody(
                    tipo=aviso.tipo,
                    explicacion=aviso.explicacion,
                    articulos_citados=[
                        CitationBody(articulo=citation.articulo, apartado=citation.apartado)
                        for citation in aviso.articulos_citados
                    ],
                    cita_de_la_clausula=aviso.cita_de_la_clausula,
                    campo_origen=origen,
                )
                for aviso, origen in result.avisos
            ],
            avisos_invalidos=[
                AvisoInvalidoBody(
                    tipo=aviso.tipo,
                    explicacion=aviso.explicacion,
                    cita_de_la_clausula=aviso.cita_de_la_clausula,
                    articulos_citados=list(aviso.articulos_citados),
                    motivos=list(aviso.motivos),
                )
                for aviso in result.avisos_invalidos
            ],
            sin_observaciones=result.sin_observaciones,
            observaciones=result.observaciones,
            modelo=result.model,
            chunks=[scored_body(chunk) for chunk in result.chunks],
            model_called=result.model_called,
        ).model_dump()
    )
