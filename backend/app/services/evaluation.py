"""Pure evaluation metrics for the annotated question set (CL-08, S6/S16).

No SQLAlchemy, no AI SDK, no file reading: every function takes plain data,
so the metrics are deterministic and unit-testable with synthetic inputs.
The runner (`evals/run.py`) collects the real data — through the real
services and the real `NanLLMClient` — and calls `build_report` and
`render_markdown` from here to produce `evals/results/<fecha>.md`.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AbstentionStats",
    "ModeRetrievalMetrics",
    "QuestionResult",
    "RetrievalComparisonRow",
    "abstention_accuracy",
    "all_citations_valid",
    "build_report",
    "compare_retrieval_modes",
    "hit_at_1",
    "mean_reciprocal_rank",
    "question_record",
    "recall_at_k",
    "render_markdown",
    "retrieval_compare_payload",
]

# k of the recall@5 objective (AC-10) and how many worst cases to list.
RECALL_K = 5
WORST_CASES_LIMIT = 5

# AC-10 goals: recall@5 >= 85%, all citations valid >= 95%, correct
# abstention in at least 4 of the 5 out-of-law questions.
RECALL_GOAL_PCT = 85.0
VALID_CITATIONS_GOAL_PCT = 95.0
ABSTENTION_GOAL_CORRECT = 4
ABSTENTION_GOAL_TOTAL = 5

_ARTICLE_LABEL_RE = re.compile(r"^\d+(\.\d+)?$")


@dataclass(frozen=True, slots=True)
class QuestionResult:
    """The evaluation outcome for one annotated question.

    `citations` are the article labels cited by the answer (`"107"`,
    `"107.2"`); `retrieved_articles` is the hybrid ranking (best first) and
    `embeddings_articles` the embeddings-only baseline ranking, so the
    report can compare both recall@5 values (BRIEF section 12).
    """

    id: str
    pregunta: str
    expected_articles: tuple[str, ...]
    should_abstain: bool
    abstained: bool
    citations: tuple[str, ...]
    retrieved_articles: tuple[str, ...]
    embeddings_articles: tuple[str, ...] = ()
    warning: str | None = None
    # Best rerank score of the retrieval step, recorded independently of the
    # answer path so the abstention threshold can be calibrated from real runs.
    best_score: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalComparisonRow:
    """One annotated question with the full ranking of both retrieval modes.

    Unlike `QuestionResult`, this keeps the rankings even for out-of-law
    questions and carries no answer data: the comparison measures retrieval
    positions only, with no generation call.
    """

    id: str
    pregunta: str
    expected_articles: tuple[str, ...]
    hybrid_articles: tuple[str, ...]
    embeddings_articles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModeRetrievalMetrics:
    """Aggregate retrieval metrics of one mode over the judged questions."""

    mode: str
    questions: int
    recall_at_5: float
    hit_at_1: float
    mrr: float
    worst_cases: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class AbstentionStats:
    """Abstention behaviour over the out-of-law subset."""

    correct: int
    total: int
    false_abstentions: int

    @property
    def accuracy_pct(self) -> float:
        return _pct(self.correct, self.total)


def recall_at_k(expected: Sequence[str], retrieved_articles: Sequence[str], k: int) -> float:
    """Fraction of `expected` articles found within the first `k` retrieved.

    A question expecting no articles (out-of-law) cannot be partially
    recalled, so its recall is 1.0 by definition.
    """
    unique_expected = set(expected)
    if not unique_expected:
        return 1.0
    top_k = set(retrieved_articles[:k])
    return sum(1 for article in unique_expected if article in top_k) / len(unique_expected)


def hit_at_1(expected: Sequence[str], retrieved_articles: Sequence[str]) -> float:
    """1.0 when the first retrieved article is one of the expected ones, else 0.0.

    Only the first position counts: an expected article further down improves
    MRR, never hit@1. An empty ranking, or a question expecting no article
    (out-of-law), can never hit: 0.0.
    """
    if not retrieved_articles or not expected:
        return 0.0
    return 1.0 if retrieved_articles[0] in set(expected) else 0.0


def mean_reciprocal_rank(expected: Sequence[str], ranked: Sequence[str]) -> float:
    """Reciprocal rank of the ranking for one question (1/position, 1-indexed).

    The first expected article found in the ranking sets the reciprocal rank,
    so a question with several expected articles is satisfied by whichever
    comes first. 0.0 when no expected article appears, when the ranking is
    empty, or when nothing is expected; the comparison over questions averages
    this per-question value into the mean.
    """
    if not expected:
        return 0.0
    expected_set = set(expected)
    for position, article in enumerate(ranked, start=1):
        if article in expected_set:
            return 1.0 / position
    return 0.0


def compare_retrieval_modes(
    rows: Sequence[RetrievalComparisonRow],
) -> dict[str, ModeRetrievalMetrics]:
    """Aggregate recall@5, hit@1 and MRR for the hybrid and embeddings-only modes.

    Recall@5 alone cannot separate the modes when both find the same articles;
    hit@1 and MRR measure whether the better mode also puts the right article
    higher. Rows without expected articles (out-of-law) are kept in the
    payload but not judged: no mode can hit an article the question does not
    expect. Worst cases list the judged questions that are not perfect
    (mrr, hit@1 or recall below 1.0), worst first by ascending mrr, then
    hit@1, then recall@5, ties broken by id.
    """
    judged = [row for row in rows if row.expected_articles]
    return {
        "hybrid": _mode_metrics("hybrid", judged, [row.hybrid_articles for row in judged]),
        "embeddings": _mode_metrics(
            "embeddings", judged, [row.embeddings_articles for row in judged]
        ),
    }


def _mode_metrics(
    mode: str,
    judged: Sequence[RetrievalComparisonRow],
    rankings: Sequence[Sequence[str]],
) -> ModeRetrievalMetrics:
    recalls = [
        recall_at_k(row.expected_articles, ranking, RECALL_K)
        for row, ranking in zip(judged, rankings, strict=True)
    ]
    hits = [
        hit_at_1(row.expected_articles, ranking)
        for row, ranking in zip(judged, rankings, strict=True)
    ]
    mrrs = [
        mean_reciprocal_rank(row.expected_articles, ranking)
        for row, ranking in zip(judged, rankings, strict=True)
    ]
    imperfect = [
        (row, ranking, recall, hit, mrr)
        for row, ranking, recall, hit, mrr in zip(
            judged, rankings, recalls, hits, mrrs, strict=True
        )
        if recall < 1.0 or hit < 1.0 or mrr < 1.0
    ]
    imperfect.sort(key=lambda item: (item[4], item[3], item[2], item[0].id))
    worst_cases = tuple(
        {
            "id": row.id,
            "pregunta": row.pregunta,
            "recall_at_5": round(recall, 4),
            "hit_at_1": round(hit, 4),
            "mrr": round(mrr, 4),
            "recuperados": list(ranking),
        }
        for row, ranking, recall, hit, mrr in imperfect[:WORST_CASES_LIMIT]
    )
    return ModeRetrievalMetrics(
        mode=mode,
        questions=len(judged),
        recall_at_5=_mean(recalls),
        hit_at_1=_mean(hits),
        mrr=_mean(mrrs),
        worst_cases=worst_cases,
    )


def retrieval_compare_payload(
    rows: Sequence[RetrievalComparisonRow],
    comparison: dict[str, ModeRetrievalMetrics],
    *,
    fecha: str,
    corpus: str,
    top_k: int,
) -> dict[str, Any]:
    """The JSON payload persisted as `evals/results/<fecha>-retrieval.json`.

    Keeps the full per-question ranking of both modes, so any later analysis
    (positions, ties, new metrics) needs no new quota.
    """
    return {
        "fecha": fecha,
        "corpus": corpus,
        "top_k": top_k,
        "comparison": {
            mode: {
                "questions": metrics.questions,
                "recall_at_5": round(metrics.recall_at_5, 4),
                "hit_at_1": round(metrics.hit_at_1, 4),
                "mrr": round(metrics.mrr, 4),
                "worst_cases": list(metrics.worst_cases),
            }
            for mode, metrics in comparison.items()
        },
        "questions": [
            {
                "id": row.id,
                "pregunta": row.pregunta,
                "articulos_esperados": list(row.expected_articles),
                "hibrido": list(row.hybrid_articles),
                "embeddings": list(row.embeddings_articles),
            }
            for row in rows
        ],
    }


def all_citations_valid(answer: QuestionResult) -> bool:
    """Whether every citation of the answer points to a retrieved article.

    An abstention asserts nothing, so it cannot carry an invalid citation.
    A non-abstention answer must cite at least one article (every claim
    needs backing, BRIEF section 4) and every citation's base article must
    be among the retrieved chunks; `[art. X.Y]` matches article `X`.
    """
    if answer.abstained:
        return True
    if not answer.citations:
        return False
    retrieved = set(answer.retrieved_articles)
    return all(_base_article(citation) in retrieved for citation in answer.citations)


def abstention_accuracy(results: Sequence[QuestionResult]) -> AbstentionStats:
    """Correct abstentions over the out-of-law subset, plus false abstentions."""
    out_of_law = [result for result in results if result.should_abstain]
    correct = sum(1 for result in out_of_law if result.abstained)
    false_abstentions = sum(
        1 for result in results if not result.should_abstain and result.abstained
    )
    return AbstentionStats(
        correct=correct, total=len(out_of_law), false_abstentions=false_abstentions
    )


def build_report(results: Sequence[QuestionResult]) -> dict[str, Any]:
    """Aggregate every metric of the evaluation into a plain dictionary."""
    in_law = [result for result in results if not result.should_abstain]
    out_of_law_count = len(results) - len(in_law)

    hybrid_recalls = {
        r.id: recall_at_k(r.expected_articles, r.retrieved_articles, RECALL_K) for r in in_law
    }
    embeddings_recalls = {
        r.id: recall_at_k(r.expected_articles, r.embeddings_articles, RECALL_K) for r in in_law
    }
    recall_at_5 = _mean(hybrid_recalls.values())
    embeddings_recall_at_5 = _mean(embeddings_recalls.values())

    answers = [result for result in in_law if not result.abstained]
    valid_citations_pct = _pct(sum(1 for a in answers if all_citations_valid(a)), len(answers))

    citation_failures = [
        {
            "id": result.id,
            "pregunta": result.pregunta,
            "citas": list(result.citations),
            "warning": result.warning,
        }
        for result in answers
        if not all_citations_valid(result)
    ]

    stats = abstention_accuracy(results)
    ranges = score_ranges(results)

    worst_cases = [
        {
            "id": result.id,
            "pregunta": result.pregunta,
            "recall_at_5": round(hybrid_recalls[result.id], 4),
            "recuperados": list(result.retrieved_articles),
        }
        for result in sorted(
            (r for r in in_law if hybrid_recalls[r.id] < 1.0),
            key=lambda r: (hybrid_recalls[r.id], r.id),
        )[:WORST_CASES_LIMIT]
    ]
    per_question = [
        {
            "id": result.id,
            "pregunta": result.pregunta,
            "hibrido": round(hybrid_recalls[result.id], 4),
            "embeddings": round(embeddings_recalls[result.id], 4),
        }
        for result in sorted(in_law, key=lambda r: (hybrid_recalls[r.id], r.id))
    ]
    return {
        "total": len(results),
        "in_law": len(in_law),
        "out_of_law": out_of_law_count,
        "recall_at_5": recall_at_5,
        "valid_citations_pct": valid_citations_pct,
        "score_ranges": ranges,
        "abstention": {
            "correct": stats.correct,
            "total": stats.total,
            "accuracy_pct": stats.accuracy_pct,
            "false_abstentions": stats.false_abstentions,
        },
        "comparison": {
            "hybrid_recall_at_5": recall_at_5,
            "embeddings_recall_at_5": embeddings_recall_at_5,
            "delta_pct_points": round((recall_at_5 - embeddings_recall_at_5) * 100.0, 2),
            "per_question": per_question,
        },
        "citation_failures": citation_failures,
        "worst_cases": worst_cases,
    }


def question_record(result: QuestionResult) -> dict[str, Any]:
    """The auditable per-question payload persisted next to the report.

    One JSON object per annotated question with exactly what the run saw:
    expected and retrieved articles, the citations the model produced, the
    abstention flag and the service warning. A later run can therefore be
    audited without spending quota again.
    """
    return {
        "id": result.id,
        "pregunta": result.pregunta,
        "articulos_esperados": list(result.expected_articles),
        "articulos_recuperados": list(result.retrieved_articles),
        "citas": list(result.citations),
        "abstencion": result.abstained,
        "warning": result.warning,
        "best_score": result.best_score,
    }


def render_markdown(report: dict[str, Any], *, fecha: str, corpus: str) -> str:
    """Render the report dictionary as the `evals/results/<fecha>.md` document."""
    abstention = report["abstention"]
    comparison = report["comparison"]
    lines: list[str] = []
    lines.append(f"# Evaluación Consultor LCSP — {fecha}")
    lines.append("")
    lines.append(f"- Corpus: {corpus}")
    lines.append(
        f"- Preguntas: {report['total']} "
        f"({report['in_law']} con base en la ley, {report['out_of_law']} fuera de la ley)"
    )
    lines.append("")
    lines.append("## Métricas")
    lines.append(f"- Recall@5: {_fmt(report['recall_at_5'])}%")
    lines.append(f"- Respuestas con todas las citas válidas: {report['valid_citations_pct']:.1f}%")
    lines.append(
        f"- Abstención correcta: {abstention['correct']}/{abstention['total']} "
        f"({abstention['accuracy_pct']:.1f}%)"
    )
    lines.append(
        f"- Abstenciones indebidas (preguntas con base en la ley): {abstention['false_abstentions']}"
    )
    lines.append("")
    lines.append("## Objetivos (AC-10)")
    lines.extend(_goal_lines(report))
    lines.append("")
    lines.append("## Comparación: búsqueda híbrida frente a solo embeddings")
    lines.append(
        f"- Recall@5 híbrido: {_fmt(comparison['hybrid_recall_at_5'])}% "
        f"(solo embeddings: {_fmt(comparison['embeddings_recall_at_5'])}%, "
        f"diferencia: {comparison['delta_pct_points']:+.2f} puntos)"
    )
    lines.append("")
    lines.append("| Pregunta | Híbrido | Solo embeddings |")
    lines.append("| --- | --- | --- |")
    for item in comparison["per_question"]:
        lines.append(
            f"| {item['id']} — {item['pregunta']} | {item['hibrido']:.2f} | {item['embeddings']:.2f} |"
        )
    lines.append("")
    lines.append("## Respuestas sin citas válidas")
    if report["citation_failures"]:
        for failure in report["citation_failures"]:
            lines.append(
                f"- **{failure['id']}**: {failure['pregunta']} — citas producidas: "
                f"{', '.join(failure['citas']) or 'ninguna'}"
            )
            lines.append(f"  - Aviso del servicio: {failure['warning'] or 'ninguno'}")
    else:
        lines.append(
            "- Ninguna: todas las respuestas generadas citan artículos del contexto recuperado."
        )
    lines.append("")
    ranges = report.get("score_ranges")
    if ranges:
        lines.append("## Puntuaciones del rerank (evidencia para calibrar el umbral)")
        for group, label in (("in_law", "Con base en la ley"), ("out_of_law", "Fuera de la ley")):
            values = ranges[group]
            lines.append(
                f"- {label}: mínimo {values['min']:.3f}, mediana {values['median']:.3f}, "
                f"máximo {values['max']:.3f} (n={int(values['count'])})"
            )
        lines.append(
            "  - Un umbral por debajo del mínimo de las preguntas con base evita abstenerse "
            "en preguntas respondibles; compáralo con el máximo de las que están fuera."
        )
        lines.append("")

    lines.append("## Peores casos")
    if report["worst_cases"]:
        for case in report["worst_cases"]:
            lines.append(
                f"- **{case['id']}** (recall@5 {case['recall_at_5']:.2f}): {case['pregunta']} "
                f"— recuperados: {', '.join(case['recuperados']) or 'ninguno'}"
            )
    else:
        lines.append("- Ninguna: todas las preguntas con base en la ley alcanzaron recall@5 = 1.0.")
    lines.append("")
    return "\n".join(lines)


def _goal_lines(report: dict[str, Any]) -> list[str]:
    abstention = report["abstention"]
    recall_pct = report["recall_at_5"] * 100.0
    lines = [
        f"- Recall@5 >= 85%: objetivo **{'cumplido' if recall_pct >= RECALL_GOAL_PCT else 'no cumplido'}** "
        f"({recall_pct:.1f}%).",
        f"- Citas válidas >= 95%: objetivo "
        f"**{'cumplido' if report['valid_citations_pct'] >= VALID_CITATIONS_GOAL_PCT else 'no cumplido'}** "
        f"({report['valid_citations_pct']:.1f}%).",
        f"- Abstención correcta: al menos 4 de 5 preguntas fuera de la ley — "
        f"**{'cumplido' if abstention['correct'] >= ABSTENTION_GOAL_CORRECT else 'no cumplido'}** "
        f"({abstention['correct']}/{abstention['total']}).",
    ]
    if recall_pct < RECALL_GOAL_PCT and report["worst_cases"]:
        ids = ", ".join(str(case["id"]) for case in report["worst_cases"])
        lines.append(
            f"  - Por qué no se alcanza: ver Peores casos ({ids}); el artículo esperado "
            "no entró en el top-5 recuperado."
        )
    if abstention["correct"] < ABSTENTION_GOAL_CORRECT:
        lines.append(
            "  - Por qué no se alcanza: el umbral de abstención no bastó para detectar "
            "las preguntas fuera de la ley."
        )
    if report["valid_citations_pct"] < VALID_CITATIONS_GOAL_PCT:
        lines.append(
            "  - Por qué no se alcanza: hay respuestas que citan artículos fuera del "
            "contexto recuperado; revisar la validación de citas."
        )
    return lines


def score_ranges(results: Sequence[QuestionResult]) -> dict[str, dict[str, float]]:
    """Best rerank score spread per group, to calibrate the abstention threshold.

    Reported, never used to decide anything here: choosing a threshold is a
    product decision the operator makes from this evidence.
    """

    def summarize(group: Sequence[QuestionResult]) -> dict[str, float]:
        scores = sorted(r.best_score for r in group if r.best_score is not None)
        if not scores:
            return {"min": 0.0, "median": 0.0, "max": 0.0, "count": 0.0}
        middle = len(scores) // 2
        median = (
            scores[middle] if len(scores) % 2 == 1 else (scores[middle - 1] + scores[middle]) / 2
        )
        return {
            "min": scores[0],
            "median": median,
            "max": scores[-1],
            "count": float(len(scores)),
        }

    return {
        "in_law": summarize([r for r in results if not r.should_abstain]),
        "out_of_law": summarize([r for r in results if r.should_abstain]),
    }


def _base_article(citation: str) -> str:
    """The article part of a citation label: `"107.2"` -> `"107"`."""
    if not _ARTICLE_LABEL_RE.match(citation):
        raise ValueError(f"citation label is not an article number: {citation!r}")
    return citation.split(".", maxsplit=1)[0]


def _pct(numerator: int, denominator: int) -> float:
    """Percentage rounded to one decimal; 100.0 when there is nothing to judge."""
    if denominator == 0:
        return 100.0
    return round(100.0 * numerator / denominator, 1)


def _mean(values: Iterable[float]) -> float:
    numbers = list(values)
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _fmt(fraction: float) -> str:
    return f"{fraction * 100.0:.1f}".rstrip("0").rstrip(".")
