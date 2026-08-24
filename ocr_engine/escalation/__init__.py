"""Orquestador de Capa 5 (Escalación LLM con batcheo)."""

from __future__ import annotations

from ocr_engine.models import (
    Documento, Bloque, Inconsistencia, MicroSegmento
)
from ocr_engine.models.results import DocumentPostCorrection

from .cola_micro_segmentos import encolar_micro_segmento, resolver_lote_pagina
from .cola_inconsistencias import resolver_inconsistencias
from .costo_tracking import registrar_costo, obtener_estadisticas
from .cliente_llm import llamar_llm_micro_segmento, llamar_llm_inconsistencia


def procesar_escalaciones(
    documento: Documento,
    bloques: list[Bloque],
    resultado_correccion: DocumentPostCorrection,
    imagen_pagina_por_num: dict = None
) -> dict:
    """Procesa todas las escalaciones de un documento (Capa 5).

    Maneja dos colas:
    1. Cola 1: Micro-segmentos de baja confianza (OCR)
    2. Cola 2: Inconsistencias documentales (Capa 4)

    Args:
        documento: Documento metadatos
        bloques: Bloques del documento (con contenido de Capa 3)
        resultado_correccion: Resultado de Capa 4 (inconsistencias)
        imagen_pagina_por_num: Mapeo {num_pagina: imagen_numpy} para contexto visual

    Returns:
        {
            "escalaciones_micro_segmentos": [EscalationResult, ...],
            "escalaciones_inconsistencias": [EscalationResult, ...],
            "estadisticas_costo": {...},
            "bloques_requieren_revision_humana": [UUID, ...]
        }
    """

    imagen_pagina_por_num = imagen_pagina_por_num or {}
    escalaciones_micro = []
    escalaciones_inconsistencias = []
    bloques_revision_humana = []

    # ========== Cola 1: Micro-segmentos de baja confianza ==========
    # (Serían encolados desde Capa 3 si la confianza fuera < 0.6)
    # Por ahora: los test PDFs no tienen baja confianza, así que la cola estaría vacía
    # En producción, esto se activaría durante Capa 3 OCR

    # ========== Cola 2: Inconsistencias documentales ==========
    if resultado_correccion.inconsistencias_detectadas:
        escalaciones_inconsistencias = resolver_inconsistencias(
            documento=documento,
            bloques=bloques,
            inconsistencias=resultado_correccion.inconsistencias_detectadas
        )

        # Registrar costos
        # resolver_inconsistencias devuelve un EscalationResult por inconsistencia,
        # en el mismo orden que la lista de entrada, así que se pueden aparear.
        vistos: set[str] = set()

        for escalacion, inconsistencia in zip(
            escalaciones_inconsistencias,
            resultado_correccion.inconsistencias_detectadas
        ):
            registrar_costo(
                documento_id=documento.documento_id,
                bloque_id=None,  # Inconsistencias no son de un bloque específico
                costo=escalacion.costo,
                razon_escalacion=escalacion.razon_escalacion,
                tipo_cola="inconsistencia_documental"
            )

            # Marcar para revisión humana si confianza LLM es baja.
            # Se acota a la página donde se ubica la inconsistencia: mandar el
            # documento entero a la cola la vuelve inservible para el revisor
            # (un solo problema arrastraba miles de bloques).
            if escalacion.requiere_revision_humana:
                for bloque in bloques:
                    if bloque.pagina != inconsistencia.ubicacion_pagina:
                        continue
                    if str(bloque.id) in vistos:
                        continue
                    vistos.add(str(bloque.id))
                    bloques_revision_humana.append(str(bloque.id))

    # ========== Estadísticas finales ==========
    estadisticas = obtener_estadisticas()

    return {
        "escalaciones_micro_segmentos": escalaciones_micro,
        "escalaciones_inconsistencias": escalaciones_inconsistencias,
        "estadisticas_costo": estadisticas,
        "bloques_requieren_revision_humana": bloques_revision_humana
    }


def escalar_lote_micro_segmentos(
    documento_id,
    pagina: int,
    imagen_pagina=None
) -> list:
    """Procesa lote de micro-segmentos de una página.

    Args:
        documento_id: ID del documento
        pagina: Número de página
        imagen_pagina: Imagen de la página completa

    Returns:
        Lista de EscalationResult
    """

    resultados = resolver_lote_pagina(pagina, imagen_pagina)

    # Registrar costos
    for resultado in resultados:
        registrar_costo(
            documento_id=documento_id,
            bloque_id=getattr(resultado, 'bloque_id', None),
            costo=resultado.costo,
            razon_escalacion=resultado.razon_escalacion,
            tipo_cola="micro_segmento"
        )

    return resultados


__all__ = [
    "procesar_escalaciones",
    "escalar_lote_micro_segmentos",
    "obtener_estadisticas",
    "registrar_costo",
]
