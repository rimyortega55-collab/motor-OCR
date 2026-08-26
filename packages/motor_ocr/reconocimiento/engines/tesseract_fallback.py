"""Wrapper de Tesseract — no es el motor principal.

Se usa para comparar resultados con EasyOCR en segmentos dudosos y aportar
la señal de "consenso entre engines" al cálculo de confianza (confianza.py),
antes de escalar a LLM — barato comparado con una llamada a LLM.
"""

from __future__ import annotations


def ocr_texto_fallback(imagen_recorte) -> tuple[str, float]:
    """Devuelve (texto_reconocido, confianza_engine)."""
    raise NotImplementedError("Pendiente: integrar pytesseract")
