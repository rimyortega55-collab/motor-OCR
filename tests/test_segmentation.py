"""Capa 2: segmentación nativo-digital y su llegada al Markdown exportado.

Las pruebas corren contra `pruebas/pdfs_de_prueba/c1.pdf`, un libro de texto
real: los defectos que se comprueban acá (párrafos partidos cada dos renglones,
guiones de corte, folios corrientes mezclados con el texto) sólo aparecen con
una maquetación de verdad y no se reproducen con un PDF sintético.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from motor_ocr.modelos import Documento, Origen, TipoBloque
from motor_ocr.layout import construir_vocabulario, resolver_orden_lectura
from motor_ocr.layout.nativo_digital import segmentar_nativo_digital
from motor_ocr.layout.taxonomia import clasificar_bloque
from motor_ocr_render import BloqueRenderizable, DocumentoRenderizable
from motor_ocr_render.markdown import renderizar as renderizar_markdown

PDF = Path(__file__).resolve().parents[1] / "pruebas" / "pdfs_de_prueba" / "c1.pdf"

pytestmark = pytest.mark.skipif(not PDF.is_file(), reason=f"falta el PDF de prueba {PDF}")


@pytest.fixture(scope="module")
def vocabulario() -> set[str]:
    return construir_vocabulario(str(PDF))


@pytest.fixture(scope="module")
def documento() -> Documento:
    return Documento(
        titulo="c1.pdf",
        origen=Origen.NATIVO_DIGITAL,
        idioma_original="en",
        total_paginas=21,
        version_pipeline="0.1.0",
    )


def _pagina(documento: Documento, vocabulario: set[str], numero: int):
    return resolver_orden_lectura(
        segmentar_nativo_digital(documento, str(PDF), numero, vocabulario)
    )


def _textos(bloques) -> list[str]:
    return [b.contenido.texto_plano or "" for b in bloques]


def test_un_parrafo_no_se_parte_por_renglon(documento, vocabulario):
    """El párrafo entero en un bloque, no en trozos de dos renglones.

    Es el defecto que hacía ilegible la exportación: el umbral vertical se
    medía contra la primera línea del bloque y con interlineado de 12 pt
    cortaba cada párrafo en pedazos.
    """
    textos = _textos(_pagina(documento, vocabulario, 6))

    parrafo = next(t for t in textos if t.startswith("The ﬁrst chapter is a warm-up"))
    assert parrafo.endswith("‘‘Solutions to Exercises’’.")


def test_la_cursiva_intercalada_no_corta_la_frase(documento, vocabulario):
    """Un cambio de fuente en medio de una frase no abre un bloque nuevo.

    Agrupar por nombre de fuente partía la frase en tres y el orden de lectura
    los barajaba, así que el título en cursiva salía antes que su propia frase.
    """
    textos = _textos(_pagina(documento, vocabulario, 5))

    assert any(
        t.startswith("This book has evolved from a course in Mathematical Writing offered")
        for t in textos
    )


@pytest.mark.parametrize(
    "esperado, no_esperado",
    [
        ("teaching resources", "resour- ces"),  # corte tipográfico: el guion se va
        ("This material underpins", "mate-rial"),
        ("who commented on", "com-mented"),
        ("offered to second-year", "second- year"),  # guion del autor: se queda
    ],
)
def test_guiones_de_corte(documento, vocabulario, esperado, no_esperado):
    completo = " ".join(
        _textos(_pagina(documento, vocabulario, 5))
        + _textos(_pagina(documento, vocabulario, 6))
    )

    assert esperado in completo
    assert no_esperado not in completo


def test_el_folio_corriente_se_marca_como_ruido(documento, vocabulario):
    """"viii Preface" en el margen superior no es contenido del documento."""
    bloques = _pagina(documento, vocabulario, 6)

    folio = next(b for b in bloques if "Preface" in (b.contenido.texto_plano or ""))
    assert folio.tipo == TipoBloque.RUIDO


def test_los_titulos_numerados_son_encabezados(documento, vocabulario):
    bloques = _pagina(documento, vocabulario, 14)
    por_texto = {b.contenido.texto_plano: b.tipo for b in bloques}

    assert por_texto["Chapter 1"] == TipoBloque.ENCABEZADO
    assert por_texto["Some Writing Tips"] == TipoBloque.ENCABEZADO
    assert por_texto["1.1 Grammar"] == TipoBloque.ENCABEZADO


def test_las_entradas_de_indice_son_items_con_elipsis(documento, vocabulario):
    bloques = _pagina(documento, vocabulario, 8)
    entradas = [b for b in bloques if b.tipo == TipoBloque.LISTA]

    assert len(entradas) > 10
    assert any(b.contenido.texto_plano == "1.2 Numbers and Symbols … 3" for b in entradas)
    # Los puntos guía crudos no llegan a la salida.
    assert not any(". . ." in (b.contenido.texto_plano or "") for b in bloques)


def test_cada_item_de_una_lista_es_su_propio_bloque(documento, vocabulario):
    """Con sangría francesa la viñeta sobresale y el ítem se lee entero."""
    textos = _textos(_pagina(documento, vocabulario, 15))

    item = next(t for t in textos if t.startswith("• Write in complete sentences"))
    assert item.endswith("in the middle of a paragraph.")
    assert any(t.startswith("• Make sure that the nouns match") for t in textos)


def test_la_prosa_con_palabras_clave_no_es_codigo():
    """" for " o " if " dentro de una frase no convierten el párrafo en código."""
    prosa = (
        "It brings about the discipline needed to use symbols effectively, and is "
        "invaluable for learning how to communicate to an audience of non-experts. "
        "Consider the following question:"
    )

    assert clasificar_bloque(prosa, False) == TipoBloque.PARRAFO
    assert clasificar_bloque("for i in range(10):", False) == TipoBloque.CODIGO


def test_markdown_omite_ruido_y_agrupa_los_items():
    def bloque(orden, tipo, texto):
        return BloqueRenderizable(
            pagina=0, orden_lectura=orden, tipo=tipo, texto=texto
        )

    bloques = [
        bloque(0, "ruido", "viii Preface"),
        bloque(1, "encabezado", "1.1 Grammar"),
        bloque(2, "lista", "1.1 Grammar … 1"),
        bloque(3, "lista", "• Style"),
        bloque(4, "parrafo", "Texto corrido."),
    ]

    md = renderizar_markdown(DocumentoRenderizable(titulo="c1.pdf"), bloques)

    assert md.startswith("# c1\n")  # sin la extensión del archivo subido
    assert "viii Preface" not in md
    assert "### 1.1 Grammar" in md  # el nivel sale de la numeración de sección
    # Los dos ítems van pegados: una línea en blanco los volvería una lista
    # suelta, con un párrafo por ítem.
    assert "- 1.1 Grammar … 1\n- Style\n" in md
