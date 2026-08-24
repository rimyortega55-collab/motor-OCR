"""Detección de fórmulas inline dentro de bloques de texto, antes del OCR.

- Nativo-digital: cambios de fuente matemática dentro de la misma línea
  (misma señal que triage/deteccion_fuentes.py).
- Escaneado: componentes conectados con proporciones/densidad distintas al
  texto circundante (superíndices, símbolos aislados, fracciones).

Resultado: secuencia de micro-segmentos [texto, formula_inline, texto, ...],
cada uno enrutado a su engine por `enrutador.py` y luego recompuesto en
orden en una sola cadena (LaTeX con $...$ incrustado). Aplica a los tipos
parrafo, teorema, lema, demostracion, definicion, nota_pie.
"""

from __future__ import annotations

import cv2
import numpy as np
import re
from uuid import uuid4

from ocr_engine.models import Bloque, OrigenContenido, Layout, Contenido, Provenance


def sub_segmentar(bloque: Bloque, imagen_pagina=None, dpi_objetivo: int = 150) -> list[tuple[str, object]]:
    """Devuelve [(tipo, contenido_crudo), ...] con tipo en {"texto", "formula_inline"}.

    Args:
        bloque: Bloque a sub-segmentar (debe estar en escaneado para usar imagen)
        imagen_pagina: Imagen de la página (para bloques escaneados)
        dpi_objetivo: DPI a usar para renderizado

    Returns:
        Lista de (tipo, contenido_crudo), donde `contenido_crudo` es el texto del
        segmento en nativo-digital y el recorte (ndarray) de su región en escaneado.

        Devolver la región importa por rendimiento, no sólo por precisión: pix2tex
        es autoregresivo y su costo depende del largo de la secuencia que genera.
        Sobre el recorte ajustado de una fórmula responde en ~0,3s; sobre el bloque
        entero de texto corrido tarda casi 4 minutos produciendo tokens basura.
    """

    # Para nativo-digital: analizar cambios de fuente
    if bloque.origen_contenido == OrigenContenido.TEXTO_NATIVO:
        return _sub_segmentar_nativo_digital(bloque)

    # Para escaneado: usar visión por computadora
    elif imagen_pagina is not None:
        return _sub_segmentar_escaneado(bloque, imagen_pagina, dpi_objetivo)

    # Fallback: asumir todo como texto
    return [("texto", "")]

def _sub_segmentar_nativo_digital(bloque: Bloque) -> list[tuple[str, str]]:
    """Detecta cambios de fuente matemática en PDF nativo-digital."""
    # Para nativo-digital, se requeriría acceso a la estructura PDF
    # Por ahora, usar heurísticas de regex
    # Detectar $...$ y \[...\] en el texto

    if not bloque.contenido.texto_plano:
        return [("texto", "")]

    texto = bloque.contenido.texto_plano

    # Patrones: $...$ o \[...\]
    pattern = r'(\$\$[^\$]*\$\$|\$[^\$]+\$|\\\\[\[].*?\\\\[\]])'
    segments = []
    last_end = 0

    for match in re.finditer(pattern, texto):
        start, end = match.span()

        # Agregar texto antes de la fórmula
        if start > last_end:
            text_segment = texto[last_end:start].strip()
            if text_segment:
                segments.append(("texto", text_segment))

        # Agregar fórmula
        formula = match.group(1).strip()
        if formula:
            segments.append(("formula_inline", formula))

        last_end = end

    # Agregar texto restante
    if last_end < len(texto):
        text_segment = texto[last_end:].strip()
        if text_segment:
            segments.append(("texto", text_segment))

    # Si no hay segmentación, todo es texto
    if not segments:
        segments = [("texto", texto)]

    return segments

