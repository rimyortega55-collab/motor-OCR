"""Wrapper de docTR — layout detection + estructura de tabla.

Reemplaza a PP-Structure (submódulo de PaddleOCR, descartado por
incompatibilidad de hardware — CPU sin AVX, ver
.contexto/02-herramientas-stack.md). Se reutiliza en dos puntos del
pipeline: layout detection de páginas escaneadas (Capa 2,
segmentation/escaneado.py) y estructura/celdas de bloques `tabla` (Capa 3).
"""

from __future__ import annotations

import cv2
import numpy as np

_predictor = None

def _get_predictor():
    """Lazy loader para doctr predictor."""
    global _predictor
    if _predictor is None:
        try:
            from doctr.io import DocumentFile
            from doctr.models import ocr_predictor
            _predictor = ocr_predictor(pretrained=True, assume_straight_pages=True)
        except ImportError:
            print("[docTR] No instalado, fallback a heurísticas")
            return None
    return _predictor

def detectar_layout(imagen_pagina) -> list[dict]:
    """Devuelve regiones detectadas: bbox, tipo aproximado, orden."""
    if imagen_pagina is None or imagen_pagina.size == 0:
        return []

    try:
        predictor = _get_predictor()
        if predictor is None:
            # Fallback a heurística simple: detectar líneas y regiones
            return _detectar_layout_heuristico(imagen_pagina)

        # Ensure uint8
        if imagen_pagina.dtype != np.uint8:
            if imagen_pagina.max() <= 1.0:
                imagen_pagina = (imagen_pagina * 255).astype(np.uint8)
            else:
                imagen_pagina = imagen_pagina.astype(np.uint8)

        # doctr works with file-like or PIL Image
        from PIL import Image
        if len(imagen_pagina.shape) == 2:
            pil_image = Image.fromarray(imagen_pagina)
        else:
            pil_image = Image.fromarray(cv2.cvtColor(imagen_pagina, cv2.COLOR_BGR2RGB))

        # Predict
        doc = predictor([pil_image])
        pages = doc.pages

        regiones = []
        if pages:
            page = pages[0]
            for block_idx, block in enumerate(page.blocks):
                bbox = block.geometry
                regiones.append({
                    "bbox": (bbox[0][0], bbox[0][1], bbox[1][0], bbox[1][1]),
                    "tipo": "texto",  # doctr no distingue tipos
                    "orden": block_idx
                })

        return regiones

    except Exception as e:
        print(f"[docTR] Error en detectar_layout: {e}")
        return _detectar_layout_heuristico(imagen_pagina)

def _detectar_layout_heuristico(imagen):
    """Fallback: detección simple de regiones conectadas."""
    if len(imagen.shape) == 3:
        gray = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    else:
        gray = imagen

    _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    regiones = []
    for i, contour in enumerate(contours):
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        page_area = gray.shape[0] * gray.shape[1]

        # Filtrar por tamaño: 1% a 90%
        if 0.01 * page_area < area < 0.9 * page_area:
            regiones.append({
                "bbox": (float(x), float(y), float(x + w), float(y + h)),
                "tipo": "texto",
                "orden": i
            })

    # Ordenar top-to-bottom, left-to-right
    regiones.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))

    return regiones

def reconocer_tabla(imagen_recorte) -> dict:
    """Devuelve estructura de tabla: filas, columnas y contenido por celda.

    Args:
        imagen_recorte: numpy array de la región tabla

    Returns:
        {
            "filas": int,
            "columnas": int,
            "celdas": [{"fila": int, "col": int, "bbox": tuple, "contenido_crudo": str}]
        }
    """
    if imagen_recorte is None or imagen_recorte.size == 0:
        return {"filas": 0, "columnas": 0, "celdas": []}

    try:
        # Detect table structure using simple heuristics
        if len(imagen_recorte.shape) == 3:
            gray = cv2.cvtColor(imagen_recorte, cv2.COLOR_BGR2GRAY)
        else:
            gray = imagen_recorte

        # Detect vertical and horizontal lines
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)

        # Morphology to enhance lines
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))

        lines_h = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_h, iterations=1)
        lines_v = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_v, iterations=1)

        # Combine
        lines = cv2.bitwise_or(lines_h, lines_v)

        # Find contours to estimate cells
        contours, _ = cv2.findContours(lines, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return {"filas": 1, "columnas": 1, "celdas": [{
                "fila": 0, "col": 0, "bbox": (0, 0, imagen_recorte.shape[1], imagen_recorte.shape[0]),
                "contenido_crudo": ""
            }]}

        # Estimate grid dimensions
        bboxes = [cv2.boundingRect(c) for c in contours]
        x_coords = sorted(set(b[0] for b in bboxes if b[2] > 10))
        y_coords = sorted(set(b[1] for b in bboxes if b[3] > 10))

        num_cols = max(2, len(x_coords) // 3)
        num_rows = max(2, len(y_coords) // 3)

        # Create cell grid
        celdas = []
        height, width = gray.shape
        cell_w = width // num_cols
        cell_h = height // num_rows

        for fila in range(num_rows):
            for col in range(num_cols):
                y0 = fila * cell_h
                y1 = (fila + 1) * cell_h
                x0 = col * cell_w
                x1 = (col + 1) * cell_w

                celdas.append({
                    "fila": fila,
                    "col": col,
                    "bbox": (float(x0), float(y0), float(x1), float(y1)),
                    "contenido_crudo": ""
                })

        return {
            "filas": num_rows,
            "columnas": num_cols,
            "celdas": celdas
        }

    except Exception as e:
        print(f"[docTR] Error en reconocer_tabla: {e}")
        return {"filas": 0, "columnas": 0, "celdas": []}
