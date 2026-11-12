"""Unit tests for the pure clause-review rules (CL-06, S4/S14, AC-08).

No DB, no LLM: the domain functions are pure and the retrieved-chunk index is
built by hand with the shared `build_chunk_index` helper.
"""

from typing import cast

import pytest

from app.domain.citations import Citation, build_chunk_index
from app.domain.clauses import (
    MAX_CLAUSE_WORDS,
    REASON_ARTICULO_NO_RECUPERADO,
    REASON_CITA_NO_ENCONTRADA,
    REASON_SIN_ARTICULOS,
    REASON_TIPO_NO_VALIDO,
    VALID_TIPOS,
    ClauseTooLongError,
    validate_clause_length,
    validate_clause_warnings,
)

INDEX = build_chunk_index([("107", None), ("159", "1")])
CLAUSE = "El contratista quedará exento de constituir la garantía definitiva."
FRAGMENT = "garantía definitiva"


def _aviso(
    tipo: str = "posible_incumplimiento",
    citas: list[object] | None = None,
    fragmento: str = FRAGMENT,
) -> dict[str, object]:
    return {
        "tipo": tipo,
        "explicacion": "La cláusula elimina una garantía exigida por la ley.",
        "articulos_citados": ["[art. 107]"] if citas is None else citas,
        "cita_de_la_clausula": fragmento,
    }


# --- the three `tipo` values are accepted -------------------------------------


def test_the_three_tipo_values_are_accepted() -> None:
    assert VALID_TIPOS == ("posible_incumplimiento", "ambiguedad", "ok")

    for tipo in VALID_TIPOS:
        report = validate_clause_warnings([_aviso(tipo=tipo)], CLAUSE, INDEX)

        assert report.invalid == ()
        assert len(report.warnings) == 1
        warning = report.warnings[0]
        assert warning.tipo == tipo
        assert warning.articulos_citados == (Citation("107", None),)
        assert warning.cita_de_la_clausula == FRAGMENT


# --- typed rejections ---------------------------------------------------------


def test_an_unknown_tipo_is_rejected_with_its_details() -> None:
    report = validate_clause_warnings([_aviso(tipo="grave")], CLAUSE, INDEX)

    assert report.warnings == ()
    assert len(report.invalid) == 1
    rejected = report.invalid[0]
    assert rejected.motivos == (REASON_TIPO_NO_VALIDO,)
    assert rejected.tipo == "grave"
    assert rejected.explicacion is not None and "garantía" in rejected.explicacion


def test_a_warning_with_no_cited_article_is_rejected() -> None:
    report = validate_clause_warnings([_aviso(citas=[])], CLAUSE, INDEX)

    assert report.warnings == ()
    assert report.invalid[0].motivos == (REASON_SIN_ARTICULOS,)


def test_a_citation_string_that_is_not_a_citation_counts_as_no_cited_article() -> None:
    report = validate_clause_warnings([_aviso(citas=["el artículo 107"])], CLAUSE, INDEX)

    assert report.warnings == ()
    assert report.invalid[0].motivos == (REASON_SIN_ARTICULOS,)


def test_a_warning_citing_an_article_that_was_not_retrieved_is_invalid() -> None:
    report = validate_clause_warnings([_aviso(citas=["[art. 999]"])], CLAUSE, INDEX)

    assert report.warnings == ()
    assert len(report.invalid) == 1
    rejected = report.invalid[0]
    assert REASON_ARTICULO_NO_RECUPERADO in rejected.motivos
    assert rejected.citas_no_recuperadas == (Citation("999", None),)


def test_an_apartado_that_does_not_exist_is_also_not_retrieved() -> None:
    # Art. 107 is retrieved without apartados, so [art. 107.2] does not exist.
    report = validate_clause_warnings([_aviso(citas=["[art. 107.2]"])], CLAUSE, INDEX)

    assert report.warnings == ()
    assert REASON_ARTICULO_NO_RECUPERADO in report.invalid[0].motivos


# --- the clause fragment ------------------------------------------------------


def test_a_quote_that_is_not_in_the_clause_is_flagged() -> None:
    report = validate_clause_warnings(
        [_aviso(fragmento="plazo de ejecución de tres años")], CLAUSE, INDEX
    )

    assert report.warnings == ()
    assert REASON_CITA_NO_ENCONTRADA in report.invalid[0].motivos


def test_the_quote_tolerates_surrounding_whitespace() -> None:
    report = validate_clause_warnings([_aviso(fragmento=f"  {FRAGMENT}  ")], CLAUSE, INDEX)

    assert report.invalid == ()
    assert report.warnings[0].cita_de_la_clausula == FRAGMENT


# --- the ~800 word cap --------------------------------------------------------


def test_a_clause_over_800_words_is_rejected_with_a_typed_error() -> None:
    clause = " ".join(["palabra"] * (MAX_CLAUSE_WORDS + 1))

    with pytest.raises(ClauseTooLongError) as excinfo:
        validate_clause_length(clause)

    assert excinfo.value.word_count == MAX_CLAUSE_WORDS + 1
    assert excinfo.value.max_words == MAX_CLAUSE_WORDS


def test_a_clause_of_exactly_800_words_is_accepted() -> None:
    clause = " ".join(["palabra"] * MAX_CLAUSE_WORDS)

    validate_clause_length(clause)  # must not raise


def test_the_service_rejects_an_unbacked_and_malformed_warning_mix() -> None:
    report = validate_clause_warnings([_aviso(), "no soy un aviso", {"tipo": 42}], CLAUSE, INDEX)

    assert len(report.warnings) == 1
    assert len(report.invalid) == 2
    assert all("mal_formado" in motivo for invalid in report.invalid for motivo in invalid.motivos)
    assert cast("object", report.warnings[0].articulos_citados) == (Citation("107", None),)
