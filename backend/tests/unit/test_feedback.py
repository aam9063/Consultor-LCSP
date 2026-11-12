"""Unit tests for user feedback (S8, FB-01/FB-02/FB-03).

No database is needed here: the typed 422 cases short-circuit in the router
before any query, the fingerprint and validators are pure functions, and the
export command is tested against a fake session factory.
"""

from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.feedback_export as feedback_export
from app.db.models import Feedback
from app.feedback_export import render_yaml
from app.main import create_app
from app.services.feedback import (
    CitaInvalidaError,
    VotoInvalidoError,
    huella_de,
    normalize_citas,
    normalize_voto,
)

# --- FB-01/S3: the fingerprint is the idempotency key ------------------------


def test_fingerprint_is_stable_and_distinguishes_answers() -> None:
    first = huella_de("¿Cuál es la garantía definitiva?", "El art. 107 fija el 5%.")
    second = huella_de("¿Cuál es la garantía definitiva?", "El art. 107 fija el 5%.")
    other_answer = huella_de("¿Cuál es la garantía definitiva?", "El art. 106 no la exige.")
    other_question = huella_de("¿Y la provisional?", "El art. 107 fija el 5%.")

    assert first == second
    assert first != other_answer
    assert first != other_question
    assert len(first) == 64
    int(first, 16)  # sha256 hex digest


# --- FB-02/S4: vote validation rejects everything but 1 and -1 ---------------


@pytest.mark.parametrize("good", [1, -1])
def test_voto_validation_accepts_exactly_1_and_minus_1(good: int) -> None:
    assert normalize_voto(good) == good


@pytest.mark.parametrize("bad", [0, 2, -2, 1.5, 1.0, "alto", "1", True, None])
def test_voto_validation_rejects_out_of_range_and_non_integers(bad: object) -> None:
    with pytest.raises(VotoInvalidoError):
        normalize_voto(bad)  # type: ignore[arg-type]  # junk must be rejected at runtime


# --- FB-02/S4: citation shape is validated before anything is written --------


def test_citas_validation_passes_well_formed_citations_through() -> None:
    citas = normalize_citas(
        [{"articulo": "107", "apartado": None}, {"articulo": "107.2", "apartado": "b)"}]
    )
    assert citas == [{"articulo": "107", "apartado": None}, {"articulo": "107.2", "apartado": "b)"}]


def test_citas_validation_accepts_an_empty_list_for_an_abstention_vote() -> None:
    assert normalize_citas([]) == []


@pytest.mark.parametrize(
    "bad",
    [
        [{"articulo": ""}],
        [{"apartado": "b)"}],
        [{"articulo": 107}],
        [{"articulo": "107", "extra": "x"}],
        ["art. 107"],
        [{"articulo": "107", "apartado": 2}],
    ],
)
def test_citas_validation_rejects_malformed_citations(bad: object) -> None:
    with pytest.raises(CitaInvalidaError):
        normalize_citas(bad)  # type: ignore[arg-type]  # junk must be rejected at runtime


# --- FB-02/S4: the typed 422 envelope, without touching any database ---------


def _body(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pregunta": "¿Cuál es la garantía definitiva?",
        "respuesta": "El art. 107 fija el 5% del precio final ofertado.",
        "citas": [{"articulo": "107", "apartado": None}],
        "modelo": "deepseek-v4-flash",
        "voto": -1,
        "comentario": None,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"pregunta": "   "}, "pregunta_ausente"),
        ({"pregunta": None}, "pregunta_ausente"),
        ({"respuesta": ""}, "respuesta_ausente"),
        ({"modelo": "  "}, "modelo_ausente"),
        ({"voto": 0}, "voto_invalido"),
        ({"voto": 2}, "voto_invalido"),
        ({"voto": 1.5}, "voto_invalido"),
        ({"voto": "alto"}, "voto_invalido"),
        ({"citas": [{"articulo": 107}]}, "cita_invalida"),
        ({"citas": [{"apartado": "b)"}]}, "cita_invalida"),
    ],
)
async def test_invalid_feedback_returns_the_typed_422_envelope(
    overrides: dict[str, Any], code: str
) -> None:
    app: FastAPI = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/feedback", json=_body(**overrides))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == code
    assert error["message"]


