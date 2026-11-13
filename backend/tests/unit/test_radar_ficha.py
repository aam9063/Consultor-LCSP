"""Unit tests for the Radar ficha domain rules (S7-01, S1/S2/S3/S5).

No DB, no LLM: composition, normalisation and quote-to-origin mapping are
pure functions. The word-limit rule reuses the clause reviewer's limit, so
the oversized case is derived from `MAX_CLAUSE_WORDS`, never a hardcoded
word count.
"""

import pytest

from app.domain.clauses import MAX_CLAUSE_WORDS
from app.domain.radar_ficha import (
    REASON_FICHA_DEMASIADO_LARGA,
    REASON_FICHA_SIN_DATOS,
    RadarFichaError,
    RadarFichaInput,
    compose_radar_ficha_text,
    origin_field_of_quote,
    validate_radar_ficha,
)

PENALIDAD = "El contratista que no respete el plazo de ejecución sufrirá una penalidad del 10%."
GARANTIA = "La garantía definitiva se fija en el 5% del importe de licitación."


def _input(
    penalidades: list[str] | None = None,
    garantia_definitiva: str | None = GARANTIA,
    expediente: str | None = "EXP-2026-001",
    licitacion_id: int = 42,
) -> RadarFichaInput:
    return RadarFichaInput(
        licitacion_id=licitacion_id,
        expediente=expediente,
        penalidades=[PENALIDAD] if penalidades is None else penalidades,
        garantia_definitiva=garantia_definitiva,
    )


# --- composition labels each origin field ------------------------------------


def test_composition_labels_each_origin_field() -> None:
    ficha = validate_radar_ficha(_input())
    texto = compose_radar_ficha_text(ficha)

    assert "penalidades" in texto, "the penalidades section names its origin field"
    assert "garantia_definitiva" in texto, "the garantía section names its origin field"
    assert texto.index(PENALIDAD) < texto.index("garantia_definitiva"), (
        "penalidades come before the garantía section"
    )
    assert GARANTIA in texto


def test_composition_of_a_ficha_without_garantia_only_labels_penalidades() -> None:
    ficha = validate_radar_ficha(_input(garantia_definitiva=None))
    texto = compose_radar_ficha_text(ficha)

    assert "garantia_definitiva" not in texto
    assert PENALIDAD in texto


# --- normalisation: trim whitespace, drop empty strings -----------------------


def test_normalisation_trims_and_drops_empty_strings() -> None:
    ficha = validate_radar_ficha(
        _input(
            penalidades=["", "   ", f"  {PENALIDAD}  "],
            garantia_definitiva=f"  {GARANTIA} ",
            expediente="  EXP-2026-001 ",
        )
    )

    assert ficha.penalidades == (PENALIDAD,)
    assert ficha.garantia_definitiva == GARANTIA
    assert ficha.expediente == "EXP-2026-001"


def test_normalisation_maps_an_empty_expediente_to_none() -> None:
    ficha = validate_radar_ficha(_input(expediente="   "))

    assert ficha.expediente is None


def test_normalisation_preserves_the_licitacion_id() -> None:
    ficha = validate_radar_ficha(_input(licitacion_id=7))

    assert ficha.licitacion_id == 7


# --- typed rejections ---------------------------------------------------------


def test_a_payload_with_no_usable_content_is_rejected_ficha_sin_datos() -> None:
    for garantia in (None, "   "):
        with pytest.raises(RadarFichaError) as excinfo:
            validate_radar_ficha(_input(penalidades=["", "  "], garantia_definitiva=garantia))

        assert excinfo.value.motivo == REASON_FICHA_SIN_DATOS


def test_an_oversized_composed_text_is_rejected_ficha_demasiado_larga() -> None:
    # Derived from the imported reviewer limit, never a hardcoded word count.
    garantia = " ".join(["palabra"] * (MAX_CLAUSE_WORDS + 1))
    ficha_input = _input(penalidades=[], garantia_definitiva=garantia)

    with pytest.raises(RadarFichaError) as excinfo:
        validate_radar_ficha(ficha_input)

    assert excinfo.value.motivo == REASON_FICHA_DEMASIADO_LARGA


def test_a_composed_text_up_to_the_limit_is_accepted() -> None:
    # The section headers also count, so the boundary is the imported limit
    # minus the composition overhead, derived here and never hardcoded.
    overhead = _composition_overhead()
    garantia = " ".join(["palabra"] * (MAX_CLAUSE_WORDS - overhead))

    ficha = validate_radar_ficha(_input(penalidades=[], garantia_definitiva=garantia))

    assert len(ficha.texto.split()) == MAX_CLAUSE_WORDS


def _composition_overhead() -> int:
    """Words the composer adds on top of the field contents."""
    texto = compose_radar_ficha_text(
        validate_radar_ficha(_input(penalidades=[], garantia_definitiva="x"))
    )
    return len(texto.split()) - 1


# --- quote-to-origin mapping --------------------------------------------------


def test_a_quote_from_the_penalidades_section_maps_to_penalidades() -> None:
    texto = compose_radar_ficha_text(validate_radar_ficha(_input()))

    assert origin_field_of_quote(texto, "penalidad del 10%") == "penalidades"
    assert origin_field_of_quote(texto, f"  {PENALIDAD}  ") == "penalidades"


def test_a_quote_from_the_garantia_section_maps_to_garantia_definitiva() -> None:
    texto = compose_radar_ficha_text(validate_radar_ficha(_input()))

    assert origin_field_of_quote(texto, "5% del importe") == "garantia_definitiva"


def test_a_quote_that_belongs_to_no_section_maps_to_none() -> None:
    texto = compose_radar_ficha_text(validate_radar_ficha(_input()))

    assert origin_field_of_quote(texto, "plazo de presentación de ofertas") is None


def test_an_empty_quote_maps_to_none() -> None:
    texto = compose_radar_ficha_text(validate_radar_ficha(_input()))

    assert origin_field_of_quote(texto, "   ") is None
