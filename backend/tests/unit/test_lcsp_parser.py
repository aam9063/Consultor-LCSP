"""Unit tests for the LCSP domain parser (CL-02, specs S1 and S8 / AC-02).

Every fixture below is a small checked-in XML snippet that mirrors the real
BOE consolidated XML structure (`data/lcsp/lcsp-consolidada.xml`), so these
tests run on a clean clone and in CI without the real file.
"""

from typing import Final

from app.domain.lcsp_parser import parse_lcsp

BOE_ID: Final = "BOE-A-2017-12902"


def _bloque_precepto(bloque_id: str, titulo: str, body: str) -> str:
    return (
        f'<bloque id="{bloque_id}" tipo="precepto" titulo="{titulo}">'
        f'<version id_norma="{BOE_ID}" fecha_publicacion="20171109"'
        f' fecha_vigencia="20180309">{body}</version></bloque>'
    )


def _bloque_encabezado(bloque_id: str, titulo: str) -> str:
    return (
        f'<bloque id="{bloque_id}" tipo="encabezado" titulo="{titulo}">'
        f'<version id_norma="{BOE_ID}" fecha_publicacion="20171109"'
        f' fecha_vigencia="20180309">'
        f'<p class="seccion">{titulo}</p></version></bloque>'
    )


def _xml(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<response><status><code>200</code></status>"
        f"<data><texto>{body}</texto></data></response>"
    ).encode()


