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
    """Segmenta página escaneada usando detección básica de regiones con OpenCV.

    Para producción, integrar docTR. Este es un fallback con heurísticas simples.
    """
    if imagen_pagina is None:
        return []

    # Convert to grayscale if needed
    if len(imagen_pagina.shape) == 3:
        gray = cv2.cvtColor(imagen_pagina, cv2.COLOR_RGB2GRAY)
    else:
        gray = imagen_pagina

    # Binary threshold
    _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)

    # Find contours (regions)
    contours, _ = cv2.findContours(
        binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )

    bloques = []
    orden_lectura = 0

    # Filter contours by size
    min_area = (gray.shape[0] * gray.shape[1]) * 0.01  # 1% of page
    max_area = (gray.shape[0] * gray.shape[1]) * 0.9   # 90% of page

    regions = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if min_area < area < max_area:
            x, y, w, h = cv2.boundingRect(contour)
            regions.append((x, y, x + w, y + h, area))

    # Sort regions top to bottom, then left to right
    regions.sort(key=lambda r: (r[1], r[0]))

    # Classify regions by aspect ratio
    for x0, y0, x1, y1, area in regions:
        width = x1 - x0
        height = y1 - y0
        aspect_ratio = width / height if height > 0 else 0

        # Heuristics for type detection
        if aspect_ratio > 3:  # very wide
            tipo = TipoBloque.TABLA
        elif aspect_ratio < 0.33:  # very tall
            tipo = TipoBloque.LISTA
        elif width > height * 0.8 and height > width * 0.5:  # roughly square
            tipo = TipoBloque.FIGURA
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
