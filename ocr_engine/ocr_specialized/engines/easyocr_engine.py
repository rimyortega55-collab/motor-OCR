"""Wrapper de EasyOCR — OCR de texto plano general.

Motor principal para micro-segmentos de tipo "texto" y para los tipos de
bloque encabezado/caption/lista/codigo. Elegido sobre PaddleOCR porque los
wheels de PaddlePaddle requieren instrucciones AVX que este hardware
(Intel Celeron N5100, sin AVX) no soporta — ver
.contexto/02-herramientas-stack.md. EasyOCR es pytorch puro y corre bien en
este CPU.
"""

from __future__ import annotations

import cv2
import numpy as np

_reader = None

def _get_reader():
    """Lazy loader para easyocr.Reader (costoso de inicializar)."""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['es', 'en', 'la'], gpu=False)
    return _reader

def ocr_texto(imagen_recorte) -> tuple[str, float]:
    """Devuelve (texto_reconocido, confianza_engine).

    Args:
        imagen_recorte: numpy array (H, W) o (H, W, 3)

    Returns:
        (texto_reconocido, confianza_media)
    """
    if imagen_recorte is None or imagen_recorte.size == 0:
        return "", 0.0

    try:
        reader = _get_reader()

        # Ensure image is uint8
        if imagen_recorte.dtype != np.uint8:
            if imagen_recorte.max() <= 1.0:
                imagen_recorte = (imagen_recorte * 255).astype(np.uint8)
            else:
                imagen_recorte = imagen_recorte.astype(np.uint8)

        # Convert grayscale to BGR if needed
        if len(imagen_recorte.shape) == 2:
            imagen_recorte = cv2.cvtColor(imagen_recorte, cv2.COLOR_GRAY2BGR)

        # OCR
        resultados = reader.readtext(imagen_recorte, detail=1)

        if not resultados:
            return "", 0.0

        # Recompone texto y calcula confianza media
        textos = [linea[1] for linea in resultados]
        confianzas = [float(linea[2]) for linea in resultados]

        texto_final = " ".join(textos)
        confianza_media = np.mean(confianzas) if confianzas else 0.0

        return texto_final, float(confianza_media)

    except Exception as e:
        print(f"[EasyOCR] Error: {e}")
        return "", 0.0
