"""Pure clause-review rules (CL-06, S4/S14, AC-08).

A review answer is a list of avisos `{tipo, explicacion, articulos_citados,
cita_de_la_clausula}`. This module validates each aviso against the clause
and the index of retrieved chunks with the same citation helpers the answer
service uses: every cited article must be one of the retrieved chunks
(`[art. X]` / `[art. X.Y]`, parsed by `parse_citations` — no second parser)
and every aviso must quote the exact clause fragment it is about (tolerating
surrounding whitespace). An out-of-enum `tipo` and an aviso without any
cited article are rejected as typed invalid entries carrying the raw details
and a stable reason, so a caller can mark or drop them explicitly. A clause
over `MAX_CLAUSE_WORDS` words is rejected with a typed error.

Domain code: no SQLAlchemy, no AI SDK, no FastAPI (AGENTS.md section 8).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from app.domain.citations import Citation, citation_backed, parse_citations

__all__ = [
    "MAX_CLAUSE_WORDS",
    "REASON_ARTICULO_NO_RECUPERADO",
    "REASON_AVISO_MAL_FORMADO",
    "REASON_CITA_NO_ENCONTRADA",
    "REASON_SIN_ARTICULOS",
    "REASON_TIPO_NO_VALIDO",
    "VALID_TIPOS",
    "ClauseReviewReport",
    "ClauseTooLongError",
    "ClauseWarning",
    "InvalidClauseWarning",
    "TipoAviso",
    "validate_clause_length",
    "validate_clause_warnings",
]

TipoAviso = Literal["posible_incumplimiento", "ambiguedad", "ok"]

VALID_TIPOS: tuple[str, ...] = ("posible_incumplimiento", "ambiguedad", "ok")

MAX_CLAUSE_WORDS = 800

# Stable rejection reasons, exposed so the caller can mark or drop each
# invalid aviso explicitly.
REASON_TIPO_NO_VALIDO = "tipo_no_valido"
REASON_SIN_ARTICULOS = "sin_articulos_citados"
REASON_ARTICULO_NO_RECUPERADO = "articulo_no_recuperado"
REASON_CITA_NO_ENCONTRADA = "cita_no_encontrada"
REASON_AVISO_MAL_FORMADO = "aviso_mal_formado"


class ClauseReviewError(Exception):
    """Base class for typed clause-review failures."""


class ClauseTooLongError(ClauseReviewError):
    """The clause exceeds the ~800-word cap of BRIEF §5 S4."""

    def __init__(self, word_count: int, max_words: int) -> None:
        self.word_count = word_count
        self.max_words = max_words
        super().__init__(f"the clause has {word_count} words, over the limit of {max_words}")


@dataclass(frozen=True, slots=True)
class ClauseWarning:
    """One validated aviso: typed issue, citation-backed, quoting the clause."""

    tipo: TipoAviso
    explicacion: str
    articulos_citados: tuple[Citation, ...]
    cita_de_la_clausula: str


@dataclass(frozen=True, slots=True)
class InvalidClauseWarning:
    """One rejected aviso, with its raw details and why it was rejected."""

    tipo: str | None
    explicacion: str | None
    cita_de_la_clausula: str | None
    articulos_citados: tuple[str, ...]
    motivos: tuple[str, ...]
    citas_no_recuperadas: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ClauseReviewReport:
    """Outcome of validating one review answer against clause and index."""

    warnings: tuple[ClauseWarning, ...]
    invalid: tuple[InvalidClauseWarning, ...]

    @property
    def needs_citation_retry(self) -> bool:
        """True when some aviso cites an article that was not retrieved."""
        return any(REASON_ARTICULO_NO_RECUPERADO in aviso.motivos for aviso in self.invalid)

    @property
    def unbacked_labels(self) -> tuple[str, ...]:
        """Labels of the cited articles that are not in the retrieved index."""
        labels: list[str] = []
        for aviso in self.invalid:
            for citation in aviso.citas_no_recuperadas:
                if citation.label() not in labels:
                    labels.append(citation.label())
        return tuple(labels)


def validate_clause_length(clause: str) -> None:
    """Raise `ClauseTooLongError` when `clause` exceeds the word cap."""
    word_count = len(clause.split())
    if word_count > MAX_CLAUSE_WORDS:
        raise ClauseTooLongError(word_count, MAX_CLAUSE_WORDS)


def _parse_citation_items(items: object) -> tuple[Citation, ...]:
    """Parse the aviso's `articulos_citados` with the shared citation parser.

    Each item must be a `[art. X]` / `[art. X.Y]` citation; joining them and
    running `parse_citations` reuses the answer-side parser (AC-08), so a
    plain "107" is simply not a citation and yields nothing.
    """
    if not isinstance(items, list):
        return ()
    text = " ".join(str(item) for item in items)
    return parse_citations(text)


def validate_clause_warnings(
    avisos: Iterable[Any],
    clause: str,
    index: Mapping[str, set[str | None]],
) -> ClauseReviewReport:
    """Validate every aviso against `clause` and the retrieved-chunk index."""
    warnings: list[ClauseWarning] = []
    invalid: list[InvalidClauseWarning] = []
    for aviso in avisos:
        if not isinstance(aviso, Mapping):
            invalid.append(
                InvalidClauseWarning(
                    tipo=None,
                    explicacion=None,
                    cita_de_la_clausula=None,
                    articulos_citados=(),
                    motivos=(REASON_AVISO_MAL_FORMADO,),
                )
            )
            continue
        tipo = aviso.get("tipo")
        explicacion = aviso.get("explicacion")
        articulos = aviso.get("articulos_citados")
        cita = aviso.get("cita_de_la_clausula")
        if (
            not isinstance(tipo, str)
            or not isinstance(explicacion, str)
            or not isinstance(cita, str)
            or not isinstance(articulos, list)
        ):
            invalid.append(
                InvalidClauseWarning(
                    tipo=tipo if isinstance(tipo, str) else None,
                    explicacion=explicacion if isinstance(explicacion, str) else None,
                    cita_de_la_clausula=cita if isinstance(cita, str) else None,
                    articulos_citados=(
                        tuple(str(item) for item in articulos)
                        if isinstance(articulos, list)
                        else ()
                    ),
                    motivos=(REASON_AVISO_MAL_FORMADO,),
                )
            )
            continue

        motivos: list[str] = []
        if tipo not in VALID_TIPOS:
            motivos.append(REASON_TIPO_NO_VALIDO)
        citations = _parse_citation_items(articulos)
        if not citations:
            motivos.append(REASON_SIN_ARTICULOS)
        unbacked = tuple(c for c in citations if not citation_backed(c, index))
        if unbacked:
            motivos.append(REASON_ARTICULO_NO_RECUPERADO)
        fragmento = cita.strip()
        if not fragmento or fragmento not in clause:
            motivos.append(REASON_CITA_NO_ENCONTRADA)

        if motivos:
            invalid.append(
                InvalidClauseWarning(
                    tipo=tipo,
                    explicacion=explicacion,
                    cita_de_la_clausula=cita,
                    articulos_citados=tuple(str(item) for item in articulos),
                    motivos=tuple(motivos),
                    citas_no_recuperadas=unbacked,
                )
            )
        else:
            warnings.append(
                ClauseWarning(
                    tipo=cast("TipoAviso", tipo),
                    explicacion=explicacion,
                    articulos_citados=citations,
                    cita_de_la_clausula=fragmento,
                )
            )
    return ClauseReviewReport(warnings=tuple(warnings), invalid=tuple(invalid))
