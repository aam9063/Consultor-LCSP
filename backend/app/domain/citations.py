"""Pure citation rules for cited answers (CL-05, S3/S12, AC-06).

The answer text must cite the retrieved context with `[art. X]` or
`[art. X.Y]` after every claim. This module parses those citations
(tolerating whitespace, case and several citations in one bracket),
splits the answer into claims (sentences) and validates each citation
against the index of retrieved chunks: the article must exist among them
and, when the citation names an apartado, that apartado must exist for
that article. A claim is supported when at least one of its citations is
valid; a claim without any citation is therefore unsupported too.

Domain code: no SQLAlchemy, no AI SDK, no FastAPI (AGENTS.md section 8).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = [
    "Citation",
    "CitationReport",
    "Claim",
    "build_chunk_index",
    "parse_citations",
    "split_claims",
    "validate_answer",
]


@dataclass(frozen=True, slots=True)
class Citation:
    """One `[art. X]` or `[art. X.Y]` citation extracted from the answer."""

    articulo: str
    apartado: str | None

    def label(self) -> str:
        """The citation in its canonical bracketed form, e.g. `[art. 107.2]`."""
        if self.apartado is None:
            return f"[art. {self.articulo}]"
        return f"[art. {self.articulo}.{self.apartado}]"


@dataclass(frozen=True, slots=True)
class Claim:
    """One sentence of the answer with its citations and backing verdict."""

    text: str
    citations: tuple[Citation, ...]
    supported: bool


@dataclass(frozen=True, slots=True)
class CitationReport:
    """Outcome of validating one answer's citations against the retrieved chunks."""

    valid: tuple[Citation, ...]
    invalid: tuple[Citation, ...]
    claims: tuple[Claim, ...]

    @property
    def unsupported_claims(self) -> tuple[Claim, ...]:
        return tuple(claim for claim in self.claims if not claim.supported)


# Citation bracket groups and, inside each one, the `art` tokens. The dot
# is optional ("[art 107]" is tolerated too); surrounding whitespace and
# case do not matter. Numbers are 1-3 digits, like the parser's articles.
_CITATION_GROUP_RE = re.compile(r"\[([^\]]*)\]")
_CITATION_RE = re.compile(r"(?iu)\bart\.?\s*(\d{1,3})(?:\.(\d{1,3}))?")
_CLAIM_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _normalize_number(value: str) -> str:
    """Canonical numeric identity: "007" and "7" are the same apartado."""
    return str(int(value)) if value.isdigit() else value


def parse_citations(text: str) -> tuple[Citation, ...]:
    """Extract every citation from the bracket groups of `text`, in order.

    Several `[art. X]` tokens may share one bracket; repeated citations
    are deduplicated while keeping first-seen order.
    """
    citations: list[Citation] = []
    seen: set[Citation] = set()
    for group in _CITATION_GROUP_RE.finditer(text):
        for match in _CITATION_RE.finditer(group.group(1)):
            apartado = match.group(2)
            citation = Citation(
                articulo=_normalize_number(match.group(1)),
                apartado=_normalize_number(apartado) if apartado is not None else None,
            )
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)
    return tuple(citations)


def split_claims(text: str) -> tuple[str, ...]:
    """Split the answer into claims (sentences), one stripped claim per part.

    Citation brackets are protected with placeholders first, so the dot of
    `art.` never becomes a sentence boundary; boundaries are `.`, `!`, `?`
    followed by whitespace, and newlines.
    """
    placeholders: dict[str, str] = {}

    def _protect(match: re.Match[str]) -> str:
        key = f"\x00{len(placeholders)}\x00"
        placeholders[key] = match.group(0)
        return key

    protected = _CITATION_GROUP_RE.sub(_protect, text)
    claims: list[str] = []
    for part in _CLAIM_SPLIT_RE.split(protected):
        claim = part.strip()
        if not claim:
            continue
        for key, value in placeholders.items():
            claim = claim.replace(key, value)
        claims.append(claim)
    return tuple(claims)


def build_chunk_index(
    chunks: Iterable[tuple[str, str | None]],
) -> dict[str, set[str | None]]:
    """Group `(articulo, apartado)` pairs into the index citations validate against."""
    index: dict[str, set[str | None]] = {}
    for articulo, apartado in chunks:
        index.setdefault(articulo, set()).add(apartado)
    return index


def _citation_backed(citation: Citation, index: Mapping[str, set[str | None]]) -> bool:
    apartados = index.get(citation.articulo)
    if apartados is None:
        return False
    if citation.apartado is None:
        return True
    return any(
        apartado is not None and _normalize_number(apartado) == citation.apartado
        for apartado in apartados
    )


def validate_answer(text: str, index: Mapping[str, set[str | None]]) -> CitationReport:
    """Validate every citation of `text` against the retrieved-chunk index."""
    citations = parse_citations(text)
    valid = tuple(citation for citation in citations if _citation_backed(citation, index))
    invalid = tuple(citation for citation in citations if not _citation_backed(citation, index))
    claims = tuple(
        Claim(
            text=claim_text,
            citations=claim_citations,
            supported=any(_citation_backed(citation, index) for citation in claim_citations),
        )
        for claim_text, claim_citations in (
            (claim, parse_citations(claim)) for claim in split_claims(text)
        )
    )
    return CitationReport(valid=valid, invalid=invalid, claims=claims)
