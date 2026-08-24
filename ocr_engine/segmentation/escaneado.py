"""Segmentación de páginas escaneadas vía docTR (layout detection).

Detecta regiones: texto, título, tabla, figura, fórmula. La salida se
convierte a `Bloque` con `origen_contenido = requiere_ocr`, listo para el
enrutamiento de Capa 3. (PP-Structure/PaddleOCR descartados: CPU sin AVX,
ver docs/contexto/02-herramientas-stack.md.)

docTR es el camino principal y la morfología con OpenCV quedó como respaldo
para cuando el modelo no está disponible. Medido sobre el mismo documento, la
heurística alcanzaba un 16,7% de similitud contra el texto real: agrupaba
glifos por proximidad, generaba regiones solapadas que hacían que un mismo
renglón se transcribiera dos veces, y perdía el orden de lectura. Con docTR la
similitud sube a 80,1%.

Se aprovecha además que el predictor de docTR detecta y reconoce en una sola
pasada: el texto viaja en el bloque para que la Capa 3 no vuelva a pagar un OCR
sobre el mismo recorte.
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
    """Segmenta una página escaneada, con docTR si está disponible."""

    if imagen_pagina is None:
        return []

    bloques = _segmentar_con_doctr(documento, imagen_pagina, pagina)
    if bloques:
        return bloques

    return _segmentar_con_morfologia(documento, imagen_pagina, pagina)


def _segmentar_con_doctr(documento: Documento, imagen_pagina, pagina: int) -> list[Bloque]:
    """Un bloque por línea detectada por docTR, con su texto y su confianza.

    Se usa la línea y no el bloque de docTR porque su agrupación en párrafos
    devuelve la página entera como una sola región, inservible para segmentar.
    La línea, en cambio, es una unidad que el detector resuelve bien.
    """

    try:
        from ocr_engine.ocr_specialized.engines.doctr_engine import detectar_layout
        regiones = detectar_layout(imagen_pagina)
    except Exception as e:
        print(f"[SEGMENTACION] docTR no disponible ({e}); se usa morfología")
        return []

    # Sin texto reconocido no hay ventaja sobre el respaldo, y probablemente
    # detectar_layout ya cayó en su propia heurística interna.
    if not regiones or not any(r.get("texto") for r in regiones):
        return []

    alto, ancho = imagen_pagina.shape[:2]
    bloques = []

    for orden, region in enumerate(regiones):
        x0, y0, x1, y1 = region["bbox"]
        texto = (region.get("texto") or "").strip()
        if not texto:
            continue

        ancho_region = x1 - x0
        alto_region = y1 - y0

        # Un renglón corto y ancho cerca del margen superior suele ser título;
        # sin un clasificador de layout real no se puede afinar más que esto.
        if alto_region <= alto * 0.02 and ancho_region > ancho * 0.25 and y0 < alto * 0.2:
            tipo = TipoBloque.ENCABEZADO
        else:
            tipo = TipoBloque.PARRAFO

        bloques.append(Bloque(
            id=uuid4(),
            documento_id=documento.documento_id,
            pagina=pagina,
            tipo=tipo,
            layout=Layout(
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                orden_lectura=orden,
                confianza_layout=float(region.get("confianza", 0.0)),
            ),
            origen_contenido=OrigenContenido.REQUIERE_OCR,
            # El texto ya reconocido viaja con el bloque; la Capa 3 lo reutiliza
            # en vez de correr otro engine sobre el mismo recorte.
            contenido=Contenido(texto_plano=texto),
            provenance=Provenance(creado_por_capa="segmentation_escaneado_doctr"),
        ))

    return bloques


def _segmentar_con_morfologia(documento: Documento, imagen_pagina, pagina: int) -> list[Bloque]:
    """Respaldo sin docTR: detecta regiones de texto con OpenCV.

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
