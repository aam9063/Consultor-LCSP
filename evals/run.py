"""Evaluation runner (CL-08, S6/S16, AC-10).

Thin CLI: reads `evals/preguntas.yaml`, runs every question through the
real services — real `NanLLMClient`, hybrid retrieval, generation with
validated citations and abstention — plus an embeddings-only baseline
(the vector branch alone), and writes `evals/results/<fecha>.md` with
recall@5, % of answers with all citations valid, % of correct
abstention, the worst cases and the hybrid-versus-embeddings-only
comparison (BRIEF section 12). It also writes
`evals/results/<fecha>.json` with one auditable record per question
(expected and retrieved articles, citations, abstention, service
warning), so a later run can be audited without spending quota again.
`--retrieval-compare` runs retrieval only, with no generation call at
all, compares the hybrid ranking against the embeddings-only baseline on
position metrics (recall@5, hit@1, MRR) and writes
`evals/results/<fecha>-retrieval.json` with the per-question rankings of
both modes, so any later analysis needs no quota.

Run from the repository root (the `app` package is the backend project):

    uv run --project backend python -m evals.run

Needs a migrated and ingested database (DATABASE_URL) and NAN_API_KEY.
This calls the real API and spends quota: it is never executed by the
test suite or by the default CI; only `workflow_dispatch` uses it.
"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import select

from app.adapters.llm import NanLLMClient
from app.db.models import Chunk
from app.db.session import dispose_engine, get_session_factory
from app.services.answers import AnswerResult, answer_question
from app.services.evaluation import (
    QuestionResult,
    RetrievalComparisonRow,
    build_report,
    compare_retrieval_modes,
    question_record,
    render_markdown,
    retrieval_compare_payload,
    score_ranges,
)
from app.services.retrieval import hybrid_search

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = REPO_ROOT / "evals" / "preguntas.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evals" / "results"
CORPUS = "LCSP consolidada (BOE-A-2017-12902, versión 2018-03-09)"


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Read and shape the annotated question set, failing early on a bad file."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path} must contain a non-empty list of questions")
    required = {"id", "pregunta", "articulos_esperados", "respuesta_referencia", "debe_abstenerse"}
    for index, entry in enumerate(data):
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError(f"{path}: entry #{index} does not match the annotated schema")
    return data


async def embeddings_only_articles(
    session: Any, llm: NanLLMClient, question: str, *, top_k: int
) -> tuple[str, ...]:
    """The vector branch alone, as the baseline for the comparison.

    This deliberately does not go through `hybrid_search`: the baseline
    must be isolated from the production retrieval path, so any future
    change there can never mask what embeddings alone achieve.
    """
    [vector] = await llm.embed([question])
    embedding_column = cast("Any", Chunk.embedding)
    statement = (
        select(Chunk.articulo)
        .where(embedding_column.is_not(None))
        .order_by(embedding_column.cosine_distance(cast("Any", vector)))
        .limit(top_k)
    )
    rows = (await session.execute(statement)).scalars().all()
    return tuple(str(articulo) for articulo in rows)


async def run_evaluation(
    questions: Sequence[dict[str, Any]], *, top_k: int
) -> list[QuestionResult]:
    """Answer every annotated question and collect its evaluation outcome."""
    llm = NanLLMClient()
    results: list[QuestionResult] = []
    async with get_session_factory()() as session:
        for entry in questions:
            question = str(entry["pregunta"])
            # Retrieval is measured on its own, before the answer path: when the
            # service abstains there are no retrieved chunks in the answer, and
            # measuring recall from that would hide a retrieval success behind
            # an abstention and make the hybrid/embeddings comparison unfair.
            retrieval = await hybrid_search(session, llm, question, top_k=top_k)
            answer: AnswerResult = await answer_question(session, llm, question, top_k=top_k)
            embeddings_articles = await embeddings_only_articles(
                session, llm, question, top_k=top_k
            )
            results.append(
                QuestionResult(
                    id=str(entry["id"]),
                    pregunta=question,
                    expected_articles=tuple(str(a) for a in entry["articulos_esperados"]),
                    should_abstain=bool(entry["debe_abstenerse"]),
                    abstained=answer.abstencion,
                    citations=tuple(
                        citation.articulo
                        if citation.apartado is None
                        else f"{citation.articulo}.{citation.apartado}"
                        for citation in answer.citas
                    ),
                    retrieved_articles=tuple(chunk.articulo for chunk in retrieval.chunks),
                    embeddings_articles=embeddings_articles,
                    warning=answer.warning,
                    best_score=retrieval.best_score,
                )
            )
    await dispose_engine()
    return results


async def calibrate_scores(
    questions: Sequence[dict[str, Any]], *, top_k: int
) -> tuple[list[QuestionResult], dict[str, dict[str, float]]]:
    """Retrieve every question and collect the rerank score distribution.

    Runs the retrieval pipeline only: no generation, no validation, so the
    abstention threshold can be chosen from real scores instead of a guess.
    """
    llm = NanLLMClient()
    results: list[QuestionResult] = []
    async with get_session_factory()() as session:
        for entry in questions:
            question = str(entry["pregunta"])
            retrieval = await hybrid_search(session, llm, question, top_k=top_k)
            results.append(
                QuestionResult(
                    id=str(entry["id"]),
                    pregunta=question,
                    expected_articles=tuple(str(a) for a in entry["articulos_esperados"]),
                    should_abstain=bool(entry["debe_abstenerse"]),
                    abstained=False,
                    citations=(),
                    retrieved_articles=tuple(chunk.articulo for chunk in retrieval.chunks),
                    best_score=retrieval.best_score,
                )
            )
    await dispose_engine()
    return results, score_ranges(results)


async def run_retrieval_compare(
    questions: Sequence[dict[str, Any]], *, top_k: int
) -> list[RetrievalComparisonRow]:
    """Retrieve every question with both modes; no generation call at all.

    The hybrid mode goes through `hybrid_search` (RRF + rerank + direct
    article); the baseline goes through `embeddings_only_articles`, the same
    isolated vector branch as the full evaluation, so any future change in
    `hybrid_search` can never mask what embeddings alone achieve. The
    per-question rankings are returned for `compare_retrieval_modes` and the
    `<fecha>-retrieval.json` audit file.
    """
    llm = NanLLMClient()
    rows: list[RetrievalComparisonRow] = []
    async with get_session_factory()() as session:
        for entry in questions:
            question = str(entry["pregunta"])
            retrieval = await hybrid_search(session, llm, question, top_k=top_k)
            embeddings_articles = await embeddings_only_articles(
                session, llm, question, top_k=top_k
            )
            rows.append(
                RetrievalComparisonRow(
                    id=str(entry["id"]),
                    pregunta=question,
                    expected_articles=tuple(str(a) for a in entry["articulos_esperados"]),
                    hybrid_articles=tuple(chunk.articulo for chunk in retrieval.chunks),
                    embeddings_articles=embeddings_articles,
                )
            )
    await dispose_engine()
    return rows


def write_report(results: Sequence[QuestionResult], *, output_dir: Path, today: str) -> Path:
    """Write `evals/results/<fecha>.md` and its per-question `<fecha>.json`.

    The JSON payload keeps one auditable record per question, so a later
    run can be inspected without spending quota again.
    """
    report = build_report(results)
    text = render_markdown(report, fecha=today, corpus=CORPUS)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{today}.md"
    destination.write_text(text, encoding="utf-8")
    audit = output_dir / f"{today}.json"
    records = [question_record(result) for result in results]
    audit.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report written to {destination}")
    print(f"per-question audit written to {audit}")
    print(f"recall@5: {report['recall_at_5'] * 100:.1f}%")
    print(f"valid citations: {report['valid_citations_pct']:.1f}%")
    print(f"correct abstention: {report['abstention']['correct']}/{report['abstention']['total']}")
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the LCSP evaluation (real API).")
    parser.add_argument("--preguntas", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", type=int, default=6)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--calibrate",
        action="store_true",
        help="retrieve only and report the rerank score spread (no generation)",
    )
    mode_group.add_argument(
        "--retrieval-compare",
        action="store_true",
        help="retrieve only with both modes and compare recall@5, hit@1 and MRR "
        "(no generation); writes <fecha>-retrieval.json",
    )
    args = parser.parse_args(argv)
    questions = load_questions(args.preguntas)
    if args.retrieval_compare:
        rows = asyncio.run(run_retrieval_compare(questions, top_k=args.top_k))
        today = datetime.now().strftime("%Y-%m-%d")
        comparison = compare_retrieval_modes(rows)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        destination = args.output_dir / f"{today}-retrieval.json"
        destination.write_text(
            json.dumps(
                retrieval_compare_payload(
                    rows, comparison, fecha=today, corpus=CORPUS, top_k=args.top_k
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"{'mode':<16} {'n':>3} {'recall@5':>9} {'hit@1':>7} {'mrr':>7}")
        for mode, label in (("hybrid", "hybrid"), ("embeddings", "embeddings-only")):
            metrics = comparison[mode]
            print(
                f"{label:<16} {metrics.questions:>3} "
                f"{metrics.recall_at_5 * 100:>8.1f}% {metrics.hit_at_1 * 100:>6.1f}% "
                f"{metrics.mrr:>7.3f}"
            )
        for mode, label in (("hybrid", "hybrid"), ("embeddings", "embeddings-only")):
            for case in comparison[mode].worst_cases:
                print(
                    f"worst ({label}) {case['id']}: mrr {case['mrr']:.3f}, "
                    f"hit@1 {case['hit_at_1']:.2f} — {case['pregunta']}"
                )
        print(f"retrieval comparison written to {destination}")
        return
    if args.calibrate:
        calibrated, ranges = asyncio.run(calibrate_scores(questions, top_k=args.top_k))
        today = datetime.now().strftime("%Y-%m-%d")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        destination = args.output_dir / f"{today}-scores.json"
        destination.write_text(
            json.dumps([question_record(r) for r in calibrated], ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        for group, label in (("in_law", "con base en la ley"), ("out_of_law", "fuera de la ley")):
            values = ranges[group]
            print(
                f"{label}: min {values['min']:.3f} | mediana {values['median']:.3f} | "
                f"max {values['max']:.3f} (n={int(values['count'])})"
            )
        print(f"scores written to {destination}")
        return
    results = asyncio.run(run_evaluation(questions, top_k=args.top_k))
    today = datetime.now().strftime("%Y-%m-%d")
    write_report(results, output_dir=args.output_dir, today=today)


if __name__ == "__main__":
    main()
