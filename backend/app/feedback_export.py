"""Export negative votes as evaluation-set candidates (S8, S5/FB-03).

`python -m app.feedback_export [--output PATH]` reads the negative votes
(`voto = -1`) from the database and renders YAML entries shaped like
`evals/preguntas.yaml` (id, pregunta, empty `articulos_esperados`, the
stored answer as `respuesta_referencia`, `debe_abstenerse: false`) so a
human can annotate them. It never writes `evals/preguntas.yaml`: it
proposes, it does not decide. No AI API is involved, so it needs no key.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback
from app.db.session import get_session_factory


def render_yaml(votes: Sequence[Feedback]) -> str:
    """Render negative votes as `evals/preguntas.yaml` shaped entries.

    The article list is deliberately empty: proposing the articles would be
    deciding; annotating them is the human's job (S5).
    """
    entries = [
        {
            "id": f"FB-{vote.id:03d}",
            "pregunta": vote.pregunta,
            "articulos_esperados": [],
            "respuesta_referencia": vote.respuesta,
            "debe_abstenerse": False,
        }
        for vote in votes
    ]
    # `sort_keys` keeps the evals field order; `width` avoids line wrapping
    # so the output stays a stable, diffable one-entry-per-block document.
    return yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=10**6)


async def _collect_negative_votes(session: AsyncSession) -> Sequence[Feedback]:
    result = await session.execute(
        select(Feedback)
        .where(Feedback.voto == -1)
        .order_by(Feedback.creada_en.desc(), Feedback.id.desc())
    )
    return result.scalars().all()


async def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.feedback_export",
        description=(
            "Dump the negative user votes as evals/preguntas.yaml-shaped "
            "candidates for human annotation (never writes evals/preguntas.yaml)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the YAML to this path instead of stdout",
    )
    args = parser.parse_args(argv)

    async with get_session_factory()() as session:
        votes = await _collect_negative_votes(session)
    rendered = render_yaml(votes)

    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(list(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
