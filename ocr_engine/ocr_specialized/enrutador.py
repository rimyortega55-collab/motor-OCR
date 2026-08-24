"""Enrutamiento por tipo de bloque hacia el engine correcto (Capa 3).

parrafo/teorema/lema/demostracion/definicion/nota_pie:
    sub-segmentar en [texto, formula_inline]* -> texto: EasyOCR,
    formula_inline: pix2tex -> recomponer en una sola cadena.
formula_display:
    todo el bloque -> pix2tex directo (sin sub-segmentar).
tabla:
    docTR (estructura + celdas); celdas con notación matemática -> pix2tex.
encabezado/caption/lista/codigo:
    EasyOCR (con detección de fuente matemática por si aplica).
figura:
    sin OCR; se preserva como imagen embebida + caption asociado.

(PaddleOCR/PP-Structure descartados: CPU sin AVX, ver
.contexto/02-herramientas-stack.md.)
"""

from __future__ import annotations

import cv2
import numpy as np

from ocr_engine.models import (
    Bloque, TipoBloque, OrigenContenido, MicroSegmento, EngineOcr
)
from ocr_engine.models.results import BlockOcrResult, MicroSegmentoOcr

from .engines.easyocr_engine import ocr_texto
from .engines.pix2tex_engine import ocr_formula
from .engines.doctr_engine import reconocer_tabla
from .sub_segmentacion import sub_segmentar
from .confianza import calcular_confianza_micro_segmento, calcular_confianza_bloque


def enrutar_bloque(
    bloque: Bloque,
    imagen_pagina=None,
    dpi_objetivo: int = 150
) -> BlockOcrResult:
    """Enruta bloque al engine OCR apropiado según su tipo.

    Args:
        bloque: Bloque a procesar
        imagen_pagina: Imagen de la página (para bloques escaneados)
        dpi_objetivo: DPI para renderizado (de Capa 1)

    Returns:
        BlockOcrResult con contenido + micro-segmentos + confianza
    """

    # Bloques que no requieren OCR
    if bloque.tipo == TipoBloque.RUIDO or bloque.tipo == TipoBloque.FIGURA:
        return BlockOcrResult(
            id=bloque.id,
            contenido="",
            micro_segmentos=[],
            confianza_global=1.0,
            requiere_escalacion=False
        )

    # Si ya es nativo-digital, usar texto directamente
    if bloque.origen_contenido == OrigenContenido.TEXTO_NATIVO:
        return BlockOcrResult(
            id=bloque.id,
            contenido=bloque.contenido.texto_plano or "",
            micro_segmentos=[],
            confianza_global=0.95,
            requiere_escalacion=False
        )

    # Bloques que requieren OCR
    if bloque.tipo == TipoBloque.FORMULA_DISPLAY:
        return _procesar_formula_display(bloque, imagen_pagina)

    elif bloque.tipo == TipoBloque.TABLA:
        return _procesar_tabla(bloque, imagen_pagina)

    elif bloque.tipo in (
        TipoBloque.PARRAFO, TipoBloque.TEOREMA, TipoBloque.LEMA,
        TipoBloque.DEMOSTRACION, TipoBloque.DEFINICION, TipoBloque.NOTA_PIE
    ):
        return _procesar_bloque_texto_con_formulas(bloque, imagen_pagina, dpi_objetivo)

    else:  # ENCABEZADO, CAPTION, LISTA, CODIGO
        return _procesar_bloque_simple(bloque, imagen_pagina)

def _extraer_recorte_bloque(bloque: Bloque, imagen_pagina) -> np.ndarray | None:
    """Extrae el recorte de imagen correspondiente al bbox del bloque."""

    if imagen_pagina is None:
        return None

    bbox = bloque.layout.bbox
    x0, y0, x1, y1 = [int(c) for c in bbox]

    # Asegurar que está dentro de los límites
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(imagen_pagina.shape[1], x1)
    y1 = min(imagen_pagina.shape[0], y1)

    if x0 >= x1 or y0 >= y1:
        return None

    recorte = imagen_pagina[y0:y1, x0:x1]
    return recorte if recorte.size > 0 else None

def _procesar_formula_display(bloque: Bloque, imagen_pagina) -> BlockOcrResult:
    """Procesa bloque de fórmula display: pix2tex directo."""

    recorte = _extraer_recorte_bloque(bloque, imagen_pagina)
    if recorte is None:
        return BlockOcrResult(
            id=bloque.id,
            contenido="",
            micro_segmentos=[],
            confianza_global=0.0,
            requiere_escalacion=True
        )

    latex, confianza_engine = ocr_formula(recorte)

    # Validación estructural
    confianza_estructural = calcular_confianza_micro_segmento(
        confianza_engine, latex, es_formula=True
    )

    micro_seg = MicroSegmentoOcr(
        tipo="formula_display",
        contenido=latex,
        engine_usado=EngineOcr.PIX2TEX,
        confianza_engine=confianza_engine,
        confianza_estructural=confianza_estructural
    )

    return BlockOcrResult(
        id=bloque.id,
        contenido=latex,
        micro_segmentos=[micro_seg],
        confianza_global=confianza_estructural,
        requiere_escalacion=confianza_estructural < 0.6
    )

