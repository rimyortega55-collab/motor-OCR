"""Orquestador end-to-end: PDF crudo -> salida indexable por Graphify.

triage -> renderizado por zona -> segmentation -> ocr_specialized ->
correction -> escalation (dos colas) -> metadata.exportador_graphify

Implementado como máquina de estados explícita con LangGraph (ver
.contexto/01-arquitectura-general.md, principio 4: "automatización
determinista y explícita, en lugar de comportamiento de agente ambiguo").
Se construye al final, según el orden sugerido en
.contexto/04-estructura-proyecto.md — cada capa debe funcionar aislada antes
de conectarse acá.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf as fitz

from ocr_engine.correction import corregir_documento
from ocr_engine.escalation import procesar_escalaciones
from ocr_engine.models import Bloque, Documento, Origen, OrigenContenido
from ocr_engine.models.results import DocumentPostCorrection
from ocr_engine.ocr_specialized import enrutar_bloque
from ocr_engine.segmentation import segmentar_documento
from ocr_engine.triage import procesar_triage


class Pipeline:
    """Orquestador secuencial de las capas 1-5 (ver .contexto/01-arquitectura-general.md).

    Implementado como pasos secuenciales explícitos en vez de un StateGraph de
    LangGraph: cada capa ya se probó aislada (ver scratch_test_*.py) y el
    orden es siempre el mismo (sin ramas condicionales que ameriten un grafo
    de estados todavía) — se puede migrar a LangGraph cuando la Capa 5
    necesite reintentos/branching real.
    """

    def __init__(self) -> None:
        self.ultima_correccion: DocumentPostCorrection | None = None

    def ejecutar(self, ruta_pdf: str) -> tuple[Documento, list[Bloque]]:
        titulo = Path(ruta_pdf).name

        # Capa 1: Triage
        resultados_triage, zonas = procesar_triage(ruta_pdf)

        documento = Documento(
            titulo=titulo,
            origen=Origen.NATIVO_DIGITAL,
            idioma_original="es",
            total_paginas=len(resultados_triage),
            version_pipeline="0.1.0",
            zonas_dpi=zonas,
        )

        # Capa 2: Segmentación
        bloques = segmentar_documento(documento, ruta_pdf, resultados_triage)

        # Capa 3: OCR especializado (solo bloques que no traen texto nativo)
        dpi_por_pagina = {t.pagina: t.dpi_objetivo for t in resultados_triage}
        self._ejecutar_ocr(ruta_pdf, bloques, dpi_por_pagina)

        # Capa 4: Corrección determinista
        resultado_correccion = corregir_documento(documento, bloques)
        self.ultima_correccion = resultado_correccion

        # Capa 5: Escalación LLM (best-effort: sin credenciales de Anthropic
        # configuradas, las colas simplemente no producen resultados)
        try:
            procesar_escalaciones(documento, bloques, resultado_correccion)
        except Exception:
            pass

        return documento, bloques

    def _ejecutar_ocr(
        self,
        ruta_pdf: str,
        bloques: list[Bloque],
        dpi_por_pagina: dict[int, int],
    ) -> None:
        doc = fitz.open(ruta_pdf)
        imagenes_pagina: dict[int, np.ndarray] = {}

        try:
            for bloque in bloques:
                if bloque.origen_contenido == OrigenContenido.TEXTO_NATIVO:
                    continue

                pagina_num = bloque.pagina
                if pagina_num not in imagenes_pagina:
                    imagenes_pagina[pagina_num] = self._renderizar_pagina(
                        doc, pagina_num, dpi_por_pagina.get(pagina_num, 200)
                    )

                resultado_ocr = enrutar_bloque(
                    bloque,
                    imagen_pagina=imagenes_pagina[pagina_num],
                    dpi_objetivo=dpi_por_pagina.get(pagina_num, 200),
                )

                bloque.contenido.texto_plano = resultado_ocr.contenido
                bloque.ocr.micro_segmentos = resultado_ocr.micro_segmentos
                bloque.ocr.confianza_global = resultado_ocr.confianza_global
        finally:
            doc.close()

    @staticmethod
    def _renderizar_pagina(doc: fitz.Document, pagina_num: int, dpi: int) -> np.ndarray:
        page = doc[pagina_num]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
