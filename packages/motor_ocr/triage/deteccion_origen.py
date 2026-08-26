"""Nativo-digital vs escaneado, vía PyMuPDF (fitz).

Un PDF es nativo-digital si tiene capa de texto embebida inspeccionable. Sin
esa señal, la página se trata como escaneada y requiere el pase visual de
`perfil_visual.py`.
"""

from __future__ import annotations

from motor_ocr.modelos import Origen


def detectar_origen(ruta_pdf: str, pagina: int) -> Origen:
    import fitz

    doc = fitz.open(ruta_pdf)
    if pagina < 0 or pagina >= len(doc):
        return Origen.ESCANEADO

    page = doc[pagina]
    text = page.get_text()

    doc.close()

    # If extractable text exists, it's native-digital
    if text.strip():
        return Origen.NATIVO_DIGITAL
    return Origen.ESCANEADO
