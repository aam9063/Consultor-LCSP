"""Answering service: generation with validated citations and abstention (CL-05, S3/S12/S13).

Flow (BRIEF §5 S3): abstain first — when nothing was retrieved or the best
rerank score is under the configurable threshold, the generation model is
never called and the exact abstention message is returned (AC-07).
Otherwise the retrieved chunks become the only context, the answer comes
back as JSON (`respuesta`, `citas`, `abstencion`, `motivo_abstencion`)
and every `[art. X]` / `[art. X.Y]` citation is validated in code against
the retrieved chunks (AC-06): an invented citation causes exactly one
retry with the validation errors appended to the prompt; if it persists,
the answer is kept, the offending claims are marked unsupported and a
warning is exposed — never silently dropped.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient, LLMError
from app.config import get_settings
from app.domain.citations import Citation, CitationReport, build_chunk_index, validate_answer
from app.services.retrieval import RetrievedChunk, hybrid_search

logger = logging.getLogger(__name__)

ABSTENTION_MESSAGE = "No encuentro base en la LCSP para responder esto"

SYSTEM_PROMPT = (
    "Eres un asistente jurídico especializado en la Ley 9/2017 (LCSP). "
    "Responde ÚNICAMENTE con el contexto recuperado; no uses conocimiento externo. "
    "Tras cada afirmación cita el artículo que la respalda con el formato [art. X] "
    "o [art. X.Y], donde Y es el apartado. "
    "Si el contexto no basta para responder, responde abstencion=true y explícalo "
    "en motivo_abstencion. La respuesta no constituye asesoramiento jurídico."
)

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string"},
        "citas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "articulo": {"type": "string"},
                    "apartado": {"type": ["string", "null"]},
                },
                "required": ["articulo", "apartado"],
                "additionalProperties": False,
            },
        },
        "abstencion": {"type": "boolean"},
        "motivo_abstencion": {"type": ["string", "null"]},
    },
    "required": ["respuesta", "citas", "abstencion", "motivo_abstencion"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """The final answer for one question, with its validation outcome."""

    respuesta: str
    citas: tuple[Citation, ...]
    abstencion: bool
    motivo_abstencion: str | None
    unsupported_claims: tuple[str, ...]
    warning: str | None
    model: str
    chunks: tuple[RetrievedChunk, ...]


async def answer_question(
    session: AsyncSession,
    llm: LLMClient,
    question: str,
    *,
    top_k: int = 6,
) -> AnswerResult:
    """Answer `question` from the retrieved context, or abstain (AC-07 first)."""
    settings = get_settings()
    retrieval = await hybrid_search(session, llm, question, top_k=top_k)
    if (
        not retrieval.chunks
        or retrieval.best_score is None
        or retrieval.best_score < settings.rerank_threshold
    ):
        logger.info(
            "answer abstained question_chars=%d retrieved=%d best_score=%s",
            len(question),
            len(retrieval.chunks),
            retrieval.best_score,
        )
        return _abstention(ABSTENTION_MESSAGE, settings.chat_model)

    index = build_chunk_index((chunk.articulo, chunk.apartado) for chunk in retrieval.chunks)
    base_prompt = _user_prompt(question, retrieval.chunks)
    payload = await llm.generate_json(system=SYSTEM_PROMPT, user=base_prompt, schema=ANSWER_SCHEMA)
    respuesta, abstencion, motivo = _extract_answer(payload)
    if abstencion:
        return _abstention(respuesta or motivo or ABSTENTION_MESSAGE, settings.chat_model, motivo)

    report = validate_answer(respuesta, index)
    if report.invalid:
        # Exactly one retry, with the validation errors appended to the prompt.
        retry_prompt = f"{base_prompt}\n\n{_validation_feedback(report)}"
        payload = await llm.generate_json(
            system=SYSTEM_PROMPT, user=retry_prompt, schema=ANSWER_SCHEMA
        )
        respuesta, abstencion, motivo = _extract_answer(payload)
        if abstencion:
            return _abstention(
                respuesta or motivo or ABSTENTION_MESSAGE, settings.chat_model, motivo
            )
        report = validate_answer(respuesta, index)

    if not report.valid:
        # The model could not back a single claim even after the retry. Shipping
        # an answer with no validated citation is worse than abstaining: for a
        # legal tool an unsupported answer is the failure mode we exist to avoid.
        logger.info(
            "answer abstained after unbacked citations question_chars=%d invalid_citations=%d",
            len(question),
            len(report.invalid),
        )
        return _abstention(ABSTENTION_MESSAGE, settings.chat_model, _unbacked_motivo(report))

    unsupported = tuple(claim.text for claim in report.unsupported_claims)
    logger.info(
        "answer generated question_chars=%d valid_citations=%d invalid_citations=%d "
        "unsupported_claims=%d",
        len(question),
        len(report.valid),
        len(report.invalid),
        len(unsupported),
    )
    return AnswerResult(
        respuesta=respuesta,
        citas=report.valid,
        abstencion=False,
        motivo_abstencion=motivo,
        unsupported_claims=unsupported,
        warning=_warning_for(report),
        model=settings.chat_model,
        chunks=tuple(retrieval.chunks),
    )


def _abstention(respuesta: str, model: str, motivo: str | None = None) -> AnswerResult:
    return AnswerResult(
        respuesta=respuesta,
        citas=(),
        abstencion=True,
        motivo_abstencion=motivo if motivo is not None else ABSTENTION_MESSAGE,
        unsupported_claims=(),
        warning=None,
        model=model,
        chunks=(),
    )


def _user_prompt(question: str, chunks: Iterable[RetrievedChunk]) -> str:
    context = "\n\n".join(
        f"[{chunk.articulo}{'.' + chunk.apartado if chunk.apartado else ''}] "
        f"{chunk.titulo}\n{chunk.texto}"
        for chunk in chunks
    )
    return (
        f"Pregunta: {question}\n\n"
        f"Contexto recuperado (única fuente permitida):\n{context}\n\n"
        "Responde en JSON con las claves: respuesta, citas, abstencion, motivo_abstencion."
    )


def _extract_answer(payload: dict[str, Any]) -> tuple[str, bool, str | None]:
    """Pull `(respuesta, abstencion, motivo_abstencion)` out of the payload.

    A payload with missing or mistyped keys is a predictable generation
    failure and raises a typed `LLMError`, never a bare exception.
    """
    respuesta = payload.get("respuesta")
    abstencion = payload.get("abstencion")
    motivo = payload.get("motivo_abstencion")
    citas = payload.get("citas")
    if not isinstance(respuesta, str) or not isinstance(abstencion, bool):
        raise LLMError("generation returned an answer payload with missing or mistyped keys")
    if motivo is not None and not isinstance(motivo, str):
        raise LLMError("generation returned a non-string motivo_abstencion")
    if not isinstance(citas, list):
        raise LLMError("generation returned a non-list citas field")
    return respuesta, abstencion, motivo


def _validation_feedback(report: CitationReport) -> str:
    labels = ", ".join(citation.label() for citation in report.invalid)
    return (
        f"Error de validación: las citas {labels} no corresponden a artículos del "
        "contexto recuperado. Reescribe la respuesta citando solo artículos presentes "
        "en el contexto, o responde abstencion=true con motivo_abstencion."
    )


def _unbacked_motivo(report: CitationReport) -> str:
    labels = ", ".join(citation.label() for citation in report.invalid) or "ninguna"
    return (
        "El modelo no logró respaldar ninguna afirmación con los artículos recuperados "
        f"(citas descartadas: {labels})."
    )


def _warning_for(report: CitationReport) -> str | None:
    if report.invalid:
        labels = ", ".join(citation.label() for citation in report.invalid)
        return f"Afirmaciones con citas no respaldadas por el contexto recuperado: {labels}."
    if report.unsupported_claims:
        return "Algunas afirmaciones de la respuesta no llevan ninguna cita que las respalde."
    return None
