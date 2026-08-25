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

from collections.abc import Callable
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

    def __init__(self, al_progresar: Callable[..., None] | None = None) -> None:
        """`al_progresar(capa, estado, **datos)` se llama al entrar y salir de cada capa.

        Es lo que permite mostrar una barra por capas mientras el documento se
        procesa: el pipeline tarda minutos y hasta ahora no reportaba nada hasta
        terminar. Es opcional, y si el callback falla no se corta el
        procesamiento: informar el progreso nunca puede costar el trabajo hecho.
        """
        self.ultima_correccion: DocumentPostCorrection | None = None
        self._al_progresar = al_progresar

    def _avisar(self, capa: int, estado: str, **datos) -> None:
        if self._al_progresar is None:
            return
        try:
            self._al_progresar(capa, estado, **datos)
        except Exception:
            pass

    def ejecutar(self, ruta_pdf: str) -> tuple[Documento, list[Bloque]]:
        titulo = Path(ruta_pdf).name

        # Capa 1: Triage
        self._avisar(1, "en_curso")
        resultados_triage, zonas = procesar_triage(ruta_pdf)

        documento = Documento(
            titulo=titulo,
            origen=Origen.NATIVO_DIGITAL,
            idioma_original="es",
            total_paginas=len(resultados_triage),
            version_pipeline="0.1.0",
            zonas_dpi=zonas,
        )

        origenes = {t.origen for t in resultados_triage}
        self._avisar(
            1,
            "completada",
            total_paginas=len(resultados_triage),
            detalle=(
                f"{len(resultados_triage)} páginas · "
                f"{'/'.join(sorted(origenes)) or 'sin clasificar'} · "
                f"{len(zonas)} zonas de DPI"
            ),
        )

        # Capa 2: Segmentación
        self._avisar(2, "en_curso")
        bloques = segmentar_documento(documento, ruta_pdf, resultados_triage)

        tipos = {b.tipo.value if hasattr(b.tipo, "value") else str(b.tipo) for b in bloques}
        self._avisar(
            2,
            "completada",
            total_bloques=len(bloques),
            detalle=f"{len(bloques)} bloques · {len(tipos)} tipos",
        )

        # Capa 3: OCR especializado (solo bloques que no traen texto nativo)
        dpi_por_pagina = {t.pagina: t.dpi_objetivo for t in resultados_triage}
        imagenes_pagina = self._ejecutar_ocr(ruta_pdf, bloques, dpi_por_pagina)

        # Capa 4: Corrección determinista
        self._avisar(4, "en_curso")
        resultado_correccion = corregir_documento(documento, bloques)
        self.ultima_correccion = resultado_correccion
        self._avisar(
            4,
            "completada",
            detalle=(
                f"{len(resultado_correccion.bloques_corregidos)} bloques corregidos · "
                f"{len(resultado_correccion.inconsistencias_detectadas)} inconsistencias"
            ),
        )

        # Capa 5: Escalación LLM (best-effort: sin credenciales de Anthropic
        # configuradas, las colas simplemente no producen resultados).
        # Las imágenes de página son necesarias para la cola de micro-segmentos:
        # sin ellas no hay recorte que mandarle al modelo con visión.
        self._avisar(5, "en_curso")
        try:
            procesar_escalaciones(
                documento, bloques, resultado_correccion, imagenes_pagina
            )
            self._avisar(5, "completada")
        except Exception as e:
            # La escalación es best-effort, pero el estado tiene que decir que se
            # omitió: mostrarla como completada haría creer que el modelo revisó
            # bloques que en realidad nunca vio.
            self._avisar(5, "omitida", detalle=str(e)[:200])

        return documento, bloques

    def _ejecutar_ocr(
        self,
        ruta_pdf: str,
        bloques: list[Bloque],
        dpi_por_pagina: dict[int, int],
    ) -> dict[int, np.ndarray]:
        """Ejecuta Capa 3 y devuelve las páginas renderizadas, que Capa 5 reutiliza."""
        doc = fitz.open(ruta_pdf)
        imagenes_pagina: dict[int, np.ndarray] = {}

        pendientes = [b for b in bloques if b.origen_contenido != OrigenContenido.TEXTO_NATIVO]
        self._avisar(3, "en_curso", hechos=0, total=len(pendientes))

        # Avisar bloque por bloque satura la base en documentos de 30 000
        # bloques; cada 1 % la barra igual se mueve con fluidez.
        paso = max(1, len(pendientes) // 100)
        engines: dict[str, int] = {}
        hechos = 0

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

                for micro in resultado_ocr.micro_segmentos:
                    nombre = getattr(micro.engine_usado, "value", str(micro.engine_usado))
                    engines[nombre] = engines.get(nombre, 0) + 1

                hechos += 1
                if hechos % paso == 0:
                    self._avisar(
                        3, "en_curso", hechos=hechos, total=len(pendientes), engines=dict(engines)
                    )
        finally:
            doc.close()

        self._avisar(
            3,
            "completada",
            hechos=hechos,
            total=len(pendientes),
            engines=dict(engines),
            detalle=(
                ", ".join(f"{k}: {v}" for k, v in sorted(engines.items()))
                or "sin bloques que requirieran OCR"
            ),
        )
        return imagenes_pagina

    @staticmethod
    def _renderizar_pagina(doc: fitz.Document, pagina_num: int, dpi: int) -> np.ndarray:
        page = doc[pagina_num]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
