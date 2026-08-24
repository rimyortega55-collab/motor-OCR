"""Segmentación de páginas escaneadas vía docTR (layout detection).

Detecta regiones: texto, título, tabla, figura, fórmula. La salida se
convierte a `Bloque` con `origen_contenido = requiere_ocr`, listo para el
enrutamiento de Capa 3. (PP-Structure/PaddleOCR descartados: CPU sin AVX,
ver .contexto/02-herramientas-stack.md.)
"""

from __future__ import annotations

from ocr_engine.models import Bloque, Documento


import cv2
import numpy as np
from uuid import uuid4
from datetime import datetime

from ocr_engine.models import (
    Bloque,
    Documento,
    Layout,
    OrigenContenido,
    Contenido,
    TipoBloque,
    Provenance,
)


def segmentar_escaneado(documento: Documento, imagen_pagina, pagina: int) -> list[Bloque]:
    """Segmenta página escaneada detectando regiones de texto con OpenCV.

    Para producción, integrar docTR. Este es un fallback con heurísticas simples.

    El agrupamiento morfológico es imprescindible: los contornos crudos de una
    página escaneada son glifos sueltos de unos pocos cientos de píxeles, muy por
    debajo de cualquier umbral de área razonable para un bloque. Sin dilatar
    primero, el filtro los descarta a todos y la página no produce ningún bloque.
    """
    if imagen_pagina is None:
        return []

    # Convert to grayscale if needed
    if len(imagen_pagina.shape) == 3:
        gray = cv2.cvtColor(imagen_pagina, cv2.COLOR_RGB2GRAY)
    else:
        gray = imagen_pagina

    alto_pagina, ancho_pagina = gray.shape[:2]

    # Otsu + inversión: el texto queda como frente (blanco). Otsu se adapta al
    # brillo del escaneo, cosa que un umbral fijo de 127 no hace.
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )

    # Unir glifos en líneas y líneas en bloques. El kernel se escala con el ancho
    # de página para que el resultado no dependa del DPI de renderizado.
    ancho_kernel = max(3, int(ancho_pagina * 0.02))
    alto_kernel = max(3, int(alto_pagina * 0.003))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (ancho_kernel, alto_kernel)
    )
    agrupado = cv2.dilate(binary, kernel, iterations=2)

    # RETR_EXTERNAL: sólo el contorno exterior de cada región, sin anidados
    # duplicados dentro del mismo bloque.
    contours, _ = cv2.findContours(
        agrupado, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    bloques = []
    orden_lectura = 0

    # Descartar ruido (motas, bordes de escaneo) y la página entera como región
    min_ancho = ancho_pagina * 0.04
    min_alto = max(8, alto_pagina * 0.004)
    max_area = alto_pagina * ancho_pagina * 0.9

    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < min_ancho or h < min_alto or (w * h) > max_area:
            continue
        # Densidad de tinta dentro de la caja: separa texto de figuras/fondos
        recorte = binary[y:y + h, x:x + w]
        densidad = float((recorte > 0).mean()) if recorte.size else 0.0
        regions.append((x, y, x + w, y + h, densidad))

    # Sort regions top to bottom, then left to right
    regions.sort(key=lambda r: (r[1], r[0]))

    for x0, y0, x1, y1, densidad in regions:
        width = x1 - x0
        height = y1 - y0

        # Clasificación deliberadamente conservadora: sin un modelo de layout real
        # se prefiere PARRAFO, que enruta al camino de texto+fórmulas de Capa 3.
        # Marcar de más como TABLA mandaría texto corrido al parser de tablas.
        if densidad < 0.05:
            tipo = TipoBloque.FIGURA
        elif height <= min_alto * 2.5 and width > ancho_pagina * 0.25:
            tipo = TipoBloque.ENCABEZADO
        else:
            tipo = TipoBloque.PARRAFO

        bloque = Bloque(
            id=uuid4(),
            documento_id=documento.documento_id,
            pagina=pagina,
            tipo=tipo,
            layout=Layout(
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                orden_lectura=orden_lectura,
                confianza_layout=0.6,  # lower confidence for scanned
            ),
            origen_contenido=OrigenContenido.REQUIERE_OCR,
            contenido=Contenido(),
            provenance=Provenance(creado_por_capa="segmentation_escaneado"),
        )
        bloques.append(bloque)
        orden_lectura += 1

    return bloques
