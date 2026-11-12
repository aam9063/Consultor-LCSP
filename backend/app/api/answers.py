"""Consulta endpoint (CL-05, BRIEF section 9): question → cited answer or abstention.

`POST /consultas` runs retrieval plus generation with validated citations.
Predictable generation failures surface as typed error envelopes through
the global handlers in `app.main` (502 `llm_unavailable` / 503
`llm_not_configured`), never a bare 500.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import LLMDep
from app.api.retrieval import ScoredChunkBody, scored_body
from app.config import get_settings
from app.db.session import get_session
from app.services.answers import answer_question

router = APIRouter(tags=["consultas"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ConsultaRequest(BaseModel):
    pregunta: str = Field(min_length=1)


class CitationBody(BaseModel):
    articulo: str
    apartado: str | None


class ConsultaResponse(BaseModel):
    pregunta: str
    respuesta: str
    citas: list[CitationBody]
    abstencion: bool
    motivo_abstencion: str | None
    advertencia: str | None
    afirmaciones_no_respaldadas: list[str]
    modelo: str
    chunks: list[ScoredChunkBody]


@router.post("/consultas", response_model=ConsultaResponse)
async def consultas(body: ConsultaRequest, session: SessionDep, llm: LLMDep) -> ConsultaResponse:
    """Answer the question with citations, or abstain when there is no base."""
    result = await answer_question(
        session, llm, body.pregunta, top_k=get_settings().retrieval_top_k
    )
    return ConsultaResponse(
        pregunta=body.pregunta,
        respuesta=result.respuesta,
        citas=[
            CitationBody(articulo=citation.articulo, apartado=citation.apartado)
            for citation in result.citas
        ],
        abstencion=result.abstencion,
        motivo_abstencion=result.motivo_abstencion,
        advertencia=result.warning,
        afirmaciones_no_respaldadas=list(result.unsupported_claims),
        modelo=result.model,
        chunks=[scored_body(chunk) for chunk in result.chunks],
    )
