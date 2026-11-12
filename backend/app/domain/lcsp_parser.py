"""Pure-domain parser for the BOE consolidated LCSP XML (CL-02, S1/S8).

Turns the BOE consolidated XML (`<response><data><texto><bloque>...`) into
retrieval chunks: one chunk per article, splitting by `apartado` when an
article is estimated to exceed ~1.500 tokens and never splitting an
`apartado` across chunks. Disposiciones adicionales, transitorias,
derogatorias and finales are parsed with their own identity.

This module is domain code: it must not import FastAPI, SQLAlchemy or the
AI SDK (AGENTS.md section 8). Parsing uses only the standard library.
"""

import re
from dataclasses import dataclass
from xml.etree.ElementTree import Element, fromstring

__all__ = ["LcspChunk", "parse_lcsp"]

# ~1.500 tokens, estimated at ~4 characters per token (Spanish prose).
MAX_CHUNK_TOKENS = 1500
_TOKEN_CHARS = 4

# Article heading, e.g. "Artículo 107".
_ARTICLE_RE = re.compile(r"^Artículo\s+(.+)$")
# Numbered apartado starting a paragraph, e.g. "1. Los licitadores...".
_APARTADO_RE = re.compile(r"^(\d+)\.\s+")
# Kinds of disposición, in BOE XML word order.
_DISPOSICION_PREFIX = {"adicional": "DA", "transitoria": "DT", "derogatoria": "DD", "final": "DF"}
# Encabezado kinds by hierarchy level; a deeper heading resets lower ones.
_ENCABEZADO_LEVELS = {
    "LIBRO": 0,
    "ANEXO": 0,
    "TÍTULO": 1,
    "CAPÍTULO": 2,
    "Sección": 3,
    "Subsección": 4,
}
# Footnote paragraphs are BOE publication notes, not law text.
_NOTA_PIE = "nota_pie"
# A "version" element carries the consolidated version date.
_BOE_URL_TEMPLATE = "https://www.boe.es/buscar/act.php?id={boe_id}#{anchor}"


@dataclass(frozen=True, slots=True)
class LcspChunk:
    """One retrieval chunk with the metadata required by spec S1."""

    boe_id: str
    articulo: str
    apartado: str | None
    titulo: str
    ruta: tuple[str, ...]
    texto: str
    url: str
    fecha_version: str


