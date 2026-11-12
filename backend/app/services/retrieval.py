"""Hybrid retrieval over ingested LCSP chunks (CL-04, S2/S10/S11).

Vector branch: exact pgvector search with cosine distance (`embedding <=> :v`,
ascending). With 4.096 dimensions the HNSW/IVFFlat indexes do not apply, so
the scan is exact and cheap at ~500 chunks. Lexical branch: Postgres full
text search over the generated `tsv` (`spanish_unaccent`), ordered by
`ts_rank`. Both rankings fuse with Reciprocal Rank Fusion, the top candidates
are reranked with the `rerank` model, and a question naming an article
("¿qué dice el artículo 107?") retrieves that article's chunks directly,
ahead of the hybrid ranking (AC-04).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import LLMClient
from app.db.models import Chunk
from app.domain.ranking import extract_article_number, ranked_indices, reciprocal_rank_fusion

logger = logging.getLogger(__name__)

BRANCH_DIRECT = "direct"
BRANCH_LEXICAL = "lexical"
BRANCH_VECTOR = "vector"

# Candidates fetched per branch before fusion. The corpus is ~500 chunks and
# the vector scan is exact, so a wide-but-bounded pool keeps RRF meaningful
# while the reranker only ever sees the best `top_k * 2` fused candidates.
_CANDIDATE_POOL = 24


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One chunk of the final ranking, with its rerank score and branches."""

    id: int
    articulo: str
    apartado: str | None
    titulo: str
    url: str
    texto: str
    score: float
    branches: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """The final ranking for one query.

    `best_score` is the highest rerank score among the returned chunks (CL-05
    uses it for the abstention threshold); `None` when nothing was retrieved.
    """

    query: str
    chunks: list[RetrievedChunk]
    best_score: float | None


async def hybrid_search(
    session: AsyncSession,
    llm: LLMClient,
    query: str,
    *,
    top_k: int = 6,
) -> RetrievalResult:
    """Retrieve the best `top_k` chunks for `query` (hybrid + rerank + direct).

    Both branch rankings fuse with RRF; the best `top_k * 2` fused candidates
    are reranked and the best `top_k` kept. When the question names an
    article, its chunks come first, ahead of the hybrid results (AC-04), and
    the rest is still filled by the hybrid ranking. Chunks outside the
    candidate pool never appear, and rows with a NULL embedding never break
    the query.
    """
    [query_vector] = await llm.embed([query])
    vector_ids = await _vector_search(session, query_vector)
    lexical_ids = await _lexical_search(session, query)
    fused = reciprocal_rank_fusion(
        [[str(chunk_id) for chunk_id in vector_ids], [str(chunk_id) for chunk_id in lexical_ids]]
    )
    fused_ids = [int(item.id) for item in fused[: top_k * 2]]

    article = extract_article_number(query)
    direct_ids = (
        await _article_chunk_ids(session, article, limit=top_k) if article is not None else []
    )

    ordered_ids = _without_duplicates([*direct_ids, *fused_ids])
    rows = await _fetch_chunks(session, ordered_ids)
    # Candidates that vanished between the branch queries and this fetch
    # (e.g. a concurrent re-ingest) drop out everywhere to keep scores aligned.
    ordered_ids = [chunk_id for chunk_id in ordered_ids if chunk_id in rows]
    if not ordered_ids:
        return RetrievalResult(query=query, chunks=[], best_score=None)
    scores = await llm.rerank(query, [rows[chunk_id].texto for chunk_id in ordered_ids])

    # Direct chunks first (best rerank score among them, ties by apartado
    # order); the remaining slots come from the reranked hybrid candidates,
    # tied along the fused rank, never along dict order.
    direct_set = set(direct_ids)
    direct_positions = ranked_indices(scores[: len(direct_ids)])
    fused_positions = ranked_indices(scores[len(direct_ids) :])

    final_ids = [ordered_ids[position] for position in direct_positions[:top_k]]
    for position in fused_positions:
        if len(final_ids) >= top_k:
            break
        chunk_id = ordered_ids[len(direct_ids) + position]
        if chunk_id in direct_set:
            continue
        final_ids.append(chunk_id)

    score_by_id = dict(zip(ordered_ids, scores, strict=True))
    chunks = [
        RetrievedChunk(
            id=row.id,
            articulo=row.articulo,
            apartado=row.apartado,
            titulo=row.titulo,
            url=row.url,
            texto=row.texto,
            score=score_by_id[chunk_id],
            branches=_branches_for(chunk_id, direct_set, vector_ids, lexical_ids),
        )
        for chunk_id, row in ((chunk_id, rows[chunk_id]) for chunk_id in final_ids)
    ]
    best_score = max(chunk.score for chunk in chunks) if chunks else None
    logger.info(
        "hybrid search query_chars=%d vector_candidates=%d lexical_candidates=%d "
        "direct_article=%s returned=%d",
        len(query),
        len(vector_ids),
        len(lexical_ids),
        article,
        len(chunks),
    )
    return RetrievalResult(query=query, chunks=chunks, best_score=best_score)


async def _vector_search(session: AsyncSession, vector: list[float]) -> list[int]:
    """Exact nearest-neighbour ids by ascending cosine distance (`<=>`).

    `Chunk.embedding` must be cast to `Any`: pgvector's cosine_distance lives
    on its custom Comparator, which SQLAlchemy's typed Mapped descriptors do
    not expose to mypy.
    """
    embedding_column = cast("Any", Chunk.embedding)
    statement = (
        select(Chunk.id)
        .where(embedding_column.is_not(None))
        .order_by(embedding_column.cosine_distance(cast("Any", vector)))
        .limit(_CANDIDATE_POOL)
    )
    return list((await session.execute(statement)).scalars())


async def _lexical_search(session: AsyncSession, query: str) -> list[int]:
    """Ids whose generated `tsv` matches the query, best `ts_rank` first."""
    tsquery = func.plainto_tsquery("spanish_unaccent", query)
    statement = (
        select(Chunk.id)
        .where(Chunk.tsv.op("@@")(tsquery))
        .order_by(func.ts_rank(Chunk.tsv, tsquery).desc(), Chunk.id.asc())
        .limit(_CANDIDATE_POOL)
    )
    return list((await session.execute(statement)).scalars())


async def _article_chunk_ids(session: AsyncSession, article: str, *, limit: int) -> list[int]:
    """Ids of every chunk of one article, apartado order first."""
    statement = (
        select(Chunk.id)
        .where(Chunk.articulo == article)
        .order_by(Chunk.apartado.asc().nulls_first(), Chunk.id.asc())
        .limit(limit)
    )
    return list((await session.execute(statement)).scalars())


async def _fetch_chunks(session: AsyncSession, ids: Sequence[int]) -> dict[int, Chunk]:
    if not ids:
        return {}
    rows = (await session.execute(select(Chunk).where(Chunk.id.in_(ids)))).scalars().all()
    return {row.id: row for row in rows}


def _without_duplicates(ids: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for chunk_id in ids:
        if chunk_id not in seen:
            seen.add(chunk_id)
            ordered.append(chunk_id)
    return ordered


def _branches_for(
    chunk_id: int,
    direct_set: set[int],
    vector_ids: Sequence[int],
    lexical_ids: Sequence[int],
) -> tuple[str, ...]:
    branches: set[str] = set()
    if chunk_id in direct_set:
        branches.add(BRANCH_DIRECT)
    if chunk_id in lexical_ids:
        branches.add(BRANCH_LEXICAL)
    if chunk_id in vector_ids:
        branches.add(BRANCH_VECTOR)
    return tuple(sorted(branches))
