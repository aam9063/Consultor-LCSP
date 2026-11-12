"""Pure ranking helpers for hybrid retrieval (CL-04, S2/S11).

Reciprocal Rank Fusion, deterministic score ordering, and the Spanish
article-number extraction that powers the direct retrieval path (AC-04).
Domain code: no SQLAlchemy, no AI SDK, no FastAPI (AGENTS.md section 8).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "RankedItem",
    "extract_article_number",
    "ranked_indices",
    "reciprocal_rank_fusion",
]

# Standard RRF damping constant.
_DEFAULT_RRF_K = 60

# Article mentions in a Spanish question: "artículo 107", "art. 107",
# "Artículo 107.2", "articulos 5"... The optional dot covers the abbreviated
# form; the trailing lookahead keeps an article number from matching inside
# an unrelated longer figure ("artículo 1072" must not yield "107").
_ARTICLE_RE = re.compile(r"(?iu)\bart(?:[íi]culo?s?)?\.?\s+(\d{1,3})(?!\d)")


@dataclass(frozen=True, slots=True)
class RankedItem:
    """One fused id with its Reciprocal Rank Fusion score."""

    id: str
    score: float


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = _DEFAULT_RRF_K
) -> list[RankedItem]:
    """Fuse any number of ranked id lists into one ordered list with scores.

    Each id scores the sum of `1 / (k + rank)` over every ranking it appears
    in (1-based ranks). The merged list is ordered by score descending; equal
    scores break by the earliest position at which the id appears in any
    ranking, scanning the rankings in the given order — never by dict
    iteration order, so the fusion is stable and deterministic.
    """
    scores: dict[str, float] = {}
    first_position: dict[str, int] = {}
    position = 0
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            if item_id not in first_position:
                first_position[item_id] = position
            position += 1
    fused_ids = sorted(scores, key=lambda item_id: (-scores[item_id], first_position[item_id]))
    return [RankedItem(id=item_id, score=scores[item_id]) for item_id in fused_ids]


def ranked_indices(scores: Sequence[float]) -> list[int]:
    """Order candidate positions by score descending, ties by input position.

    Callers must pass candidates in their fused-rank order so score ties
    resolve along that order, never along dict iteration order.
    """
    return sorted(range(len(scores)), key=lambda position: (-scores[position], position))


def extract_article_number(question: str) -> str | None:
    """Return the article identity ("107") named by a Spanish question, or None.

    Recognises "¿Qué dice el artículo 107?", "art. 107", "artículo 107.2"
    (only the article part is returned) and case/variant forms. Article
    numbers start at 1, and figures embedded in unrelated numbers
    ("artículo 1072", "expediente 1072") never match.
    """
    match = _ARTICLE_RE.search(question)
    if match is None:
        return None
    number = int(match.group(1))
    if number < 1:
        return None
    return match.group(1)
