"""Wrapper de pix2tex (LaTeX-OCR) — reconocimiento de fórmulas a LaTeX.

Se usa tanto para bloques `formula_display` completos (directo, sin
sub-segmentar) como para micro-segmentos `formula_inline` dentro de bloques
de texto, y para celdas de tabla con notación matemática.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

_model = None

def _get_model():
    """Lazy loader para pix2tex model (costoso de inicializar)."""
    global _model
    if _model is None:
        try:
            from pix2tex.cli import LatexOCR
            _model = LatexOCR()
        except ImportError:
            print("[pix2tex] No instalado, fallback a tesseract")
            return None
    return _model

def ocr_formula(imagen_recorte) -> tuple[str, float]:
    """Devuelve (latex_reconocido, confianza_engine).

    Args:
        imagen_recorte: numpy array (H, W) o (H, W, 3)

    Returns:
        (latex_formula, confidence)
    """
    if imagen_recorte is None or imagen_recorte.size == 0:
        return "", 0.0

    try:
        model = _get_model()
        if model is None:
            return "", 0.0

        # Ensure image is uint8
        if imagen_recorte.dtype != np.uint8:
            if imagen_recorte.max() <= 1.0:
                imagen_recorte = (imagen_recorte * 255).astype(np.uint8)
            else:
                imagen_recorte = imagen_recorte.astype(np.uint8)

        # Convert to RGB if grayscale
        if len(imagen_recorte.shape) == 2:
            imagen_recorte = cv2.cvtColor(imagen_recorte, cv2.COLOR_GRAY2RGB)
        elif len(imagen_recorte.shape) == 3 and imagen_recorte.shape[2] == 4:
            imagen_recorte = cv2.cvtColor(imagen_recorte, cv2.COLOR_BGRA2RGB)

        # pix2tex (LatexOCR) espera una PIL.Image, no un numpy array
        pil_image = Image.fromarray(imagen_recorte)
        latex = model(pil_image)

        # pix2tex no proporciona confidence scores nativas
        # Usamos heurística: largura vs complejidad
        if latex:
            # Confianza inversamente correlada con longitud (fórmulas cortas = más confiables)
            confianza = max(0.7, min(0.95, 0.95 - len(latex) * 0.001))
        else:
            confianza = 0.0

        return str(latex).strip(), float(confianza)

    except Exception as e:
        print(f"[pix2tex] Error: {e}")
        return "", 0.0
