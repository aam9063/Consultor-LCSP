"""Pure metrics for the evaluation set (CL-08, S6/S16): unit tests.

Every test feeds synthetic data: no database, no API, no YAML here.
"""

import pytest

from app.services.evaluation import (
    QuestionResult,
    abstention_accuracy,
    all_citations_valid,
    build_report,
    question_record,
    recall_at_k,
)

# --- recall@5 ---------------------------------------------------------------


def test_recall_at_k_expected_at_fifth_position_is_full() -> None:
    """Boundary: the expected article is exactly the 5th retrieved."""
    retrieved = ("300", "71", "107", "118", "159", "215")
    assert recall_at_k(("159",), retrieved, k=5) == 1.0


def test_recall_at_k_expected_at_sixth_position_is_zero() -> None:
    """Boundary: the expected article is the 6th, one past k=5."""
    retrieved = ("300", "71", "107", "118", "159", "215")
    assert recall_at_k(("215",), retrieved, k=5) == 0.0


def test_recall_at_k_partial_hit_is_fraction() -> None:
    retrieved = ("107", "71", "300", "118", "159", "215")
    assert recall_at_k(("107", "149"), retrieved, k=5) == 0.5


def test_recall_at_k_no_expected_articles_is_one() -> None:
    """Out-of-law questions expect nothing, so recall cannot be partial."""
    assert recall_at_k((), ("107", "118"), k=5) == 1.0


# --- citation validity ------------------------------------------------------


def test_all_citations_valid_true() -> None:
    answer = QuestionResult(
        id="P-01",
        pregunta="x",
        expected_articles=("107",),
        should_abstain=False,
        abstained=False,
        citations=("107", "107.2"),
        retrieved_articles=("107", "118"),
    )
    assert all_citations_valid(answer) is True


def test_all_citations_valid_false_when_citation_not_retrieved() -> None:
    answer = QuestionResult(
        id="P-02",
        pregunta="x",
        expected_articles=("107",),
        should_abstain=False,
        abstained=False,
        citations=("107", "999"),
        retrieved_articles=("107",),
    )
    assert all_citations_valid(answer) is False


def test_all_citations_valid_false_without_any_citation() -> None:
    """Every claim must carry a citation, so a bare answer is invalid."""
    answer = QuestionResult(
        id="P-03",
        pregunta="x",
        expected_articles=("107",),
        should_abstain=False,
        abstained=False,
        citations=(),
        retrieved_articles=("107",),
    )
    assert all_citations_valid(answer) is False


def test_all_citations_valid_ignores_apartado_suffix() -> None:
    answer = QuestionResult(
        id="P-04",
        pregunta="x",
        expected_articles=("118",),
        should_abstain=False,
        abstained=False,
        citations=("118.1",),
        retrieved_articles=("118",),
    )
    assert all_citations_valid(answer) is True


def test_all_citations_valid_abstention_has_no_claims() -> None:
    answer = QuestionResult(
        id="P-05",
        pregunta="x",
        expected_articles=(),
        should_abstain=True,
        abstained=True,
        citations=(),
        retrieved_articles=(),
    )
    assert all_citations_valid(answer) is True


# --- abstention accuracy ----------------------------------------------------


def test_abstention_accuracy_counts_only_out_of_law() -> None:
    results = [
        QuestionResult("P-01", "q", ("107",), False, False, ("107",), ("107",), ()),
        QuestionResult("P-21", "q", (), True, True, (), (), ()),
        QuestionResult("P-22", "q", (), True, True, (), (), ()),
        QuestionResult("P-23", "q", (), True, True, (), (), ()),
        QuestionResult("P-24", "q", (), True, False, (), (), ()),
    ]
    stats = abstention_accuracy(results)
    assert stats.correct == 3
    assert stats.total == 4
    assert stats.accuracy_pct == 75.0


def test_abstention_counts_false_abstentions() -> None:
    results = [
        QuestionResult("P-01", "q", ("107",), False, True, (), (), ()),
        QuestionResult("P-02", "q", ("118",), False, False, ("118",), ("118",), ()),
        QuestionResult("P-21", "q", (), True, True, (), (), ()),
    ]
    stats = abstention_accuracy(results)
    assert stats.false_abstentions == 1
    assert stats.correct == 1
    assert stats.total == 1


# --- report -----------------------------------------------------------------


