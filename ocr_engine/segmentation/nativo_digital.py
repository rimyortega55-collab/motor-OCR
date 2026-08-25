"""Segmentación de páginas nativo-digitales por estructura del PDF.

Los bloques se derivan directamente agrupando por fuente + posición +
espaciado vertical — más preciso y más barato que segmentación visual, ya
que no hay pérdida de información al no pasar por una imagen rasterizada.
"""

from __future__ import annotations

from ocr_engine.models import Bloque, Documento


from uuid import uuid4
from datetime import datetime

from ocr_engine.models import (
    Bloque,
    Documento,
    Layout,
    OrigenContenido,
    Contenido,
    Provenance,
)
from .bbox import normalizar_bbox
from .taxonomia import clasificar_bloque

import pymupdf as fitz


def segmentar_nativo_digital(documento: Documento, ruta_pdf: str, pagina: int) -> list[Bloque]:
    """Segmenta página nativo-digital agrupando por fuente+posición+espaciado."""
    doc = fitz.open(ruta_pdf)
    if pagina < 0 or pagina >= len(doc):
        return []

    page = doc[pagina]
    text_dict = page.get_text("dict")
    # PyMuPDF da los bbox en puntos PDF (72 dpi). Se guardan normalizados a la
    # caja de la página para que el bbox de un bloque signifique lo mismo venga
    # de acá o del camino escaneado, donde sale en píxeles del render.
    caja = (page.rect.width or 1.0, page.rect.height or 1.0)
    doc.close()

    bloques = []
    orden_lectura = 0

    # Group consecutive spans by similar font and position
    current_block_spans = []
    current_font = None
    current_y = None

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # only text blocks
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue

                font_name = span.get("font", "")
                bbox = span.get("bbox", (0, 0, 0, 0))
                y_pos = (bbox[1] + bbox[3]) / 2  # center Y

                # Check if we should start a new block
                if (
                    current_font is None
                    or font_name != current_font
                    or (current_y is not None and abs(y_pos - current_y) > 15)
                ):
                    # Save previous block if exists
                    if current_block_spans:
                        bloque = _crear_bloque(
                            caja,
                            documento,
                            pagina,
                            current_block_spans,
                            orden_lectura,
                        )
                        bloques.append(bloque)
                        orden_lectura += 1
                        current_block_spans = []

                    current_font = font_name
                    current_y = y_pos

                current_block_spans.append(
                    {
                        "text": text,
                        "bbox": bbox,
                        "font": font_name,
                        "y": y_pos,
                    }
                )

    # Save final block
    if current_block_spans:
        bloque = _crear_bloque(
            caja,
            documento,
            pagina,
            current_block_spans,
            orden_lectura,
        )
        bloques.append(bloque)

    return bloques


def _crear_bloque(
    caja: tuple[float, float],
    documento: Documento,
    pagina: int,
    spans: list,
    orden_lectura: int,
) -> Bloque:
    """Crea un Bloque a partir de spans agrupados."""
    # Merge text
    texto = " ".join([s["text"] for s in spans])

    # Calculate bounding box
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)

    # Check if block starts with bold
    es_negrita = spans[0]["font"] and "bold" in spans[0]["font"].lower()

    # Classify block type
    tipo_bloque = clasificar_bloque(texto, es_negrita)

    bloque = Bloque(
        id=uuid4(),
        documento_id=documento.documento_id,
        pagina=pagina,
        tipo=tipo_bloque,
        layout=Layout(
            bbox=normalizar_bbox((x0, y0, x1, y1), caja),
            orden_lectura=orden_lectura,
            confianza_layout=0.95,  # high confidence for native-digital
        ),
        origen_contenido=OrigenContenido.TEXTO_NATIVO,
        contenido=Contenido(texto_plano=texto),
        provenance=Provenance(creado_por_capa="segmentation_nativo_digital"),
    )

    return bloque
