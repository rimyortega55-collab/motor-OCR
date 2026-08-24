from .nativo_digital import segmentar_nativo_digital
from .escaneado import segmentar_escaneado
from .orden_lectura import resolver_orden_lectura

from ocr_engine.models import Bloque, Documento, Origen, TriageResult
import pymupdf as fitz
import cv2
import numpy as np


def segmentar_documento(
    documento: Documento,
    ruta_pdf: str,
    resultados_triage: list[TriageResult],
) -> list[Bloque]:
    """
    Segmenta un documento completo (Capa 2).

    Procesa cada página según su origen detectado en Triage:
    - Nativo-digital: agrupación por fuente/posición/espaciado
    - Escaneado: detección de regiones visuales
    Resuelve orden de lectura incluyendo multi-columna.
    """
    doc = fitz.open(ruta_pdf)
    bloques_documento = []

    for triage_result in resultados_triage:
        pagina_num = triage_result.pagina

        # Get page
        page = doc[pagina_num]

        # Segment by origin
        if triage_result.origen == Origen.NATIVO_DIGITAL.value:
            bloques_pagina = segmentar_nativo_digital(
                documento, ruta_pdf, pagina_num
            )
        else:
            # Render page to image for scanned segmentation
            zoom = (triage_result.dpi_objetivo / 72.0)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )

            # Convert BGR to RGB if needed
            if img_data.shape[2] == 3:
                imagen_pagina = cv2.cvtColor(img_data, cv2.COLOR_BGR2RGB)
            else:
                imagen_pagina = img_data[:, :, 0]

            bloques_pagina = segmentar_escaneado(
                documento, imagen_pagina, pagina_num
            )

        # Resolve reading order for this page's blocks
        bloques_pagina = resolver_orden_lectura(bloques_pagina)

        bloques_documento.extend(bloques_pagina)

    doc.close()
    return bloques_documento


__all__ = [
    "segmentar_documento",
    "segmentar_nativo_digital",
    "segmentar_escaneado",
    "resolver_orden_lectura",
]
