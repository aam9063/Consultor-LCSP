"""Markdown rendering of the evaluation report (CL-08, S6/S16): unit tests."""

from app.services.evaluation import QuestionResult, build_report, render_markdown

REPORT: dict[str, object] = build_report(
    [
        QuestionResult(
            id="P-01",
            pregunta="penalidades",
            expected_articles=("193",),
            should_abstain=False,
            abstained=False,
            citations=("193",),
            retrieved_articles=("193", "107", "118", "149", "159", "215"),
            embeddings_articles=("193", "107", "118"),
        ),
        QuestionResult(
            id="P-02",
            pregunta="clasificacion",
            expected_articles=("77", "159"),
            should_abstain=False,
            abstained=False,
            citations=("77",),
            retrieved_articles=("77", "107", "118", "149", "215", "159"),
            embeddings_articles=("77", "107", "118"),
        ),
        QuestionResult(
            id="P-21",
            pregunta="iva",
            expected_articles=(),
            should_abstain=True,
            abstained=True,
            citations=(),
            retrieved_articles=(),
            embeddings_articles=(),
        ),
    ]
)


def test_markdown_contains_every_required_section() -> None:
    text = render_markdown(REPORT, fecha="2026-11-13", corpus="LCSP consolidada")
    assert "2026-11-13" in text
    assert "LCSP consolidada" in text
    assert "Recall@5" in text
    assert "citas" in text.lower()
    assert "abstenci" in text.lower()
    assert "Peores casos" in text


def test_markdown_shows_hybrid_vs_embeddings_numbers() -> None:
    text = render_markdown(REPORT, fecha="2026-11-13", corpus="LCSP consolidada")
    comparison_section = text.split("solo embeddings")[-1]
    assert "Híbrido" in text
    assert "Solo embeddings" in text
    # Every in-law question appears in the comparison table, out-of-law ones do not.
    assert "P-01" in comparison_section
    assert "P-02" in comparison_section
    assert "P-21" not in comparison_section


def test_markdown_reports_goals_and_explains_misses() -> None:
    text = render_markdown(REPORT, fecha="2026-11-13", corpus="LCSP consolidada")
    assert "85%" in text
    assert "95%" in text
    assert "4 de 5" in text
    # P-02 has recall 0.5 < 1, so a miss explanation with the offending question shows up.
    assert "P-02" in text.split("Peores casos")[1]


def test_markdown_lists_worst_cases_with_recall() -> None:
    text = render_markdown(REPORT, fecha="2026-11-13", corpus="LCSP consolidada")
    worst_section = text.split("Peores casos")[1]
    assert "P-02" in worst_section
    assert "0.5" in worst_section


# --- citation failure section (why valid citations are below 100%) ----------


CITATION_WARNING = "Afirmaciones con citas no respaldadas por el contexto recuperado: art. 999."

FAILING_REPORT: dict[str, object] = build_report(
    [
        QuestionResult(
            id="P-04",
            pregunta="importe del contrato menor",
            expected_articles=("118",),
            should_abstain=False,
            abstained=False,
            citations=("118", "999"),
            retrieved_articles=("118", "107", "149", "159", "215", "101"),
            embeddings_articles=("118", "107", "149"),
            warning=CITATION_WARNING,
        ),
        QuestionResult(
            id="P-01",
            pregunta="penalidades",
            expected_articles=("193",),
            should_abstain=False,
            abstained=False,
            citations=("193",),
            retrieved_articles=("193", "107", "118", "149", "159", "215"),
            embeddings_articles=("193", "107", "118"),
        ),
    ]
)


def _citation_section(text: str) -> str:
    """The markdown chunk between the citation-failure heading and the next one."""
    tail = text.split("## Respuestas sin citas válidas")[1]
    return tail.split("\n## ")[0]


def test_markdown_renders_failing_citation_section_with_cause() -> None:
    text = render_markdown(FAILING_REPORT, fecha="2026-11-14", corpus="LCSP consolidada")
    section = _citation_section(text)
    assert "P-04" in section
    assert "importe del contrato menor" in section
    assert "999" in section
    assert CITATION_WARNING in section
    # Valid answers are not listed as failures.
    assert "P-01" not in section


def test_markdown_states_no_citation_failures_when_everything_is_valid() -> None:
    text = render_markdown(REPORT, fecha="2026-11-13", corpus="LCSP consolidada")
    section = _citation_section(text)
    assert "Ninguna" in section
    assert "P-01" not in section
