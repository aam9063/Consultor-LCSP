"""Unit tests for the pure ranking helpers (CL-04, S2/S11, AC-05).

`reciprocal_rank_fusion` and `ranked_indices` must be deterministic and
stable: score ties break by rank position, never by dict iteration order.
`extract_article_number` powers the direct article path (AC-04 / S10).
"""

import pytest

from app.domain.ranking import extract_article_number, ranked_indices, reciprocal_rank_fusion


def _rrf(rank: int, *, k: int = 60) -> float:
    return 1.0 / (k + rank)


class TestReciprocalRankFusion:
    def test_merges_two_rankings_into_one_exact_order(self) -> None:
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "a", "b"]])

        scores = {item.id: item.score for item in fused}
        assert scores["a"] == pytest.approx(_rrf(1) + _rrf(2))
        assert scores["c"] == pytest.approx(_rrf(1) + _rrf(3))
        assert scores["b"] == pytest.approx(_rrf(2) + _rrf(3))
        assert [item.id for item in fused] == ["a", "c", "b"]

    def test_ties_break_by_first_appearance_not_by_dict_order(self) -> None:
        # Both ids collect the same total, so any dict- or alphabet-based
        # tie-break would make both calls return the same order.
        first = reciprocal_rank_fusion([["p", "q"], ["q", "p"]])
        assert [item.id for item in first] == ["p", "q"]
        second = reciprocal_rank_fusion([["q", "p"], ["p", "q"]])
        assert [item.id for item in second] == ["q", "p"]

    def test_accepts_any_number_of_rankings(self) -> None:
        fused = reciprocal_rank_fusion([["x", "y"], ["y"], ["x", "y", "z"]])

        assert [item.id for item in fused] == ["y", "x", "z"]
        assert fused[0].score == pytest.approx(_rrf(2) + _rrf(1) + _rrf(2))
        assert fused[1].score == pytest.approx(_rrf(1) + _rrf(1))

    def test_single_ranking_preserves_its_order(self) -> None:
        fused = reciprocal_rank_fusion([["n3", "n1", "n2"]])

        assert [item.id for item in fused] == ["n3", "n1", "n2"]

    def test_empty_input_yields_empty_output(self) -> None:
        assert reciprocal_rank_fusion([]) == []


class TestRankedIndices:
    def test_orders_positions_by_score_descending(self) -> None:
        assert ranked_indices([0.1, 0.9, 0.5]) == [1, 2, 0]

    def test_ties_break_by_input_position_not_by_dict_order(self) -> None:
        assert ranked_indices([0.7, 0.7, 0.2]) == [0, 1, 2]

    def test_empty_input_yields_empty_output(self) -> None:
        assert ranked_indices([]) == []


class TestExtractArticleNumber:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("¿Qué dice el artículo 107?", "107"),
            ("art. 107", "107"),
            ("artículo 107.2", "107"),
            ("Artículo 159", "159"),
            ("¿Qué regula el artículo 2 de la LCSP?", "2"),
            ("dime el art. 193", "193"),
        ],
    )
    def test_extracts_the_named_article_number(self, question: str, expected: str) -> None:
        assert extract_article_number(question) == expected

    @pytest.mark.parametrize(
        ("question",),
        [
            ("artículo 0",),
            ("el artículo de la ley",),
            ("159",),
            ("¿Qué dice el artículo 1072?",),
            ("el expediente 1072 quedó archivado",),
        ],
    )
    def test_does_not_match_non_article_numbers(self, question: str) -> None:
        assert extract_article_number(question) is None
