"""Evaluation runner (CL-08, S6/S16, AC-10).

Thin CLI: reads `evals/preguntas.yaml`, runs every question through the
real services — real `NanLLMClient`, hybrid retrieval, generation with
validated citations and abstention — plus an embeddings-only baseline
(the vector branch alone), and writes `evals/results/<fecha>.md` with
recall@5, % of answers with all citations valid, % of correct
abstention, the worst cases and the hybrid-versus-embeddings-only
comparison (BRIEF section 12).

Run from the repository root (the `app` package is the backend project):

    uv run --project backend python -m evals.run

Needs a migrated and ingested database (DATABASE_URL) and NAN_API_KEY.
This calls the real API and spends quota: it is never executed by the
test suite or by the default CI; only `workflow_dispatch` uses it.
"""

import argparse
import asyncio
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
from app.services.evaluation import QuestionResult, build_report, render_markdown

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


async def run_evaluation(questions: Sequence[dict[str, Any]], *, top_k: int) -> list[QuestionResult]:
    """Answer every annotated question and collect its evaluation outcome."""
    llm = NanLLMClient()
    results: list[QuestionResult] = []
    async with get_session_factory()() as session:
        for entry in questions:
            question = str(entry["pregunta"])
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
                    retrieved_articles=tuple(chunk.articulo for chunk in answer.chunks),
                    embeddings_articles=embeddings_articles,
                )
            )
    await dispose_engine()
    return results


def write_report(
    results: Sequence[QuestionResult], *, output_dir: Path, today: str
) -> Path:
    """Build, render and write `evals/results/<fecha>.md`; print the summary."""
    report = build_report(results)
    text = render_markdown(report, fecha=today, corpus=CORPUS)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{today}.md"
    destination.write_text(text, encoding="utf-8")
    print(f"report written to {destination}")
    print(f"recall@5: {report['recall_at_5'] * 100:.1f}%")
    print(f"valid citations: {report['valid_citations_pct']:.1f}%")
    print(
        "correct abstention: "
        f"{report['abstention']['correct']}/{report['abstention']['total']}"
    )
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the LCSP evaluation (real API).")
    parser.add_argument("--preguntas", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args(argv)
    questions = load_questions(args.preguntas)
    results = asyncio.run(run_evaluation(questions, top_k=args.top_k))
    today = datetime.now().strftime("%Y-%m-%d")
    write_report(results, output_dir=args.output_dir, today=today)


if __name__ == "__main__":
    main()
