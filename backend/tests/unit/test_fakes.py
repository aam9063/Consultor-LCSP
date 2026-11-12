"""Unit tests for the shared `FakeLLMClient` double (CL-04, S2/S11).

The rerank scores must be deterministic and derived from the documents so
tests can assert exact orders; an optional override map pins scores for
specific document texts.
"""

from tests.fakes import FakeLLMClient


async def test_rerank_returns_one_score_per_document_in_input_order() -> None:
    llm = FakeLLMClient()
    documents = ["primero", "segundo", "tercero"]

    scores = await llm.rerank("consulta", documents)

    assert len(scores) == len(documents)
    assert all(0.0 <= score < 1.0 for score in scores)
    assert await llm.rerank("consulta", documents) == scores  # deterministic


async def test_rerank_scores_depend_on_the_document_not_its_position() -> None:
    llm = FakeLLMClient()

    first = await llm.rerank("q", ["alpha", "beta"])
    second = await llm.rerank("q", ["beta", "alpha"])

    assert first[0] == second[1]
    assert first[1] == second[0]


async def test_rerank_prefers_configured_scores_for_exact_documents() -> None:
    llm = FakeLLMClient(rerank_scores={"articulo uno": 0.1, "articulo dos": 0.9})

    scores = await llm.rerank("q", ["articulo uno", "articulo dos"])

    assert scores == [0.1, 0.9]
    assert llm.rerank_calls == [("q", ["articulo uno", "articulo dos"])]


async def test_rerank_with_no_documents_makes_no_recorded_call() -> None:
    llm = FakeLLMClient()

    assert await llm.rerank("q", []) == []
    assert llm.rerank_calls == []