def _sub_segmentar_escaneado(bloque: Bloque, imagen_pagina, dpi_objetivo: int) -> list[tuple[str, str]]:
    """Detecta regiones de fórmula en imagen usando características visuales."""

    bbox = bloque.layout.bbox
    x0, y0, x1, y1 = [int(c) for c in bbox]

    # Recorte de la región
    recorte = imagen_pagina[y0:y1, x0:x1]

    if recorte.size == 0:
        return [("texto", "")]

    # Convertir a escala de grises
    if len(recorte.shape) == 3:
        gray = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    else:
        gray = recorte

    # Binarización con Otsu e inversión: el texto queda como frente (blanco), que
    # es lo que findContours busca. Con THRESH_BINARY directo los contornos salen
    # del fondo de la página, no de los glifos.
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )

    # Detectar componentes conectadas
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return [("texto", "")]

    # Altura típica de glifo en el bloque: sirve de referencia para distinguir un
    # símbolo matemático (que se sale de la caja de texto) de una letra normal.
    alturas = [cv2.boundingRect(c)[3] for c in contours if cv2.contourArea(c) >= 10]
    if not alturas:
        return [("texto", "")]
    alto_tipico = float(np.median(alturas))

    # Clasificar regiones por características
    componentes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)

        if area < 10:  # Ruido
            continue

        # Calcular características
        aspect_ratio = w / h if h > 0 else 0
        compactness = area / (w * h) if w > 0 and h > 0 else 0

        # Un aspect ratio extremo por sí solo no distingue nada: las letras
        # angostas corrientes ("l", "i", "1", paréntesis) lo cumplen, y marcarlas
        # como fórmula mandaba bloques de texto plano al engine de LaTeX. Se exige
        # además que el componente se salga del alto de línea típico, que es lo que
        # de verdad delata fracciones, sumatorias, radicales o superíndices.
        desviado = h > alto_tipico * 1.8 or h < alto_tipico * 0.35
        is_formula = (
            desviado
            and compactness > 0.4
            and (aspect_ratio < 0.3 or aspect_ratio > 3)
        )

        componentes.append({
            "x": x, "y": y, "w": w, "h": h,
            "area": area,
            "aspect_ratio": aspect_ratio,
            "is_formula": is_formula
        })

    # Agrupar componentes por proximidad (líneas de texto)
    if not componentes:
        return [("texto", "")]

    # Ordenar por posición Y para encontrar líneas
    componentes.sort(key=lambda c: c["y"])

    lineas = []
    current_linea = []
    last_y = None

    for comp in componentes:
        y = comp["y"]

        # ¿Mismo nivel (línea)?
        if last_y is not None and abs(y - last_y) > 20:
            if current_linea:
                lineas.append(current_linea)
            current_linea = [comp]
        else:
            current_linea.append(comp)

        last_y = y + comp["h"] // 2

    if current_linea:
        lineas.append(current_linea)

    # Partir cada línea en tramos de texto y de fórmula según la posición
    # horizontal de los componentes. Marcar la línea entera cuando cualquier
    # componente parecía fórmula mandaba renglones de texto corrido completos a
    # pix2tex: lento (el costo crece con el largo de la secuencia generada) y con
    # un LaTeX de calidad pobre, porque la mayor parte del recorte es prosa.
    segmentos = []
    for linea in lineas:
        for tipo, tramo in _partir_linea_en_tramos(linea):
            xs = [c["x"] for c in tramo]
            ys = [c["y"] for c in tramo]
            ws = [c["x"] + c["w"] for c in tramo]
            hs = [c["y"] + c["h"] for c in tramo]

            region_x0 = max(0, min(xs) - 5)
            region_y0 = max(0, min(ys) - 5)
            region_x1 = min(recorte.shape[1], max(ws) + 5)
            region_y1 = min(recorte.shape[0], max(hs) + 5)

            region = recorte[region_y0:region_y1, region_x0:region_x1]
            if region.size:
                segmentos.append((tipo, region))

    return segmentos or [("texto", recorte)]


# Un componente suelto marcado como fórmula casi siempre es una letra angosta mal
# clasificada; una fórmula real aporta varios (símbolo, exponente, barra de fracción).
_MIN_COMPONENTES_FORMULA = 2


def _partir_linea_en_tramos(linea: list[dict]) -> list[tuple[str, list[dict]]]:
    """Divide una línea en tramos consecutivos de "texto" y "formula_inline"."""

    if not linea:
        return []

    ordenados = sorted(linea, key=lambda c: c["x"])

    # Agrupar componentes contiguos que compartan la misma clasificación
    tramos: list[tuple[bool, list[dict]]] = []
    for comp in ordenados:
        if tramos and tramos[-1][0] == comp["is_formula"]:
            tramos[-1][1].append(comp)
        else:
            tramos.append((comp["is_formula"], [comp]))

    # Degradar a texto los tramos de fórmula demasiado chicos para ser creíbles
    normalizados = [
        (es_formula and len(comps) >= _MIN_COMPONENTES_FORMULA, comps)
        for es_formula, comps in tramos
    ]

    # Volver a unir tramos vecinos que quedaron con el mismo tipo tras degradar
    fusionados: list[tuple[bool, list[dict]]] = []
    for es_formula, comps in normalizados:
        if fusionados and fusionados[-1][0] == es_formula:
            fusionados[-1][1].extend(comps)
        else:
            fusionados.append((es_formula, list(comps)))

    return [
        ("formula_inline" if es_formula else "texto", comps)
        for es_formula, comps in fusionados
    ]
