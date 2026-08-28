"""Capa 3 (reconocimiento): que cada bloque vaya al engine que le corresponde.

Lo que se prueba acá es el **enrutamiento**, no la calidad del reconocimiento.
Son dos cosas distintas y conviene no mezclarlas: si un párrafo termina en
pix2tex o una fórmula en EasyOCR, ninguna mejora del modelo lo arregla, porque
el error ya ocurrió antes de que el modelo viera el recorte.

Por eso los tres engines se sustituyen por dobles que registran con qué los
llamaron. Eso mantiene la prueba determinista y sin descargar pesos —EasyOCR,
docTR y pix2tex bajan cientos de MB la primera vez— y además permite afirmar
lo contrario de lo habitual: que a un engine **no** se lo llamó.

El `skip` que tenía este archivo decía "pendiente: agregar fixtures PDF", pero
el enrutador recibe bloques e imágenes, no PDF.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from motor_ocr.reconocimiento import enrutador
from motor_ocr.modelos import Bloque, ModoMotor, OrigenContenido, TipoBloque
from motor_ocr.modelos.block import Contenido, Layout, Provenance, SegmentoCrudo


_DOCUMENTO_ID = uuid.uuid4()


def _bloque(
    tipo: TipoBloque,
    *,
    origen: OrigenContenido = OrigenContenido.REQUIERE_OCR,
    texto: str | None = None,
    segmentos: list[SegmentoCrudo] | None = None,
    capa: str = "prueba",
    bbox: tuple[float, float, float, float] = (0.1, 0.1, 0.9, 0.4),
) -> Bloque:
    return Bloque(
        documento_id=_DOCUMENTO_ID,
        pagina=0,
        tipo=tipo,
        layout=Layout(bbox=bbox, orden_lectura=0, confianza_layout=0.9),
        origen_contenido=origen,
        contenido=Contenido(texto_plano=texto),
        segmentos_capa2=segmentos or [],
        provenance=Provenance(creado_por_capa=capa),
    )


def _pagina(alto: int = 400, ancho: int = 300) -> np.ndarray:
    """Una página gris uniforme: al enrutador sólo le importa que haya píxeles."""
    return np.full((alto, ancho, 3), 220, dtype=np.uint8)


@pytest.fixture
def engines(monkeypatch):
    """Sustituye los tres engines y registra a cuál se llamó y cuántas veces.

    Se parchea el nombre tal como quedó ligado en `enrutador`, no en el módulo
    donde está definido: el enrutador hace `from .engines... import ocr_texto`,
    así que parchear el origen no cambiaría la referencia que ya resolvió.
    """
    llamadas: dict[str, int] = {"texto": 0, "formula": 0, "tabla": 0}

    def _texto(recorte, *a, **k):
        llamadas["texto"] += 1
        return "texto reconocido", 0.9

    def _formula(recorte, *a, **k):
        llamadas["formula"] += 1
        return r"\frac{a}{b}", 0.85

    def _tabla(recorte, *a, **k):
        # `reconocer_tabla` devuelve un dict con la estructura, no una tupla
        # como los otros dos engines. El doble tiene que respetar ese contrato
        # o la prueba falla por la forma del doble y no por el enrutamiento.
        llamadas["tabla"] += 1
        return {
            "filas": 1,
            "columnas": 2,
            "celdas": [
                {"bbox": (0, 0, 10, 10), "fila": 0, "columna": 0},
                {"bbox": (10, 0, 20, 10), "fila": 0, "columna": 1},
            ],
        }

    monkeypatch.setattr(enrutador, "ocr_texto", _texto)
    monkeypatch.setattr(enrutador, "ocr_formula", _formula)
    monkeypatch.setattr(enrutador, "reconocer_tabla", _tabla)
    return llamadas


# ============================================================================
# ENRUTAMIENTO POR TIPO DE BLOQUE
# ============================================================================

def test_enruta_formula_display_a_pix2tex(engines):
    """Una fórmula display va entera a pix2tex, sin sub-segmentar."""
    bloque = _bloque(TipoBloque.FORMULA_DISPLAY)
    enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert engines["formula"] == 1
    assert engines["texto"] == 0


def test_enruta_tabla_a_doctr(engines):
    bloque = _bloque(TipoBloque.TABLA)
    enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert engines["tabla"] == 1


@pytest.mark.parametrize(
    "tipo", [TipoBloque.ENCABEZADO, TipoBloque.CAPTION, TipoBloque.LISTA, TipoBloque.CODIGO]
)
def test_los_bloques_simples_van_a_easyocr(engines, tipo):
    enrutador.enrutar_bloque(_bloque(tipo), imagen_pagina=_pagina())

    assert engines["texto"] == 1
    assert engines["formula"] == 0


def test_enruta_parrafo_a_easyocr(engines):
    """Un párrafo escaneado sin fórmulas no debe tocar pix2tex."""
    bloque = _bloque(TipoBloque.PARRAFO)
    enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert engines["texto"] >= 1
    assert engines["tabla"] == 0


# ============================================================================
# LO QUE NO DEBE PASAR POR NINGÚN ENGINE
# ============================================================================

@pytest.mark.parametrize("tipo", [TipoBloque.RUIDO, TipoBloque.FIGURA])
def test_ni_el_ruido_ni_las_figuras_pasan_por_ocr(engines, tipo):
    """Reconocer una figura es gastar cómputo para producir basura."""
    resultado = enrutador.enrutar_bloque(_bloque(tipo), imagen_pagina=_pagina())

    assert resultado.contenido == ""
    assert sum(engines.values()) == 0
    assert resultado.requiere_escalacion is False


def test_el_texto_nativo_no_se_vuelve_a_reconocer(engines):
    """PyMuPDF ya entregó ese texto exacto y gratis: repetirlo sólo puede empeorarlo.

    Es la optimización central del motor. Si esta prueba falla, el pipeline
    está pagando OCR por páginas que no lo necesitan y, peor, sustituyendo
    texto exacto por texto reconocido.
    """
    bloque = _bloque(
        TipoBloque.PARRAFO,
        origen=OrigenContenido.TEXTO_NATIVO,
        texto="El teorema fundamental del calculo relaciona derivada e integral.",
    )
    resultado = enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert sum(engines.values()) == 0
    assert resultado.contenido == bloque.contenido.texto_plano


def test_lo_ya_reconocido_por_doctr_en_capa_2_no_se_reconoce_de_nuevo(engines):
    """docTR detecta y transcribe en la misma pasada: repetirlo se paga dos veces."""
    bloque = _bloque(
        TipoBloque.PARRAFO,
        texto="texto ya transcrito por doctr",
        capa="segmentation_escaneado_doctr",
    )
    resultado = enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert sum(engines.values()) == 0
    assert resultado.contenido == "texto ya transcrito por doctr"
    assert [m.engine_usado.value for m in resultado.micro_segmentos] == ["doctr"]


# ============================================================================
# SUB-SEGMENTACIÓN DE FÓRMULAS INLINE
# ============================================================================

def test_sub_segmenta_formula_inline_en_parrafo(engines):
    """Un párrafo nativo con tramos de fórmula marcados en capa 2 va a pix2tex.

    El texto plano de esos tramos ya perdió la estructura -exponentes,
    símbolos-, así que la única forma de recuperarla es reconocer el recorte.
    El resto del párrafo se conserva sin tocar.
    """
    bloque = _bloque(
        TipoBloque.PARRAFO,
        origen=OrigenContenido.TEXTO_NATIVO,
        texto="Sea x2 el cuadrado de x.",
        segmentos=[
            SegmentoCrudo(tipo="texto", texto="Sea "),
            SegmentoCrudo(tipo="formula", texto="x2", bbox=(0.2, 0.2, 0.3, 0.25)),
            SegmentoCrudo(tipo="texto", texto=" el cuadrado de x."),
        ],
    )
    enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert engines["formula"] >= 1, "el tramo de formula tiene que ir a pix2tex"


def test_un_parrafo_nativo_sin_tramos_de_formula_no_llama_a_pix2tex(engines):
    """El contrapunto: sin marca de capa 2 no hay motivo para reconocer nada."""
    bloque = _bloque(
        TipoBloque.PARRAFO,
        origen=OrigenContenido.TEXTO_NATIVO,
        texto="Un parrafo de prosa sin una sola formula.",
        segmentos=[SegmentoCrudo(tipo="texto", texto="Un parrafo de prosa.")],
    )
    enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert engines["formula"] == 0


# ============================================================================
# CASOS DE BORDE
# ============================================================================

def test_sin_imagen_de_pagina_no_revienta(engines):
    """Un bloque que requiere OCR pero llega sin píxeles tiene que degradar, no romper."""
    resultado = enrutador.enrutar_bloque(_bloque(TipoBloque.FORMULA_DISPLAY), imagen_pagina=None)

    assert resultado is not None
    assert resultado.confianza_global <= 1.0


def test_un_bbox_degenerado_no_revienta(engines):
    """Un bbox de área cero no puede tumbar la capa entera."""
    bloque = _bloque(TipoBloque.FORMULA_DISPLAY, bbox=(0.5, 0.5, 0.5, 0.5))
    resultado = enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert resultado is not None


# ============================================================================
# MODO SOLO_IA
# ============================================================================
#
# El modo existe para poder ver qué reconoce el modelo sin la ayuda del motor
# determinista. Lo que hay que probar entonces es lo contrario que arriba: que
# los atajos que el resto del archivo defiende **no** se aplican.

def test_solo_ia_manda_el_texto_nativo_al_modelo(engines):
    """El atajo del texto nativo se saltea a propósito: es el punto del modo."""
    bloque = _bloque(
        TipoBloque.PARRAFO,
        origen=OrigenContenido.TEXTO_NATIVO,
        texto="El teorema fundamental del calculo relaciona derivada e integral.",
    )
    resultado = enrutador.enrutar_bloque(
        bloque, imagen_pagina=_pagina(), modo=ModoMotor.SOLO_IA
    )

    assert engines["formula"] == 1
    assert engines["texto"] == 0
    assert resultado.contenido != bloque.contenido.texto_plano
    assert [m.engine_usado.value for m in resultado.micro_segmentos] == ["pix2tex"]


def test_solo_ia_reconoce_de_nuevo_lo_que_ya_transcribio_doctr(engines):
    bloque = _bloque(
        TipoBloque.PARRAFO,
        texto="texto ya transcrito por doctr",
        capa="segmentation_escaneado_doctr",
    )
    resultado = enrutador.enrutar_bloque(
        bloque, imagen_pagina=_pagina(), modo=ModoMotor.SOLO_IA
    )

    assert engines["formula"] == 1
    assert [m.engine_usado.value for m in resultado.micro_segmentos] == ["pix2tex"]


@pytest.mark.parametrize(
    "tipo", [TipoBloque.PARRAFO, TipoBloque.TABLA, TipoBloque.ENCABEZADO]
)
def test_solo_ia_no_usa_easyocr_ni_doctr_en_ningun_tipo(engines, tipo):
    """Ni siquiera la tabla, que en híbrido pasa por docTR más EasyOCR."""
    enrutador.enrutar_bloque(_bloque(tipo), imagen_pagina=_pagina(), modo=ModoMotor.SOLO_IA)

    assert engines["texto"] == 0
    assert engines["tabla"] == 0
    assert engines["formula"] == 1


@pytest.mark.parametrize("tipo", [TipoBloque.RUIDO, TipoBloque.FIGURA])
def test_solo_ia_sigue_sin_reconocer_ruido_ni_figuras(engines, tipo):
    """Mandarle una figura al modelo es gastar cómputo para producir basura,
    y eso no cambia porque el modo sea otro."""
    resultado = enrutador.enrutar_bloque(
        _bloque(tipo), imagen_pagina=_pagina(), modo=ModoMotor.SOLO_IA
    )

    assert sum(engines.values()) == 0
    assert resultado.contenido == ""


def test_el_modo_por_defecto_es_hibrido(engines):
    """Quien no elige nada tiene que seguir teniendo el motor de siempre."""
    bloque = _bloque(
        TipoBloque.PARRAFO, origen=OrigenContenido.TEXTO_NATIVO, texto="prosa exacta"
    )
    resultado = enrutador.enrutar_bloque(bloque, imagen_pagina=_pagina())

    assert sum(engines.values()) == 0
    assert resultado.contenido == "prosa exacta"


def test_solo_ia_no_deja_ningun_bloque_afuera_de_la_capa_3():
    """El filtro del pipeline también tiene que abrirse, no sólo el enrutador.

    Si `_requiere_capa3` siguiera descartando el bloque nativo, el modo no
    llegaría nunca a llamar al modelo por más que el enrutador esté listo.
    """
    from motor_ocr.pipeline import Pipeline

    nativo = _bloque(
        TipoBloque.PARRAFO, origen=OrigenContenido.TEXTO_NATIVO, texto="prosa exacta"
    )

    assert Pipeline._requiere_capa3(nativo, ModoMotor.HIBRIDO) is False
    assert Pipeline._requiere_capa3(nativo, ModoMotor.SOLO_IA) is True
