"""The annotated question set itself (CL-08, S6/S16): structural validation.

Loads `evals/preguntas.yaml` from the repository root so CI validates the
real annotated file, not a copy. No API calls, no database.
"""

import re
from pathlib import Path

import pytest
import yaml

QUESTIONS_PATH = Path(__file__).resolve().parents[3] / "evals" / "preguntas.yaml"

ARTICLE_RE = re.compile(r"^\d{1,3}(\.\d{1,3})?$")


@pytest.fixture(scope="module")
def questions() -> list[dict[str, object]]:
    with QUESTIONS_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, list)
    return data


def test_set_has_exactly_25_entries(questions: list[dict[str, object]]) -> None:
    assert len(questions) == 25


def test_entry_keys_and_types(questions: list[dict[str, object]]) -> None:
    for entry in questions:
        assert set(entry) == {
            "id",
            "pregunta",
            "articulos_esperados",
            "respuesta_referencia",
            "debe_abstenerse",
        }, entry.get("id")
        assert isinstance(entry["id"], str) and entry["id"]
        assert isinstance(entry["pregunta"], str) and entry["pregunta"]
        assert isinstance(entry["respuesta_referencia"], str) and entry["respuesta_referencia"]
        assert isinstance(entry["debe_abstenerse"], bool)
        assert isinstance(entry["articulos_esperados"], list)


def test_ids_are_unique(questions: list[dict[str, object]]) -> None:
    ids = [str(entry["id"]) for entry in questions]
    assert len(set(ids)) == len(ids)


def test_exactly_20_in_law_and_5_out_of_law(questions: list[dict[str, object]]) -> None:
    in_law = [e for e in questions if not e["debe_abstenerse"]]
    out_of_law = [e for e in questions if e["debe_abstenerse"]]
    assert len(in_law) == 20
    assert len(out_of_law) == 5


def test_out_of_law_entries_expect_no_articles(questions: list[dict[str, object]]) -> None:
    for entry in questions:
        if entry["debe_abstenerse"]:
            assert entry["articulos_esperados"] == [], entry["id"]


def test_in_law_entries_name_confirmed_articles(questions: list[dict[str, object]]) -> None:
    for entry in questions:
        if not entry["debe_abstenerse"]:
            articles = entry["articulos_esperados"]
            assert isinstance(articles, list) and bool(articles), entry["id"]
            for article in articles:
                assert isinstance(article, str)
                assert ARTICLE_RE.match(article), (entry["id"], article)


def test_in_law_entries_expect_at_most_two_articles(questions: list[dict[str, object]]) -> None:
    """A professional doubt can span two precepts, never more."""
    for entry in questions:
        expected = entry["articulos_esperados"]
        if entry["debe_abstenerse"]:
            continue
        assert isinstance(expected, list)
        assert len(expected) <= 2, entry["id"]


def test_two_article_questions_name_both_in_the_reference_answer(
    questions: list[dict[str, object]],
) -> None:
    """A question expecting two articles says so in `respuesta_referencia`."""
    for entry in questions:
        expected = entry["articulos_esperados"]
        if entry["debe_abstenerse"] or not isinstance(expected, list) or len(expected) < 2:
            continue
        reference = str(entry["respuesta_referencia"])
        assert all(re.search(rf"\b{number}\b", reference) for number in expected), entry["id"]


def test_in_law_questions_do_not_echo_the_statute_wording(
    questions: list[dict[str, object]],
) -> None:
    """Questions must be asked the way a professional would, not copy titles.

    The saturated first run scored 100% recall because the questions repeated
    the article titles almost verbatim. Naming the article in the question
    defeats the point of the retrieval evaluation, so it is forbidden.
    """
    for entry in questions:
        if not entry["debe_abstenerse"]:
            question = str(entry["pregunta"]).lower()
            assert "artículo" not in question and "articulo" not in question, entry["id"]