def _result(idx: str, *, recall: float, abstained: bool = False) -> QuestionResult:
    """An in-law question whose hybrid recall@5 equals `recall`.

    Expected articles are 107 and 150; the embeddings-only baseline never
    retrieves either, so it is always strictly worse than the hybrid one.
    """
    retrieved = {
        1.0: ("107", "150", "100", "101", "102"),
        0.5: ("107", "100", "101", "102", "103"),
        0.0: ("100", "101", "102", "103", "104"),
    }[recall]
    return QuestionResult(
        id=idx,
        pregunta=f"pregunta {idx}",
        expected_articles=("107", "150"),
        should_abstain=False,
        abstained=abstained,
        citations=("107",),
        retrieved_articles=retrieved,
        embeddings_articles=("100", "101", "102"),
    )


def test_build_report_aggregates_all_metrics() -> None:
    results = [
        _result("P-01", recall=1.0),
        _result("P-02", recall=0.5),
        _result("P-21", recall=1.0),
    ]
    report = build_report(results)
    assert report["total"] == 3
    assert report["in_law"] == 3
    assert report["recall_at_5"] == pytest.approx(5 / 6)
    assert report["comparison"]["hybrid_recall_at_5"] == pytest.approx(5 / 6)
    assert report["comparison"]["embeddings_recall_at_5"] == 0.0
    assert (
        report["comparison"]["embeddings_recall_at_5"] < report["comparison"]["hybrid_recall_at_5"]
    )


def test_build_report_selects_worst_cases_first() -> None:
    results = [
        _result("P-01", recall=1.0),
        _result("P-02", recall=0.0),
        _result("P-03", recall=0.5),
    ]
    report = build_report(results)
    assert [case["id"] for case in report["worst_cases"]] == ["P-02", "P-03"]


def test_build_report_comparison_per_question_is_in_law_only() -> None:
    out_of_law = QuestionResult(
        id="P-21",
        pregunta="q",
        expected_articles=(),
        should_abstain=True,
        abstained=True,
        citations=(),
        retrieved_articles=(),
        embeddings_articles=("107",),
    )
    report = build_report([out_of_law])
    assert report["comparison"]["per_question"] == []
    assert report["in_law"] == 0


# --- citation failures and the JSON audit record ----------------------------


def _failing(idx: str, citations: tuple[str, ...], warning: str | None) -> QuestionResult:
    """An in-law, non-abstained answer whose citation `999` was not retrieved."""
    return QuestionResult(
        id=idx,
        pregunta=f"pregunta {idx}",
        expected_articles=("107",),
        should_abstain=False,
        abstained=False,
        citations=citations,
        retrieved_articles=("107", "100", "101", "102", "103"),
        embeddings_articles=(),
        warning=warning,
    )


def test_build_report_lists_answers_with_invalid_citations_and_their_warning() -> None:
    results = [
        _failing("P-03", ("107", "999"), "citas no respaldadas por el contexto: 999."),
        _result("P-01", recall=1.0),
    ]
    report = build_report(results)
    failures = report["citation_failures"]
    assert [item["id"] for item in failures] == ["P-03"]
    assert failures[0]["pregunta"] == "pregunta P-03"
    assert failures[0]["citas"] == ["107", "999"]
    assert failures[0]["warning"] == "citas no respaldadas por el contexto: 999."


def test_build_report_keeps_valid_and_abstained_answers_out_of_the_failure_list() -> None:
    abstained_in_law = QuestionResult(
        id="P-05",
        pregunta="pregunta P-05",
        expected_articles=("107",),
        should_abstain=False,
        abstained=True,
        citations=(),
        retrieved_articles=("107",),
        embeddings_articles=(),
    )
    report = build_report([_result("P-01", recall=1.0), abstained_in_law])
    assert report["citation_failures"] == []


def test_question_record_contains_every_audit_field() -> None:
    result = _failing("P-03", ("107", "999"), "aviso de validación")
    record = question_record(result)
    assert record == {
        "id": "P-03",
        "pregunta": "pregunta P-03",
        "articulos_esperados": ["107"],
        "articulos_recuperados": ["107", "100", "101", "102", "103"],
        "citas": ["107", "999"],
        "abstencion": False,
        "warning": "aviso de validación",
    }


def test_question_record_of_an_abstention_has_no_citations() -> None:
    result = QuestionResult(
        id="P-21",
        pregunta="pregunta P-21",
        expected_articles=(),
        should_abstain=True,
        abstained=True,
        citations=(),
        retrieved_articles=(),
        embeddings_articles=(),
    )
    record = question_record(result)
    assert record["citas"] == []
    assert record["abstencion"] is True
    assert record["articulos_esperados"] == []
