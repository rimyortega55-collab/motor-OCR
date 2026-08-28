"""Capa 2: en qué orden se lee la página.

El orden de lectura es geometría pura, y por eso se prueba con documentos
generados y no con el corpus real: la respuesta correcta se puede escribir de
antemano, cosa que con un libro escaneado sólo se puede hacer a ojo.

Es un fallo caro cuando sale mal, y silencioso. Un documento a dos columnas
leído renglón por renglón cruzando la página produce texto gramaticalmente
plausible y completamente desordenado; nada aguas abajo lo detecta, y el
export sale con el contenido intercalado sin una sola advertencia.

Hay dos direcciones de error y las dos importan, por eso hay pruebas de las
dos: no detectar las columnas cuando las hay, y -el defecto que la
implementación anterior tenía- creer que hay columnas en una página de una
sola, que reordena por grupos texto que ya estaba bien.
"""

from __future__ import annotations

import re
import uuid

import pymupdf
import pytest

from motor_ocr.layout.orden_lectura import resolver_orden_lectura
from motor_ocr.modelos import Bloque, OrigenContenido, TipoBloque
from motor_ocr.modelos.block import Contenido, Layout, Provenance

from tests.fixtures import sinteticos


_DOCUMENTO_ID = uuid.uuid4()


def _bloque(texto: str, bbox: tuple[float, float, float, float]) -> Bloque:
    return Bloque(
        documento_id=_DOCUMENTO_ID,
        pagina=0,
        tipo=TipoBloque.PARRAFO,
        layout=Layout(bbox=bbox, orden_lectura=0, confianza_layout=0.9),
        origen_contenido=OrigenContenido.TEXTO_NATIVO,
        contenido=Contenido(texto_plano=texto),
        provenance=Provenance(creado_por_capa="prueba"),
    )


def _textos_en_orden(bloques: list[Bloque]) -> list[str]:
    ordenados = sorted(bloques, key=lambda b: b.layout.orden_lectura)
    return [b.contenido.texto_plano for b in ordenados]


# ============================================================================
# DOS COLUMNAS
# ============================================================================

def test_lee_la_columna_izquierda_entera_antes_que_la_derecha():
    """Cuatro bloques en dos columnas: 1, 2 a la izquierda; 3, 4 a la derecha.

    Si el orden sale 1, 3, 2, 4 el motor está leyendo por renglones a través de
    la calle, que es exactamente el fallo que esta capa existe para evitar.
    """
    bloques = [
        _bloque("1", (0.08, 0.10, 0.45, 0.30)),
        _bloque("3", (0.55, 0.10, 0.92, 0.30)),
        _bloque("2", (0.08, 0.35, 0.45, 0.55)),
        _bloque("4", (0.55, 0.35, 0.92, 0.55)),
    ]
    resultado = resolver_orden_lectura(bloques)

    assert _textos_en_orden(resultado) == ["1", "2", "3", "4"]


def test_una_pagina_de_una_columna_no_se_reordena_por_grupos():
    """El falso positivo: sangrías y títulos no son una segunda columna.

    La detección anterior comparaba huecos entre bordes izquierdos, y con
    varios bloques por página eso se cumple casi siempre. Activaba el modo
    multi-columna en documentos de una sola y dejaba el texto ilegible. Acá los
    bloques tienen sangrías distintas y aun así deben leerse de arriba abajo.
    """
    bloques = [
        _bloque("1", (0.10, 0.10, 0.90, 0.20)),
        _bloque("2", (0.15, 0.25, 0.90, 0.35)),  # sangria
        _bloque("3", (0.35, 0.40, 0.65, 0.50)),  # titulo centrado
        _bloque("4", (0.10, 0.55, 0.90, 0.65)),
    ]
    resultado = resolver_orden_lectura(bloques)

    assert _textos_en_orden(resultado) == ["1", "2", "3", "4"]


def test_un_bloque_ancho_que_cruza_la_calle_impide_la_deteccion():
    """Un título a todo el ancho tapa la calle: sin calle, no hay dos columnas."""
    bloques = [
        _bloque("titulo", (0.08, 0.05, 0.92, 0.09)),
        _bloque("1", (0.08, 0.10, 0.45, 0.30)),
        _bloque("2", (0.55, 0.10, 0.92, 0.30)),
        _bloque("3", (0.08, 0.35, 0.45, 0.55)),
    ]
    resultado = resolver_orden_lectura(bloques)

    assert _textos_en_orden(resultado)[0] == "titulo"


# ============================================================================
# CASOS DE BORDE
# ============================================================================

def test_una_pagina_sin_bloques_no_revienta():
    assert resolver_orden_lectura([]) == []


def test_pocos_bloques_no_activan_el_modo_multicolumna():
    """Con menos de cuatro bloques no hay evidencia suficiente de una calle."""
    bloques = [
        _bloque("1", (0.08, 0.10, 0.45, 0.30)),
        _bloque("2", (0.55, 0.10, 0.92, 0.30)),
    ]
    resultado = resolver_orden_lectura(bloques)

    assert len(resultado) == 2
    assert sorted(b.layout.orden_lectura for b in resultado) == [0, 1]


# ============================================================================
# SOBRE EL PDF GENERADO A DOS COLUMNAS
# ============================================================================

def test_el_fixture_de_dos_columnas_tiene_la_geometria_que_dice_tener(pdf_en_disco):
    """El generador es parte del contrato: si deja de producir dos columnas,
    los tests que dependan de él pasarían por la razón equivocada.

    Se comprueba la geometría -dos agrupaciones de bordes izquierdos separadas
    por una banda vacía- y que los renglones estén numerados en secuencia, que
    es lo que después permite afirmar cuál era el orden correcto.
    """
    ruta = pdf_en_disco(sinteticos.pdf_dos_columnas())
    documento = pymupdf.open(str(ruta))
    pagina = documento[0]

    izquierdas = sorted({round(b[0]) for b in pagina.get_text("blocks") if b[4].strip()})
    numeros = [int(n) for n in re.findall(r"\b(\d{3})\b", pagina.get_text())]
    documento.close()

    assert len(izquierdas) == 2, f"se esperaban dos columnas, hay {izquierdas}"
    assert izquierdas[1] - izquierdas[0] > 200, "las columnas tienen que estar bien separadas"
    assert numeros == list(range(1, len(numeros) + 1))
