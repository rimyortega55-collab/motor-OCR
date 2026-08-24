"""Detección de fuentes matemáticas embebidas (páginas nativo-digitales).

Fuentes tipo CMMI, CMSY, CMEX, MSAM, MSBM, Latin Modern Math u otras fuentes
OpenType matemáticas son señal confiable y gratuita de presencia de notación
matemática — sin necesidad de OCR ni LLM. Esta misma señal se reutiliza en
Capa 3 para sub-segmentar fórmulas inline dentro de bloques de texto nativo.
"""

from __future__ import annotations

FUENTES_MATEMATICAS_CONOCIDAS = (
    "CMMI",
    "CMSY",
    "CMEX",
    "MSAM",
    "MSBM",
    "Latin Modern Math",
)


def detectar_fuentes_matematicas(ruta_pdf: str, pagina: int) -> list[str]:
    import fitz

    doc = fitz.open(ruta_pdf)
    if pagina < 0 or pagina >= len(doc):
        return []

    page = doc[pagina]
    text_dict = page.get_text("dict")

    fuentes_encontradas = set()
    for block in text_dict.get("blocks", []):
        if block.get("type") == 0:  # text block
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font_name = span.get("font", "")
                    if font_name:
                        for math_font in FUENTES_MATEMATICAS_CONOCIDAS:
                            if math_font.upper() in font_name.upper():
                                fuentes_encontradas.add(font_name)

    doc.close()
    return list(fuentes_encontradas)
