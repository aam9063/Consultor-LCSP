"""Radar review service (S7-02, S3/S4).

Takes the ficha Radar pushes, composes the labelled review text and runs it
through the EXISTING clause-review engine (`services.clauses.review_clause`):
retrieval, generation, citation validation and the abstention path are all
reused, not duplicated. The composed text is reviewed in one generation pass
so a request costs one pass, exactly like a hand-pasted clause (the engine's
bounded citation retry stays untouched). Every accepted aviso is returned
together with the origin field its literal quote came from (S4).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient
from app.domain.clauses import ClauseWarning, InvalidClauseWarning
from app.domain.radar_ficha import (
    OriginField,
    RadarFichaInput,
    origin_field_of_quote,
    validate_radar_ficha,
)
from app.services.clauses import ReviewResult, review_clause
from app.services.retrieval import RetrievedChunk

__all__ = ["RadarReviewResult", "review_radar_ficha"]


@dataclass(frozen=True, slots=True)
class RadarReviewResult:
    """The review of one pushed ficha, with each aviso's origin field."""

    licitacion_id: int
    expediente: str | None
    avisos: tuple[tuple[ClauseWarning, OriginField | None], ...]
    avisos_invalidos: tuple[InvalidClauseWarning, ...]
    sin_observaciones: bool
    observaciones: str | None
    chunks: tuple[RetrievedChunk, ...]
    model_called: bool
    model: str


async def review_radar_ficha(
    session: AsyncSession,
    llm: LLMClient,
    ficha: RadarFichaInput,
    *,
    top_k: int = 6,
) -> RadarReviewResult:
    """Contrast the pushed ficha against the LCSP with the clause engine.

    The ficha is validated first, so `ficha_sin_datos` and
    `ficha_demasiado_larga` surface before any retrieval or generation call.
    """
    validada = validate_radar_ficha(ficha)
    result: ReviewResult = await review_clause(session, llm, validada.texto, top_k=top_k)
    avisos: list[tuple[ClauseWarning, OriginField | None]] = [
        (aviso, origin_field_of_quote(validada.texto, aviso.cita_de_la_clausula))
        for aviso in result.avisos
    ]
    return RadarReviewResult(
        licitacion_id=validada.licitacion_id,
        expediente=validada.expediente,
        avisos=tuple(avisos),
        avisos_invalidos=result.avisos_invalidos,
        sin_observaciones=result.sin_observaciones,
        observaciones=result.observaciones,
        chunks=result.chunks,
        model_called=result.model_called,
        model=result.model,
    )
