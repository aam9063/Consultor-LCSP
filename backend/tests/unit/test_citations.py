"""Unit tests for the pure citation rules (CL-05, S3/S12, AC-06).

No DB, no LLM: the domain module parses `[art. X]` / `[art. X.Y]`
citations, splits the answer into claims and validates each citation
against the index of retrieved chunks.
"""

from app.domain.citations import (
    Citation,
    build_chunk_index,
    parse_citations,
    split_claims,
    validate_answer,
)

_INDEX: dict[str, set[str | None]] = {"107": {None, "1", "2"}, "159": {None}}


# --- parsing the allowed citation forms --------------------------------------


def test_parses_the_two_allowed_forms() -> None:
    assert parse_citations("[art. 107]") == (Citation(articulo="107", apartado=None),)
    assert parse_citations("[art. 107.2]") == (Citation(articulo="107", apartado="2"),)


def test_tolerates_surrounding_whitespace_and_case() -> None:
    assert parse_citations("[ art. 107 ]") == (Citation("107", None),)
    assert parse_citations("[Art. 107.2]") == (Citation("107", "2"),)


def test_multiple_citations_in_one_bracket() -> None:
    assert parse_citations("[art. 107, art. 159.1]") == (
        Citation("107", None),
        Citation("159", "1"),
    )


def test_repeated_citations_are_deduplicated() -> None:
    assert parse_citations("[art. 107] y más tarde [art. 107]") == (Citation("107", None),)


def test_brackets_without_citations_are_ignored() -> None:
    assert parse_citations("ver [anexo I] y [cuadro 2]") == ()


def test_text_without_brackets_yields_no_citations() -> None:
    assert parse_citations("El plazo es de un mes.") == ()


# --- sentence splitting ------------------------------------------------------


def test_split_claims_keeps_citations_inside_their_sentence() -> None:
    text = "Primera afirmación [art. 107]. Segunda afirmación [art. 159]."
    assert split_claims(text) == (
        "Primera afirmación [art. 107].",
        "Segunda afirmación [art. 159].",
    )


def test_newlines_also_split_claims() -> None:
    assert split_claims("Uno [art. 107].\nDos [art. 159].") == (
        "Uno [art. 107].",
        "Dos [art. 159].",
    )


def test_a_period_inside_a_citation_does_not_split_the_sentence() -> None:
    claims = split_claims("Según [art. 107.2] hay garantía. Y también [art. 159].")
    assert claims == ("Según [art. 107.2] hay garantía.", "Y también [art. 159].")


# --- validation against the retrieved chunks ---------------------------------


def test_citation_to_a_retrieved_article_is_valid() -> None:
    report = validate_answer("La garantía es el 5 por 100 [art. 107].", _INDEX)
    assert report.valid == (Citation("107", None),)
    assert report.invalid == ()
    assert all(claim.supported for claim in report.claims)


def test_citation_to_an_unretrieved_article_is_invalid_and_marks_the_claim() -> None:
    text = "La garantía es del 5 por 100 [art. 999]."
    report = validate_answer(text, _INDEX)
    assert report.invalid == (Citation("999", None),)
    assert report.claims[0].supported is False
    assert report.unsupported_claims[0].text == text


def test_the_named_apartado_must_exist_for_that_article() -> None:
    ok = validate_answer("Plazo [art. 107.2].", _INDEX)
    assert ok.valid == (Citation("107", "2"),)
    bad = validate_answer("Plazo [art. 107.9].", _INDEX)
    assert bad.invalid == (Citation("107", "9"),)
    assert bad.claims[0].supported is False


def test_a_claim_without_any_citation_is_unsupported() -> None:
    report = validate_answer("Afirmación sin cita. Otra con cita [art. 107].", _INDEX)
    assert report.claims[0].supported is False
    assert report.claims[1].supported is True
    assert len(report.unsupported_claims) == 1


def test_one_valid_citation_is_enough_to_support_a_claim() -> None:
    report = validate_answer("Mixto [art. 107] y también [art. 999].", _INDEX)
    assert report.claims[0].supported is True
    assert report.invalid == (Citation("999", None),)


def test_build_chunk_index_groups_apartados_by_article() -> None:
    index = build_chunk_index([("107", None), ("107", "1"), ("107", "2"), ("159", None)])
    assert index == {"107": {None, "1", "2"}, "159": {None}}
