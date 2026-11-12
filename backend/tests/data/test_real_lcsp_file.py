"""Explicit data-backed checks against the real BOE consolidated LCSP XML.

`data/lcsp/` is not committed, so CI has no XML and the default suites
(`pytest` → `tests/unit`) must stay green on a clean clone. This file is
NOT in `testpaths`: it runs only when invoked explicitly with
`uv run pytest tests/data`, and it skips itself when the file is absent.
"""

from pathlib import Path

import pytest

from app.domain.lcsp_parser import parse_lcsp

pytestmark = pytest.mark.data

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_FILE = REPO_ROOT / "data" / "lcsp" / "lcsp-consolidada.xml"


def test_real_lcsp_file_parses_with_correct_encoding_and_metadata() -> None:
    if not REAL_FILE.exists():
        pytest.skip("data/lcsp/lcsp-consolidada.xml is not present in this clone")

    chunks = parse_lcsp(REAL_FILE.read_bytes())

    assert len(chunks) > 400
    article_107 = [chunk for chunk in chunks if chunk.articulo == "107"]
    assert article_107, "article 107 must exist in the real consolidated text"
    first_107 = article_107[0]
    # Decoding must yield real Spanish text, not mojibake.
    assert first_107.titulo.startswith("Artículo 107.")
    assert "garantía definitiva" in first_107.texto
    assert first_107.url == ("https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-19")
    assert first_107.fecha_version == "2018-03-09"
    assert any(chunk.articulo.startswith("DA") for chunk in chunks), (
        "disposiciones adicionales must be parsed"
    )
    assert any(chunk.articulo.startswith("DT") for chunk in chunks), (
        "disposiciones transitorias must be parsed"
    )
