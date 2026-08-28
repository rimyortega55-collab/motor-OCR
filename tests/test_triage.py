"""Capa 1 (triage): de que tipo es cada pagina y cuanto hay que gastar en ella.

Es la capa que decide el costo de todo lo que sigue. Si clasifica de mas, el
motor manda a OCR paginas que PyMuPDF ya entrega exactas y gratis; si clasifica
de menos, una pagina escaneada sale vacia y el error se propaga hasta el
export sin que nadie lo note.

Estas pruebas corren contra los PDF sinteticos de `tests/fixtures/sinteticos.py`,
que se generan en el momento. Eso alcanza para fijar el comportamiento -que la
capa distinga capa de texto de imagen, que reconozca una fuente matematica, que
agrupe paginas contiguas- sin depender de ningun binario versionado. Lo que no
alcanzan a medir es fidelidad sobre material real: para eso esta el corpus con
licencia redistribuible descrito en `tests/fixtures/MANIFEST.md`.
"""

from __future__ import annotations

import pytest

from motor_ocr.triage import (
    detectar_fuentes_matematicas,
    detectar_origen,
    procesar_triage,
    zonificar_paginas,
)
from motor_ocr.modelos import Origen

from tests.fixtures import sinteticos


# ============================================================================
# ORIGEN: NATIVO-DIGITAL VS ESCANEADO
# ============================================================================

def test_detecta_origen_nativo_digital(pdf_en_disco):
    """Con capa de texto inspeccionable, la pagina es nativo-digital."""
    ruta = pdf_en_disco(sinteticos.pdf_texto())
    assert detectar_origen(str(ruta), 0) is Origen.NATIVO_DIGITAL


def test_detecta_origen_escaneado(pdf_en_disco):
    """Sin texto que extraer, la pagina se trata como escaneada."""
    ruta = pdf_en_disco(sinteticos.pdf_escaneado())
    assert detectar_origen(str(ruta), 0) is Origen.ESCANEADO


def test_una_pagina_que_no_existe_no_revienta(pdf_en_disco):
    """Un indice fuera de rango cae del lado caro, no en una excepcion.

    Preferir `ESCANEADO` ante la duda es deliberado: equivocarse hacia el pase
    visual cuesta computo, equivocarse hacia el otro lado devuelve una pagina
    en blanco sin aviso.
    """
    ruta = pdf_en_disco(sinteticos.pdf_texto())
    assert detectar_origen(str(ruta), 99) is Origen.ESCANEADO
    assert detectar_origen(str(ruta), -1) is Origen.ESCANEADO


# ============================================================================
# FUENTES MATEMATICAS
# ============================================================================

def test_la_prosa_sin_matematica_no_declara_fuentes(pdf_en_disco):
    ruta = pdf_en_disco(sinteticos.pdf_texto())
    assert detectar_fuentes_matematicas(str(ruta), 0) == []


def test_una_fuente_matematica_embebida_se_detecta(pdf_en_disco):
    ruta = pdf_en_disco(sinteticos.pdf_con_matematica())
    assert detectar_fuentes_matematicas(str(ruta), 0) == ["Symbol"]


# ============================================================================
# DECISION DE COSTO: DPI Y NECESIDAD DE OCR
# ============================================================================

def test_la_prosa_nativa_se_saltea_el_ocr(pdf_en_disco):
    """La unica combinacion gratis del motor: nativo-digital y sin formulas."""
    ruta = pdf_en_disco(sinteticos.pdf_texto(paginas=2))
    resultados, _ = procesar_triage(str(ruta))

    assert [r.origen for r in resultados] == ["nativo_digital"] * 2
    assert all(r.requiere_ocr is False for r in resultados)
    assert all(r.dpi_objetivo == 200 for r in resultados)


def test_la_matematica_nativa_sube_el_dpi_y_pide_ocr(pdf_en_disco):
    """Hay capa de texto, pero la notacion igual necesita el pase de reconocimiento."""
    ruta = pdf_en_disco(sinteticos.pdf_con_matematica())
    resultados, _ = procesar_triage(str(ruta))

    assert resultados[0].origen == "nativo_digital"
    assert resultados[0].requiere_ocr is True
    assert resultados[0].dpi_objetivo == 300
    assert resultados[0].fuentes_detectadas == ["Symbol"]


def test_lo_escaneado_siempre_pide_ocr(pdf_en_disco):
    ruta = pdf_en_disco(sinteticos.pdf_escaneado())
    resultados, _ = procesar_triage(str(ruta))

    assert resultados[0].origen == "escaneado"
    assert resultados[0].requiere_ocr is True
    assert resultados[0].dpi_objetivo >= 200


# ============================================================================
# ZONIFICACION
# ============================================================================

def test_zonifica_paginas_contiguas_por_perfil(pdf_en_disco):
    """Paginas seguidas del mismo perfil comparten zona; un cambio la corta.

    El PDF mixto son dos paginas de prosa, una con matematica y una escaneada.
    Las dos primeras salen a 200 DPI y las dos ultimas a 300, asi que la
    zonificacion tiene que devolver exactamente dos zonas contiguas que cubran
    las cuatro paginas sin huecos ni solapamientos.
    """
    ruta = pdf_en_disco(sinteticos.pdf_mixto())
    resultados, zonas = procesar_triage(str(ruta))

    assert len(resultados) == 4
    assert [(z.paginas, z.dpi) for z in zonas] == [((0, 1), 200), ((2, 3), 300)]


def test_un_documento_uniforme_da_una_sola_zona(pdf_en_disco):
    """El contrapunto del test anterior: sin cambio de perfil no hay corte."""
    ruta = pdf_en_disco(sinteticos.pdf_texto(paginas=5))
    _, zonas = procesar_triage(str(ruta))

    assert len(zonas) == 1
    assert zonas[0].paginas == (0, 4)


def test_las_zonas_cubren_todas_las_paginas(pdf_en_disco):
    """Ninguna pagina puede quedar fuera de una zona: se dejaria sin renderizar."""
    ruta = pdf_en_disco(sinteticos.pdf_mixto())
    resultados, zonas = procesar_triage(str(ruta))

    cubiertas = [p for z in zonas for p in range(z.paginas[0], z.paginas[1] + 1)]
    assert cubiertas == list(range(len(resultados)))


def test_un_documento_sin_paginas_no_inventa_zonas():
    """Cero paginas es cero zonas, no una zona vacia ni una excepcion."""
    assert zonificar_paginas([]) == []


def test_un_pdf_sin_paginas_atraviesa_la_capa(pdf_en_disco):
    ruta = pdf_en_disco(sinteticos.pdf_vacio())
    resultados, zonas = procesar_triage(str(ruta))

    assert resultados == []
    assert zonas == []
