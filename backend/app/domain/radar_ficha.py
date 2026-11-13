"""Radar ficha domain rules (S7-01, S1/S2/S3/S5).

Radar de Pliegos pushes the verbatim text it extracted (`penalidades` and
`garantia_definitiva`) to Consultor. This module validates that payload and
composes the single text the clause reviewer sees: every field gets a
labelled section carrying its origin field, so the model can tell penalties
from the guarantee (S3), and every validated aviso's literal quote can be
mapped back to the field it came from (S4). A quote that appears in no
section maps to `None` rather than guessing.

Validation is typed with the same rejection-reason style as `clauses.py`:
a payload with no usable content is rejected (`ficha_sin_datos`) and a
composed text over the reviewer's word limit is rejected
(`ficha_demasiado_larga`) using the SAME limit the clause reviewer enforces
(imported, never duplicated).

Domain code: stdlib + Pydantic only — no SQLAlchemy, no AI SDK, no FastAPI
(AGENTS.md section 8).
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.domain.clauses import MAX_CLAUSE_WORDS, ClauseTooLongError, validate_clause_length

__all__ = [
    "MAX_FICHA_WORDS",
    "REASON_FICHA_DEMASIADO_LARGA",
    "REASON_FICHA_SIN_DATOS",
    "OriginField",
    "RadarFicha",
    "RadarFichaError",
    "RadarFichaInput",
    "compose_radar_ficha_text",
    "origin_field_of_quote",
    "validate_radar_ficha",
]

# The reviewer's word limit, reused (imported) — never a second number.
MAX_FICHA_WORDS = MAX_CLAUSE_WORDS

OriginField = Literal["penalidades", "garantia_definitiva"]

# Stable rejection reasons, same style as the `clauses.py` rejection motives.
REASON_FICHA_SIN_DATOS = "ficha_sin_datos"
REASON_FICHA_DEMASIADO_LARGA = "ficha_demasiado_larga"

# Section headers of the composed text. Both the composer and the
# quote-to-origin resolver share them, so a quote can be located in exactly
# one section body.
_PENALIDADES_HEADER = "Penalidades (campo: penalidades):"
_GARANTIA_HEADER = "Garantía definitiva (campo: garantia_definitiva):"


class RadarFichaError(Exception):
    """A typed, predictable rejection of the Radar payload."""

    def __init__(self, motivo: str, message: str) -> None:
        self.motivo = motivo
        self.message = message
        super().__init__(f"{motivo}: {message}")


class RadarFichaInput(BaseModel):
    """The payload Radar pushes to `POST /revisiones/radar` (S1)."""

    licitacion_id: int
    expediente: str | None = None
    penalidades: list[str] = []
    garantia_definitiva: str | None = None


@dataclass(frozen=True, slots=True)
class RadarFicha:
    """The validated ficha, with its fields normalised and text composed."""

    licitacion_id: int
    expediente: str | None
    penalidades: tuple[str, ...]
    garantia_definitiva: str | None
    texto: str


def _clean(value: str | None) -> str | None:
    """Trim surrounding whitespace; an empty result becomes `None`."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def validate_radar_ficha(ficha: RadarFichaInput) -> RadarFicha:
    """Normalise the payload and reject it with typed reasons when unusable.

    Whitespace is trimmed and empty strings are dropped (S5). A payload with
    neither penalidades nor a garantía left is rejected (`ficha_sin_datos`)
    and a composed text over the reviewer's word limit is rejected
    (`ficha_demasiado_larga`), both before any retrieval or generation.
    """
    penalidades = tuple(line.strip() for line in ficha.penalidades if line.strip())
    garantia_definitiva = _clean(ficha.garantia_definitiva)
    expediente = _clean(ficha.expediente)

    if not penalidades and garantia_definitiva is None:
        raise RadarFichaError(
            REASON_FICHA_SIN_DATOS,
            "La ficha no aporta penalidades ni garantía definitiva revisables.",
        )

    texto = compose_radar_ficha_text(
        RadarFicha(
            licitacion_id=ficha.licitacion_id,
            expediente=expediente,
            penalidades=penalidades,
            garantia_definitiva=garantia_definitiva,
            texto="",
        )
    )
    try:
        validate_clause_length(texto)
    except ClauseTooLongError as error:
        raise RadarFichaError(
            REASON_FICHA_DEMASIADO_LARGA,
            f"La ficha compuesta tiene {error.word_count} palabras y el límite es "
            f"{error.max_words}.",
        ) from error

    return RadarFicha(
        licitacion_id=ficha.licitacion_id,
        expediente=expediente,
        penalidades=penalidades,
        garantia_definitiva=garantia_definitiva,
        texto=texto,
    )


def compose_radar_ficha_text(ficha: RadarFicha) -> str:
    """Compose the review text, each section labelled with its origin field.

    The labels are what lets the model tell penalties from the guarantee in
    a single generation pass (S3) and what the quote-to-origin resolver
    reads back (S4).
    """
    sections: list[str] = []
    if ficha.penalidades:
        lines = "\n".join(f"- {line}" for line in ficha.penalidades)
        sections.append(f"{_PENALIDADES_HEADER}\n{lines}")
    if ficha.garantia_definitiva is not None:
        sections.append(f"{_GARANTIA_HEADER}\n{ficha.garantia_definitiva}")
    return "\n\n".join(sections)


def origin_field_of_quote(texto: str, cita: str) -> OriginField | None:
    """Map a validated aviso's literal quote back to its origin field (S4).

    The quote is located in the composed text and attributed to the field
    whose section body contains it; `penalidades` is checked first. A quote
    that appears in no section maps to `None` rather than guessing.
    """
    fragmento = cita.strip()
    if not fragmento:
        return None
    sections: tuple[tuple[str, OriginField], ...] = (
        (_PENALIDADES_HEADER, "penalidades"),
        (_GARANTIA_HEADER, "garantia_definitiva"),
    )
    for header, field in sections:
        body = _section_body(texto, header)
        if body is not None and fragmento in body:
            return field
    return None


def _section_body(texto: str, header: str) -> str | None:
    """Return the text of one labelled section, or `None` when absent.

    A section body runs from after its header to the next section header
    (or the end of the text).
    """
    start = texto.find(header)
    if start == -1:
        return None
    rest = texto[start + len(header) :]
    next_headers = [
        header_
        for header_ in (_PENALIDADES_HEADER, _GARANTIA_HEADER)
        if header_ != header and header_ in rest
    ]
    if next_headers:
        rest = rest[: min(rest.find(next_header) for next_header in next_headers)]
    return rest
