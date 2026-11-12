"""CLI entry point: `uv run python -m app.ingest data/lcsp/<fichero>` (CL-03, S1).

Default mode runs a real ingestion through `NanLLMClient` (needs
`NAN_API_KEY`). `--dry-run` parses the file and reports counts with zero
writes and zero API calls; it never constructs the real client, so it needs
no key. Both modes finish with one machine-readable JSON summary line.
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

from app.adapters.llm import LLMError, MissingAPIKeyError, NanLLMClient
from app.config import get_settings
from app.db.session import get_session_factory
from app.domain.lcsp_parser import parse_lcsp
from app.services.ingest import ingest_chunks


def _summary(payload: dict[str, object]) -> str:
    return json.dumps(payload)


async def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingest",
        description="Ingest a BOE consolidated LCSP XML file into Postgres",
    )
    parser.add_argument("path", type=Path, help="path to the consolidated LCSP XML")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and report counts only: no writes, no API calls, no key needed",
    )
    args = parser.parse_args(argv)

    path: Path = args.path
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    chunks = parse_lcsp(path.read_bytes())
    settings = get_settings()
    embedding_batches = math.ceil(len(chunks) / settings.embedding_batch_size) if chunks else 0

    if args.dry_run:
        print(
            _summary(
                {
                    "mode": "dry-run",
                    "file": str(path),
                    "chunks": len(chunks),
                    "embedding_batches": embedding_batches,
                }
            )
        )
        return 0

    try:
        llm = NanLLMClient(settings)
    except MissingAPIKeyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 3

    try:
        async with get_session_factory()() as session:
            result = await ingest_chunks(session, chunks, llm)
    except LLMError as error:
        print(f"error: {error}", file=sys.stderr)
        return 4

    print(
        _summary(
            {
                "mode": "ingest",
                "file": str(path),
                "chunks": len(chunks),
                "inserted": result.inserted,
                "updated": result.updated,
                "skipped": result.skipped,
                "embedded": result.embedded,
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(list(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
