"""Clause-review service (CL-06, S4/S14, AC-08).

Flow (BRIEF §5 S4): retrieve the relevant articles for the clause with the
same `hybrid_search` as the answers service; when nothing was retrieved or
the best rerank score is under the configurable threshold the generation
model is **never** called and the result carries the exact text
`sin observaciones fundadas`. Otherwise the warnings come back as JSON
(`avisos`) and are validated in code with the domain rules (AC-08): every
cited article must be retrieved and every aviso must quote the clause
fragment it is about. Warnings citing non-retrieved articles cause exactly
one retry with validation feedback; if the invented citation persists, the
offending warnings are dropped and reported explicitly — a citation that
does not exist is never shown.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient, LLMError
from app.config import get_settings
from app.domain.citations import build_chunk_index
from app.domain.clauses import (
    VALID_TIPOS,
    ClauseReviewReport,
    ClauseWarning,
    InvalidClauseWarning,
    validate_clause_length,
    validate_clause_warnings,
)
from app.services.retrieval import RetrievedChunk, hybrid_search

logger = logging.getLogger(__name__)

SIN_OBSERVACIONES_FUNDADAS = "sin observaciones fundadas"

SYSTEM_PROMPT = (
    "Eres un revisor jurídico especializado en la Ley 9/2017 (LCSP). "
    "Analiza la cláusula suministrada ÚNICAMENTE con el contexto recuperado; "
    "no uses conocimiento externo. Devuelve una lista de avisos; el tipo de "
    "cada aviso es exactamente uno de: posible_incumplimiento, ambiguedad, ok. "
    "Cada aviso cita los artículos que lo respaldan con el formato [art. X] o "
    "[art. X.Y], donde Y es el apartado, y reproduce literalmente en "
    "cita_de_la_clausula el fragmento de la cláusula al que se refiere. "
    "Si el contexto no basta para observarla, devuelve una lista vacía. "
    "La revisión no constituye asesoramiento jurídico."
)

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "avisos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": list(VALID_TIPOS)},
                    "explicacion": {"type": "string"},
                    "articulos_citados": {"type": "array", "items": {"type": "string"}},
                    "cita_de_la_clausula": {"type": "string"},
                },
                "required": ["tipo", "explicacion", "articulos_citados", "cita_de_la_clausula"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["avisos"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """The final review of one clause, with its validation outcome."""

    clausula: str
    avisos: tuple[ClauseWarning, ...]
    avisos_invalidos: tuple[InvalidClauseWarning, ...]
    sin_observaciones: bool
    observaciones: str | None
    model: str
    chunks: tuple[RetrievedChunk, ...]
    model_called: bool


async def review_clause(
    session: AsyncSession,
    llm: LLMClient,
    clause: str,
    *,
    top_k: int = 6,
) -> ReviewResult:
    """Review `clause` from the retrieved context, or abstain with no basis."""
    settings = get_settings()
    validate_clause_length(clause)
    retrieval = await hybrid_search(session, llm, clause, top_k=top_k)
    if (
        not retrieval.chunks
        or retrieval.best_score is None
        or retrieval.best_score < settings.rerank_threshold
    ):
        logger.info(
            "clause review abstained clause_chars=%d retrieved=%d best_score=%s",
            len(clause),
            len(retrieval.chunks),
            retrieval.best_score,
        )
        return _no_basis(clause, settings.chat_model, tuple(retrieval.chunks))

    index = build_chunk_index((chunk.articulo, chunk.apartado) for chunk in retrieval.chunks)
    base_prompt = _user_prompt(clause, retrieval.chunks)
    avisos = _extract_avisos(
        await llm.generate_json(system=SYSTEM_PROMPT, user=base_prompt, schema=REVIEW_SCHEMA)
    )
    report = validate_clause_warnings(avisos, clause, index)
    if report.needs_citation_retry:
        # Exactly one retry, with the validation errors appended to the prompt.
        retry_prompt = f"{base_prompt}\n\n{_citation_feedback(report)}"
        avisos = _extract_avisos(
            await llm.generate_json(system=SYSTEM_PROMPT, user=retry_prompt, schema=REVIEW_SCHEMA)
        )
        report = validate_clause_warnings(avisos, clause, index)

    logger.info(
        "clause reviewed clause_chars=%d valid_warnings=%d invalid_warnings=%d",
        len(clause),
        len(report.warnings),
        len(report.invalid),
    )
    return ReviewResult(
        clausula=clause,
        avisos=report.warnings,
        avisos_invalidos=report.invalid,
        sin_observaciones=False,
        observaciones=None,
        model=settings.chat_model,
        chunks=tuple(retrieval.chunks),
        model_called=True,
    )


def _no_basis(clause: str, model: str, chunks: tuple[RetrievedChunk, ...]) -> ReviewResult:
    return ReviewResult(
        clausula=clause,
        avisos=(),
        avisos_invalidos=(),
        sin_observaciones=True,
        observaciones=SIN_OBSERVACIONES_FUNDADAS,
        model=model,
        chunks=chunks,
        model_called=False,
    )


def _user_prompt(clause: str, chunks: Iterable[RetrievedChunk]) -> str:
    context = "\n\n".join(
        f"[{chunk.articulo}{'.' + chunk.apartado if chunk.apartado else ''}] "
        f"{chunk.titulo}\n{chunk.texto}"
        for chunk in chunks
    )
    return (
        f"Cláusula a revisar:\n{clause}\n\n"
        f"Contexto recuperado (única fuente permitida):\n{context}\n\n"
        "Responde en JSON con la clave: avisos."
    )


def _extract_avisos(payload: dict[str, Any]) -> list[Any]:
    """Pull the `avisos` list out of the payload with typed errors.

    A payload with a missing or mistyped `avisos` key is a predictable
    generation failure and raises a typed `LLMError`, never a bare exception.
    """
    avisos = payload.get("avisos")
    if not isinstance(avisos, list):
        raise LLMError("generation returned a review payload with a missing or mistyped avisos")
    return avisos


def _citation_feedback(report: ClauseReviewReport) -> str:
    labels = ", ".join(report.unbacked_labels)
    return (
        f"Error de validación: los avisos citan {labels}, que no corresponden a artículos "
        "del contexto recuperado. Reescribe esos avisos citando solo artículos presentes "
        "en el contexto con el formato [art. X] o [art. X.Y], o elimínalos de la lista."
    )