def _long_text(prefix: str, chars: int) -> str:
    """Long apartado body: > 1.500 estimated tokens once the heading joins it."""
    return f"{prefix} " + ("palabras de relleno " * (chars // 21))


# --- AC-02 / S8: 3 articles, one of them with apartados ---------------------


def test_parses_number_title_apartado_and_path() -> None:
    body = "".join(
        [
            _bloque_encabezado("tp", "TÍTULO PRELIMINAR"),
            _bloque_encabezado("ci", "CAPÍTULO I"),
            _bloque_encabezado("s1", "Sección 1"),
            _bloque_precepto(
                "a1",
                "Artículo 1",
                '<p class="articulo">Artículo 1. Objeto de la Ley.</p>'
                '<p class="parrafo">1. Esta Ley regula la contratación pública.</p>'
                '<p class="parrafo">2. También el examen de sus cláusulas.</p>',
            ),
            _bloque_precepto(
                "a2",
                "Artículo 2",
                '<p class="articulo">Artículo 2. Artículo con apartados.</p>'
                f'<p class="parrafo">1. {_long_text("Apartado primero", 3300)}</p>'
                f'<p class="parrafo">2. {_long_text("Apartado segundo", 3300)}</p>',
            ),
            _bloque_precepto(
                "a3",
                "Artículo 3",
                '<p class="articulo">Artículo 3. Artículo corto.</p>'
                '<p class="parrafo">Este artículo no tiene apartados numerados.</p>',
            ),
        ]
    )

    chunks = parse_lcsp(_xml(body))

    assert {(chunk.articulo, chunk.apartado) for chunk in chunks} == {
        ("1", None),
        ("2", "1"),
        ("2", "2"),
        ("3", None),
    }
    art1 = next(c for c in chunks if c.articulo == "1")
    assert art1.titulo == "Artículo 1. Objeto de la Ley."
    art2_first = next(c for c in chunks if c.articulo == "2" and c.apartado == "1")
    assert art2_first.ruta == ("TÍTULO PRELIMINAR", "CAPÍTULO I", "Sección 1")
    assert art2_first.titulo == "Artículo 2. Artículo con apartados."
    art2_second = next(c for c in chunks if c.articulo == "2" and c.apartado == "2")
    assert art2_second.texto.startswith("Artículo 2. Artículo con apartados.")
    assert "Apartado segundo" in art2_second.texto


def test_article_under_the_limit_stays_one_chunk() -> None:
    body = _bloque_precepto(
        "a3",
        "Artículo 3",
        '<p class="articulo">Artículo 3. Artículo corto.</p>'
        '<p class="parrafo">1. Un único apartado con poco texto.</p>',
    )

    chunks = parse_lcsp(_xml(body))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.articulo == "3"
    assert chunk.apartado is None
    assert "Artículo 3. Artículo corto." in chunk.texto
    assert "Un único apartado con poco texto." in chunk.texto


# --- S1: metadata per chunk (URL with anchor, consolidated version date) ----


def test_chunk_metadata_url_and_version_date() -> None:
    body = _bloque_precepto(
        "a107",
        "Artículo 107",
        '<p class="articulo">Artículo 107. Exigencia de la garantía definitiva.</p>'
        '<p class="parrafo">1. Los licitadores deberán constituir una garantía.</p>',
    )

    chunks = parse_lcsp(_xml(body))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.url == (f"https://www.boe.es/buscar/act.php?id={BOE_ID}#a107")
    assert chunk.fecha_version == "2018-03-09"


def test_chunk_metadata_is_decoded_correctly() -> None:
    body = _bloque_precepto(
        "a1",
        "Artículo 1",
        '<p class="articulo">Artículo 1. Objeto de la Ley.</p>'
        '<p class="parrafo">Aprobación de pliegos y adjudicación.</p>',
    )

    chunks = parse_lcsp(_xml(body))

    assert chunks[0].titulo == "Artículo 1. Objeto de la Ley."
    assert "adjudicación" in chunks[0].texto


# --- S1: articles over ~1.500 tokens split by apartado, never splitting one -


def test_long_article_splits_by_apartado_without_splitting_one() -> None:
    body = _bloque_precepto(
        "a9",
        "Artículo 9",
        '<p class="articulo">Artículo 9. Artículo largo con tres apartados.</p>'
        f'<p class="parrafo">1. {_long_text("MARCADOR_UNO", 3400)}</p>'
        f'<p class="parrafo">b) {_long_text("Continuación del apartado uno", 3400)}</p>'
        f'<p class="parrafo">2. {_long_text("MARCADOR_DOS", 3400)}</p>'
        f'<p class="parrafo">3. {_long_text("MARCADOR_TRES", 3400)}</p>',
    )

    chunks = parse_lcsp(_xml(body))

    assert {(chunk.articulo, chunk.apartado) for chunk in chunks} == {
        ("9", "1"),
        ("9", "2"),
        ("9", "3"),
    }
    first = next(c for c in chunks if c.apartado == "1")
    second = next(c for c in chunks if c.apartado == "2")
    third = next(c for c in chunks if c.apartado == "3")
    # The letra b) continuation stays inside apartado 1's chunk.
    assert "MARCADOR_UNO" in first.texto
    assert "Continuación del apartado uno" in first.texto
    assert "MARCADOR_DOS" in second.texto
    assert "MARCADOR_TRES" in third.texto
    # No apartado leaks into another chunk.
    for chunk in chunks:
        if chunk.apartado != "1":
            assert "MARCADOR_UNO" not in chunk.texto
        if chunk.apartado != "2":
            assert "MARCADOR_DOS" not in chunk.texto
        if chunk.apartado != "3":
            assert "MARCADOR_TRES" not in chunk.texto


# --- S1: disposiciones are parsed with their own identity -------------------


def test_disposicion_adicional_is_parsed_with_its_own_identity() -> None:
    body = "".join(
        [
            _bloque_precepto(
                "a5",
                "Artículo 5",
                '<p class="articulo">Artículo 5. Medios de prueba.</p>'
                '<p class="parrafo">La prueba se practicarán conforme a lo dispuesto.</p>',
            ),
            _bloque_precepto(
                "da",
                "Disposición adicional primera",
                '<p class="articulo">Disposición adicional primera. '
                "Contratación en el extranjero.</p>"
                '<p class="parrafo">1. Los contratos que se formalicen en el '
                "extranjero se regirán por las siguientes normas.</p>",
            ),
        ]
    )

    chunks = parse_lcsp(_xml(body))

    assert {(chunk.articulo, chunk.apartado) for chunk in chunks} == {
        ("5", None),
        ("DA1", None),
    }
    disposicion = next(c for c in chunks if c.articulo == "DA1")
    assert disposicion.titulo == ("Disposición adicional primera. Contratación en el extranjero.")
    assert "Contratación en el extranjero" in disposicion.texto
    assert "Artículo 5" not in disposicion.texto
