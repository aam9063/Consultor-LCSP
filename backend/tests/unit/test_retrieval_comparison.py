"""Retrieval-only position metrics (hit@1, MRR) and the two-mode comparison: unit tests.

Every test feeds synthetic data: no database, no API, no YAML here.
"""

import json

import pytest

from app.services.evaluation import (
    RetrievalComparisonRow,
    compare_retrieval_modes,
    hit_at_1,
    mean_reciprocal_rank,
    retrieval_compare_payload,
)

# --- hit_at_1 ---------------------------------------------------------------


def test_hit_at_1_expected_article_first_is_one() -> None:
    assert hit_at_1(("107",), ("107", "118", "149")) == 1.0


def test_hit_at_1_expected_article_not_first_is_zero() -> None:
    """Position 3 counts for MRR, never for hit@1."""
    assert hit_at_1(("107",), ("100", "118", "107")) == 0.0


def test_hit_at_1_expected_article_absent_is_zero() -> None:
    assert hit_at_1(("107",), ("100", "118", "149")) == 0.0


def test_hit_at_1_empty_ranking_is_zero() -> None:
    assert hit_at_1(("107",), ()) == 0.0


def test_hit_at_1_two_expected_where_only_the_second_appears() -> None:
    """Two expected articles, only the second one in the ranking, not first: no hit."""
    assert hit_at_1(("107", "149"), ("100", "149")) == 0.0


def test_hit_at_1_two_expected_first_retrieved_is_one_of_them() -> None:
    """hit@1 only looks at the first retrieved article, not at full recall."""
    assert hit_at_1(("107", "149"), ("149", "100")) == 1.0


def test_hit_at_1_without_expected_articles_is_zero() -> None:
    """Nothing can be hit when the question expects no article (out-of-law)."""
    assert hit_at_1((), ("107", "118")) == 0.0


# --- mean_reciprocal_rank ---------------------------------------------------


def test_mrr_expected_at_first_position_is_one() -> None:
    assert mean_reciprocal_rank(("107",), ("107", "118")) == 1.0


def test_mrr_expected_at_third_position_is_one_third() -> None:
    assert mean_reciprocal_rank(("107",), ("100", "118", "107")) == pytest.approx(1 / 3)


def test_mrr_expected_absent_is_zero() -> None:
    assert mean_reciprocal_rank(("107",), ("100", "118")) == 0.0


def test_mrr_empty_ranking_is_zero() -> None:
    assert mean_reciprocal_rank(("107",), ()) == 0.0


def test_mrr_two_expected_where_only_the_second_appears() -> None:
    """The first expected article found in the ranking sets the reciprocal rank."""
    assert mean_reciprocal_rank(("107", "149"), ("100", "149", "118")) == pytest.approx(0.5)


def test_mrr_uses_the_earliest_expected_article_found() -> None:
    """Several expected articles: the earliest one in the ranking wins."""
    assert mean_reciprocal_rank(("107", "149"), ("118", "149", "107")) == pytest.approx(0.5)


# --- compare_retrieval_modes ------------------------------------------------


def _row(
    rid: str,
    expected: tuple[str, ...],
    hybrid: tuple[str, ...],
    embeddings: tuple[str, ...],
) -> RetrievalComparisonRow:
    return RetrievalComparisonRow(
        id=rid,
        pregunta=f"pregunta {rid}",
        expected_articles=expected,
        hybrid_articles=hybrid,
        embeddings_articles=embeddings,
    )


def test_compare_retrieval_modes_better_positions_win() -> None:
    rows = [
        _row("P-01", ("107",), ("107", "100"), ("100", "107")),
        _row("P-02", ("149",), ("149", "100"), ("100", "149")),
        _row("P-03", ("215",), ("100", "215"), ("100", "215")),
    ]
    comparison = compare_retrieval_modes(rows)
    hybrid = comparison["hybrid"]
    embeddings = comparison["embeddings"]
    # Recall@5 cannot separate the modes here: every expected article is in the top 5.
    assert hybrid.recall_at_5 == embeddings.recall_at_5 == pytest.approx(1.0)
    assert hybrid.questions == embeddings.questions == 3
    assert hybrid.hit_at_1 == pytest.approx(2 / 3)
    assert embeddings.hit_at_1 == 0.0
    assert hybrid.mrr == pytest.approx(5 / 6)
    assert embeddings.mrr == pytest.approx(0.5)
    assert hybrid.mrr > embeddings.mrr
    assert hybrid.hit_at_1 > embeddings.hit_at_1