# --- FB-03/S5: the export renders evaluation-set shaped YAML -----------------


def _vote(id_: int, pregunta: str, respuesta: str) -> Feedback:
    return Feedback(
        id=id_,
        huella=f"huella-{id_}",
        pregunta=pregunta,
        respuesta=respuesta,
        citas=[],
        modelo="deepseek-v4-flash",
        voto=-1,
    )


def test_export_renders_evaluation_entries_for_negative_votes() -> None:
    rendered = render_yaml(
        [
            _vote(7, "Pregunta siete", "Respuesta siete"),
            _vote(3, "Pregunta tres", "Respuesta tres"),
        ]
    )

    assert rendered == (
        "- id: FB-007\n"
        "  pregunta: Pregunta siete\n"
        "  articulos_esperados: []\n"
        "  respuesta_referencia: Respuesta siete\n"
        "  debe_abstenerse: false\n"
        "- id: FB-003\n"
        "  pregunta: Pregunta tres\n"
        "  articulos_esperados: []\n"
        "  respuesta_referencia: Respuesta tres\n"
        "  debe_abstenerse: false\n"
    )
    assert yaml.safe_load(rendered) == [
        {
            "id": "FB-007",
            "pregunta": "Pregunta siete",
            "articulos_esperados": [],
            "respuesta_referencia": "Respuesta siete",
            "debe_abstenerse": False,
        },
        {
            "id": "FB-003",
            "pregunta": "Pregunta tres",
            "articulos_esperados": [],
            "respuesta_referencia": "Respuesta tres",
            "debe_abstenerse": False,
        },
    ]


# --- FB-03/S5: the CLI wires the DB read to the YAML output ------------------


class _FakeResult:
    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Feedback]:
        return _fake_votes


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult()


class _FakeSessionFactory:
    def __call__(self) -> _FakeSession:
        return _FakeSession()


_fake_votes: list[Feedback] = []


def _install_fake_session(monkeypatch: pytest.MonkeyPatch, votes: list[Feedback]) -> None:
    global _fake_votes
    _fake_votes = votes

    def _factory() -> _FakeSessionFactory:
        return _FakeSessionFactory()

    monkeypatch.setattr(feedback_export, "get_session_factory", _factory)


def test_export_cli_prints_yaml_of_negative_votes_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_fake_session(
        monkeypatch,
        [
            _vote(5, "Pregunta cinco", "Respuesta cinco"),
            _vote(2, "Pregunta dos", "Respuesta dos"),
        ],
    )

    exit_code = feedback_export.main([])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert yaml.safe_load(out) == [
        {
            "id": "FB-005",
            "pregunta": "Pregunta cinco",
            "articulos_esperados": [],
            "respuesta_referencia": "Respuesta cinco",
            "debe_abstenerse": False,
        },
        {
            "id": "FB-002",
            "pregunta": "Pregunta dos",
            "articulos_esperados": [],
            "respuesta_referencia": "Respuesta dos",
            "debe_abstenerse": False,
        },
    ]


def test_export_cli_writes_the_output_path_and_nothing_to_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    from pathlib import Path

    _install_fake_session(monkeypatch, [_vote(1, "Pregunta una", "Respuesta una")])
    target = Path(str(tmp_path)) / "candidatos.yaml"

    exit_code = feedback_export.main(["--output", str(target)])

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    assert target.read_text(encoding="utf-8") == render_yaml(
        [_vote(1, "Pregunta una", "Respuesta una")]
    )


def test_export_cli_never_imports_the_llm_stack() -> None:
    # S5: the export must not need the AI API; it must not even import it.
    assert not hasattr(feedback_export, "NanLLMClient")
    assert not hasattr(feedback_export, "LLMClient")
