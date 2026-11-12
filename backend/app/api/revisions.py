"""Clause review endpoint (CL-06, BRIEF section 9): clause → typed warnings.

`POST /revisiones` runs retrieval plus review with validated citations.
A missing or oversized clause is a typed 422, never a bare validation dump;
predictable generation failures surface as typed error envelopes through the
global handlers in `app.main` (502 `llm_unavailable` / 503
`llm_not_configured`).
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
from app.services.clauses import review_clause

router = APIRouter(tags=["revisiones"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class RevisionRequest(BaseModel):
    clausula: str | None = None


class AvisoBody(BaseModel):
    tipo: str
    explicacion: str
    articulos_citados: list[CitationBody]
    cita_de_la_clausula: str


class AvisoInvalidoBody(BaseModel):
    tipo: str | None
    explicacion: str | None
    cita_de_la_clausula: str | None
    articulos_citados: list[str]
    motivos: list[str]


class RevisionResponse(BaseModel):
    clausula: str
    avisos: list[AvisoBody]
    avisos_invalidos: list[AvisoInvalidoBody]
    sin_observaciones: bool
    observaciones: str | None
    modelo: str
    chunks: list[ScoredChunkBody]


@router.post("/revisiones", response_model=RevisionResponse)
async def revisiones(body: RevisionRequest, session: SessionDep, llm: LLMDep) -> JSONResponse:
    """Review the clause and return its typed warnings, or no-basis text."""
    if body.clausula is None or not body.clausula.strip():
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "clausula_ausente",
                    "message": "Falta el texto de la cláusula en el campo 'clausula'.",
                }
            },
        )
    result = await review_clause(session, llm, body.clausula, top_k=get_settings().retrieval_top_k)
    return JSONResponse(
        content=RevisionResponse(
            clausula=result.clausula,
            avisos=[
                AvisoBody(
                    tipo=aviso.tipo,
                    explicacion=aviso.explicacion,
                    articulos_citados=[
                        CitationBody(articulo=citation.articulo, apartado=citation.apartado)
                        for citation in aviso.articulos_citados
                    ],
                    cita_de_la_clausula=aviso.cita_de_la_clausula,
                )
                for aviso in result.avisos
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
        ).model_dump()
    )
