"""Retrieval API endpoints (CL-04, BRIEF section 9): retrieval only, no LLM generation.

`GET /buscar?q=...` is the debug view of the hybrid ranking with scores;
`GET /articulos/{numero}` returns the full text of every chunk of an
article, or a 404 with a typed error body when the article does not exist.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import LLMDep
from app.config import get_settings
from app.db.models import Chunk
from app.db.session import get_session
from app.services.retrieval import RetrievedChunk, hybrid_search

router = APIRouter(tags=["retrieval"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ChunkBody(BaseModel):
    id: int
    articulo: str
    apartado: str | None
    titulo: str
    url: str
    texto: str


class ScoredChunkBody(ChunkBody):
    score: float
    branches: list[str]


class SearchResponse(BaseModel):
    query: str
    best_score: float | None
    results: list[ScoredChunkBody]


class ArticleResponse(BaseModel):
    articulo: str
    chunks: list[ChunkBody]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def _scored_body(chunk: RetrievedChunk) -> ScoredChunkBody:
    return ScoredChunkBody(
        id=chunk.id,
        articulo=chunk.articulo,
        apartado=chunk.apartado,
        titulo=chunk.titulo,
        url=chunk.url,
        texto=chunk.texto,
        score=chunk.score,
        branches=list(chunk.branches),
    )


@router.get("/buscar", response_model=SearchResponse)
async def buscar(q: str, session: SessionDep, llm: LLMDep) -> SearchResponse:
    """Debug view: the hybrid ranking with scores, without any generation."""
    result = await hybrid_search(session, llm, q, top_k=get_settings().retrieval_top_k)
    return SearchResponse(
        query=result.query,
        best_score=result.best_score,
        results=[_scored_body(chunk) for chunk in result.chunks],
    )


@router.get(
    "/articulos/{numero}",
    response_model=ArticleResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_articulo(numero: str, session: SessionDep) -> JSONResponse:
    """Full text of every chunk of one article; 404 with a typed body if absent."""
    rows = (
        (
            await session.execute(
                select(Chunk)
                .where(Chunk.articulo == numero)
                .order_by(Chunk.apartado.asc().nulls_first(), Chunk.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        body = ErrorResponse(
            error=ErrorBody(
                code="article_not_found",
                message=f"Article {numero!r} does not exist in the ingested LCSP.",
            )
        )
        return JSONResponse(status_code=404, content=body.model_dump())
    article = ArticleResponse(
        articulo=numero,
        chunks=[
            ChunkBody(
                id=row.id,
                articulo=row.articulo,
                apartado=row.apartado,
                titulo=row.titulo,
                url=row.url,
                texto=row.texto,
            )
            for row in rows
        ],
    )
    return JSONResponse(content=article.model_dump())
