"""Unit tests for the `python -m app.ingest` CLI (CL-03, S1).

`--dry-run` must parse and report only: zero DB writes and zero API calls,
and it must not even construct `NanLLMClient`. The DB and the real client
are replaced by sentinels that fail the test the moment they are touched.
"""

import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.ingest import main

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "small_lcsp.xml"


def _forbid_constructing(module: Any, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = type(name, (), {"__init__": _forbidden})
    monkeypatch.setattr(module, name, sentinel)


def _forbidden(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("dry-run must not touch the DB or the real client")


def test_dry_run_reports_counts_without_writes_or_api_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import app.ingest as ingest_module

    _forbid_constructing(ingest_module, "NanLLMClient", monkeypatch)
    _forbid_constructing(ingest_module, "get_session_factory", monkeypatch)

    exit_code = main(["--dry-run", str(FIXTURE)])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["mode"] == "dry-run"
    assert summary["chunks"] == 2  # fixture: two whole-article chunks
    default_settings = Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings accepts this at runtime
    expected_batches = math.ceil(summary["chunks"] / default_settings.embedding_batch_size)
    assert summary["embedding_batches"] == expected_batches


def test_dry_run_needs_no_api_key(capsys: pytest.CaptureFixture[str]) -> None:
    # No monkeypatching at all: with no NAN_API_KEY in the environment a dry
    # run must still succeed because the real client is never constructed.
    exit_code = main(["--dry-run", str(FIXTURE)])

    assert exit_code == 0
    assert '"mode": "dry-run"' in capsys.readouterr().out


def test_missing_file_reports_a_clear_error(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--dry-run", "does-not-exist.xml"])

    assert exit_code == 2
    assert "does-not-exist.xml" in capsys.readouterr().err


def test_real_run_without_api_key_fails_with_a_typed_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import app.ingest as ingest_module

    monkeypatch.setattr(
        ingest_module,
        "get_settings",
        # Init kwargs win over env/.env in pydantic-settings, so no key leaks in.
        lambda: Settings(nan_api_key=SecretStr("")),
    )
    monkeypatch.setattr(ingest_module, "get_session_factory", _forbidden)

    exit_code = main([str(FIXTURE)])

    assert exit_code == 3
    assert "NAN_API_KEY" in capsys.readouterr().err