def estimate_tokens(text: str) -> int:
    """Estimate the token count of `text` (~4 characters per token)."""
    return max(1, -(-len(text) // _TOKEN_CHARS))


def _decode(data: bytes) -> str:
    """Decode the BOE XML bytes explicitly instead of trusting the declaration.

    The current consolidated export is valid UTF-8 (verified byte-level), but
    the BOE has shipped mislabelled exports before, so a Latin-1 fallback keeps
    an unexpected export parseable instead of failing on a codec mismatch. The
    XML declaration is stripped so `fromstring` accepts the decoded string
    without re-applying the declared codec.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 never fails
        raise ValueError("Cannot decode the LCSP XML data")
    if text.startswith("<?xml"):
        end = text.index("?>") + 2
        text = text[end:]
    return text


def _paragraph_text(element: Element) -> str:
    raw = "".join(element.itertext())
    return " ".join(raw.replace("\xa0", " ").split())


def _version_elements(block: Element) -> list[Element]:
    return [child for child in block if child.tag == "version"]


def _normalise_date(raw: str | None) -> str:
    if not raw or len(raw) != 8 or not raw.isdigit():
        return raw or ""
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _articulo_identifier(title_attr: str, counters: dict[str, int]) -> str:
    article = _ARTICLE_RE.match(title_attr)
    if article:
        return article.group(1).strip()
    disposition = re.match(r"^Disposición\s+(\w+)", title_attr)
    if disposition:
        kind = disposition.group(1)
        prefix = _DISPOSICION_PREFIX.get(kind, "DX")
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]}"
    return title_attr.strip()


def _group_apartados(
    version: Element,
) -> tuple[str | None, list[tuple[str | None, list[str]]]]:
    """Return `(heading, groups)` where each group is `(apartado, paragraphs)`.

    The first group (if any) holds paragraphs that precede the first
    numbered apartado; it keeps `apartado=None`.
    """
    heading: str | None = None
    groups: list[tuple[str | None, list[str]]] = []
    current: str | None = None
    for paragraph in version:
        if paragraph.tag != "p":
            continue
        css_class = paragraph.get("class", "")
        if css_class.startswith(_NOTA_PIE):
            continue
        text = _paragraph_text(paragraph)
        if not text:
            continue
        if css_class == "articulo" and heading is None:
            heading = text
            continue
        apartado = _APARTADO_RE.match(text) if css_class in ("parrafo", "sangrado") else None
        if apartado:
            current = apartado.group(1)
            groups.append((current, [text]))
        elif groups:
            groups[-1][1].append(text)
        else:
            groups.append((None, [text]))
    return heading, groups


def _build_chunks(
    version: Element,
    *,
    boe_id: str,
    anchor: str | None,
    articulo: str,
    ruta: tuple[str, ...],
) -> list[LcspChunk]:
    heading, groups = _group_apartados(version)
    if not groups:
        return []
    title = heading or articulo
    if anchor and anchor != "no":
        url = _BOE_URL_TEMPLATE.format(boe_id=boe_id, anchor=anchor)
    else:
        url = f"https://www.boe.es/buscar/act.php?id={boe_id}"
    fecha_version = _normalise_date(version.get("fecha_vigencia"))

    full_text = "\n".join(line for _, lines in groups for line in lines)
    has_apartados = any(apartado is not None for apartado, _ in groups)
    if estimate_tokens(full_text) <= MAX_CHUNK_TOKENS or not has_apartados:
        # Whole article stays a single chunk, even if oversized without
        # apartados: the rule only allows splitting by apartado.
        return [
            LcspChunk(
                boe_id=boe_id,
                articulo=articulo,
                apartado=None,
                titulo=title,
                ruta=ruta,
                texto=_compose(title, [line for _, lines in groups for line in lines]),
                url=url,
                fecha_version=fecha_version,
            )
        ]

    chunks: list[LcspChunk] = []
    # Any leading text before the first apartado is kept with the first
    # apartado's chunk so it is never lost.
    pending_leading: list[str] = []
    for apartado, lines in groups:
        if apartado is None:
            pending_leading = lines
            continue
        body = [*pending_leading, *lines]
        pending_leading = []
        chunks.append(
            LcspChunk(
                boe_id=boe_id,
                articulo=articulo,
                apartado=apartado,
                titulo=title,
                ruta=ruta,
                texto=_compose(title, body),
                url=url,
                fecha_version=fecha_version,
            )
        )
    if pending_leading:
        chunks.append(
            LcspChunk(
                boe_id=boe_id,
                articulo=articulo,
                apartado=None,
                titulo=title,
                ruta=ruta,
                texto=_compose(title, pending_leading),
                url=url,
                fecha_version=fecha_version,
            )
        )
    return chunks


def _compose(title: str, lines: list[str]) -> str:
    return "\n".join([title, *lines])


def parse_lcsp(data: bytes) -> list[LcspChunk]:
    """Parse the BOE consolidated XML bytes into retrieval chunks."""
    root = fromstring(_decode(data))
    texto = root.find(".//texto")
    if texto is None:
        raise ValueError("LCSP XML has no <texto> element")
    ruta: list[str] = []
    counters: dict[str, int] = {}
    chunks: list[LcspChunk] = []
    for block in texto.iter("bloque"):
        block_type = block.get("tipo", "")
        title_attr = block.get("titulo", "")
        if block_type == "encabezado":
            first_word = title_attr.split(" ", 1)[0] if title_attr else ""
            level = _ENCABEZADO_LEVELS.get(first_word)
            if level is not None:
                del ruta[level:]
                ruta.append(title_attr)
            continue
        if block_type != "precepto":
            continue
        versions = _version_elements(block)
        if not versions:
            continue
        version = versions[0]
        boe_id = version.get("id_norma", "")
        chunks.extend(
            _build_chunks(
                version,
                boe_id=boe_id,
                anchor=block.get("id"),
                articulo=_articulo_identifier(title_attr, counters),
                ruta=tuple(ruta),
            )
        )
    return chunks