def _procesar_tabla(bloque: Bloque, imagen_pagina) -> BlockOcrResult:
    """Procesa bloque tabla: detecta estructura + OCR en celdas."""

    recorte = _extraer_recorte_bloque(bloque, imagen_pagina)
    if recorte is None:
        return BlockOcrResult(
            id=bloque.id,
            contenido="",
            micro_segmentos=[],
            confianza_global=0.0,
            requiere_escalacion=True
        )

    tabla_info = reconocer_tabla(recorte)

    # OCR en cada celda
    confianzas = []
    contenidos_celda = []

    for celda in tabla_info.get("celdas", []):
        # Extraer región de celda
        x0, y0, x1, y1 = [int(c) for c in celda["bbox"]]
        celda_recorte = recorte[y0:y1, x0:x1]

        if celda_recorte.size == 0:
            contenidos_celda.append("")
            continue

        # Intenta pix2tex primero (por si hay fórmulas)
        latex, conf_latex = ocr_formula(celda_recorte)
        if conf_latex > 0.7 and len(latex) > 3:
            contenidos_celda.append(latex)
            confianzas.append(conf_latex)
        else:
            # Fallback a EasyOCR
            texto, conf_texto = ocr_texto(celda_recorte)
            contenidos_celda.append(texto)
            confianzas.append(conf_texto)

    # Recomponer tabla en formato markdown
    tabla_markdown = _recomponer_tabla(tabla_info, contenidos_celda)

    confianza_global = np.mean(confianzas) if confianzas else 0.0

    return BlockOcrResult(
        id=bloque.id,
        contenido=tabla_markdown,
        micro_segmentos=[],
        confianza_global=confianza_global,
        requiere_escalacion=confianza_global < 0.6
    )

def _procesar_bloque_texto_con_formulas(
    bloque: Bloque, imagen_pagina, dpi_objetivo: int
) -> BlockOcrResult:
    """Procesa párrafo/teorema con sub-segmentación: texto + fórmulas."""

    recorte = _extraer_recorte_bloque(bloque, imagen_pagina)
    if recorte is None:
        return BlockOcrResult(
            id=bloque.id,
            contenido="",
            micro_segmentos=[],
            confianza_global=0.0,
            requiere_escalacion=True
        )

    # Sub-segmentar en [texto, formula_inline, ...]
    segmentos = sub_segmentar(bloque, imagen_pagina, dpi_objetivo)

    micro_segmentos = []
    contenido_final = []
    confianzas = []

    for tipo_seg, region in segmentos:
        # En escaneado la sub-segmentación devuelve el recorte de la región; en
        # nativo-digital devuelve texto, y ahí se cae al recorte del bloque.
        # Pasarle a pix2tex el bloque entero en vez de la región es la diferencia
        # entre ~0,3s y varios minutos por llamada.
        imagen_seg = region if isinstance(region, np.ndarray) and region.size else recorte

        if tipo_seg == "texto":
            texto, conf_engine = ocr_texto(imagen_seg)
            engine = EngineOcr.EASYOCR

        else:  # formula_inline
            texto, conf_engine = ocr_formula(imagen_seg)
            # Envolver en $...$
            if texto and not texto.startswith('$'):
                texto = f"${texto}$"
            engine = EngineOcr.PIX2TEX

        # Confianza estructural
        conf_struct = calcular_confianza_micro_segmento(
            conf_engine, texto, es_formula=(tipo_seg == "formula_inline")
        )

        micro_seg = MicroSegmentoOcr(
            tipo=tipo_seg,
            contenido=texto,
            engine_usado=engine,
            confianza_engine=conf_engine,
            confianza_estructural=conf_struct
        )

        micro_segmentos.append(micro_seg)
        contenido_final.append(texto)
        confianzas.append(conf_struct)

    contenido = " ".join(contenido_final)
    confianza_global = np.mean(confianzas) if confianzas else 0.0

    return BlockOcrResult(
        id=bloque.id,
        contenido=contenido,
        micro_segmentos=micro_segmentos,
        confianza_global=confianza_global,
        requiere_escalacion=confianza_global < 0.6
    )

def _procesar_bloque_simple(bloque: Bloque, imagen_pagina) -> BlockOcrResult:
    """Procesa encabezado/caption/lista/código: EasyOCR directo."""

    recorte = _extraer_recorte_bloque(bloque, imagen_pagina)
    if recorte is None:
        return BlockOcrResult(
            id=bloque.id,
            contenido="",
            micro_segmentos=[],
            confianza_global=0.0,
            requiere_escalacion=True
        )

    texto, confianza_engine = ocr_texto(recorte)

    confianza_estructural = calcular_confianza_micro_segmento(
        confianza_engine, texto, es_formula=False
    )

    micro_seg = MicroSegmentoOcr(
        tipo="texto",
        contenido=texto,
        engine_usado=EngineOcr.EASYOCR,
        confianza_engine=confianza_engine,
        confianza_estructural=confianza_estructural
    )

    return BlockOcrResult(
        id=bloque.id,
        contenido=texto,
        micro_segmentos=[micro_seg],
        confianza_global=confianza_estructural,
        requiere_escalacion=confianza_estructural < 0.6
    )

def _recomponer_tabla(tabla_info: dict, contenidos_celda: list[str]) -> str:
    """Recompone tabla en formato Markdown."""

    filas = tabla_info.get("filas", 0)
    cols = tabla_info.get("columnas", 0)

    if filas == 0 or cols == 0 or not contenidos_celda:
        return ""

    # Crear matriz
    matriz = []
    idx = 0
    for f in range(filas):
        fila = []
        for c in range(cols):
            if idx < len(contenidos_celda):
                fila.append(contenidos_celda[idx])
                idx += 1
            else:
                fila.append("")
        matriz.append(fila)

    # Convertir a markdown
    lineas = []
    for f, fila in enumerate(matriz):
        lineas.append("| " + " | ".join(fila) + " |")
        if f == 0:
            lineas.append("|" + "|".join(["-" * 5 for _ in fila]) + "|")

    return "\n".join(lineas)