def test_compare_retrieval_modes_identical_rankings_are_a_tie() -> None:
    rows = [
        _row("P-01", ("107",), ("100", "107"), ("100", "107")),
        _row("P-02", ("149",), ("149",), ("149",)),
    ]
    comparison = compare_retrieval_modes(rows)
    hybrid = comparison["hybrid"]
    embeddings = comparison["embeddings"]
    assert hybrid.recall_at_5 == embeddings.recall_at_5
    assert hybrid.hit_at_1 == embeddings.hit_at_1
    assert hybrid.mrr == embeddings.mrr == pytest.approx(0.75)
    assert hybrid.hit_at_1 == pytest.approx(0.5)


def test_compare_retrieval_modes_worst_cases_are_ordered_worst_first() -> None:
    rows = [
        _row("P-01", ("107",), ("107",), ("100", "107")),  # embeddings mrr 0.5
        _row("P-02", ("149",), ("149",), ("149",)),  # perfect in both modes
        _row("P-03", ("215",), ("215",), ("100", "101", "215")),  # embeddings mrr 1/3
    ]
    comparison = compare_retrieval_modes(rows)
    assert comparison["hybrid"].worst_cases == ()
    worst = comparison["embeddings"].worst_cases
    assert [case["id"] for case in worst] == ["P-03", "P-01"]
    assert worst[0]["mrr"] == pytest.approx(1 / 3, abs=1e-4)  # rounded to 4 decimals
    assert worst[0]["recuperados"] == ["100", "101", "215"]
    assert worst[0]["pregunta"] == "pregunta P-03"


def test_compare_retrieval_modes_ignores_out_of_law_questions() -> None:
    rows = [
        _row("P-01", ("107",), ("107",), ("100", "107")),
        _row("P-21", (), ("100", "101"), ("107",)),
    ]
    comparison = compare_retrieval_modes(rows)
    assert comparison["hybrid"].questions == 1
    assert comparison["hybrid"].mrr == 1.0
    assert comparison["embeddings"].mrr == pytest.approx(0.5)


# --- JSON payload for `<fecha>-retrieval.json` ------------------------------


def test_retrieval_compare_payload_keeps_both_rankings_and_every_field() -> None:
    rows = [
        _row("P-01", ("107",), ("107", "100"), ("100", "107")),
        _row("P-21", (), ("100",), ("101",)),
    ]
    comparison = compare_retrieval_modes(rows)
    payload = retrieval_compare_payload(
        rows, comparison, fecha="2026-11-14", corpus="LCSP", top_k=6
    )
    assert payload["fecha"] == "2026-11-14"
    assert payload["corpus"] == "LCSP"
    assert payload["top_k"] == 6
    assert set(payload["comparison"]) == {"hybrid", "embeddings"}
    for mode in ("hybrid", "embeddings"):
        assert {"questions", "recall_at_5", "hit_at_1", "mrr", "worst_cases"} <= set(
            payload["comparison"][mode]
        )
    assert payload["questions"][0] == {
        "id": "P-01",
        "pregunta": "pregunta P-01",
        "articulos_esperados": ["107"],
        "hibrido": ["107", "100"],
        "embeddings": ["100", "107"],
    }
    # Out-of-law questions keep their rankings even though they are not judged.
    assert payload["questions"][1]["hibrido"] == ["100"]
    assert payload["questions"][1]["embeddings"] == ["101"]
    # The payload must be exactly what the runner writes to disk.
    json.dumps(payload, ensure_ascii=False)
