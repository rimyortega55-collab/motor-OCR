"""Orquestador de Capa 5 (Escalación LLM con batcheo)."""

from __future__ import annotations

from ocr_engine.config.settings import settings
from ocr_engine.models import (
    ColaOrigen, Documento, Bloque, Inconsistencia, MicroSegmento
)
from ocr_engine.models.results import DocumentPostCorrection

from ocr_engine.segmentation.bbox import desnormalizar_bbox

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
    # Los bloques llegan de Capa 3 con sus micro-segmentos y confianzas en
    # `bloque.ocr`. Sin imagen de página no se puede escalar: el LLM necesita ver
    # el recorte, que es justamente lo que el engine determinista no supo leer.
    if imagen_pagina_por_num:
        paginas_encoladas = set()

        for bloque in bloques:
            micro_segmentos = getattr(bloque.ocr, "micro_segmentos", None) or []
            if not micro_segmentos:
                continue

            imagen_pagina = imagen_pagina_por_num.get(bloque.pagina)
            if imagen_pagina is None:
                continue

            for idx, micro_segmento in enumerate(micro_segmentos):
                if micro_segmento.confianza_estructural >= settings.umbral_escalacion_micro_segmento:
                    continue

                recorte = _recortar_bloque(bloque, imagen_pagina)
                if recorte is None:
                    continue

                encolar_micro_segmento(
                    bloque_id=bloque.id,
                    micro_segmento_idx=idx,
                    pagina=bloque.pagina,
                    micro_segmento=micro_segmento,
                    imagen_recorte=recorte,
                    contexto_texto=_contexto_de_bloque(bloque),
                )
                paginas_encoladas.add(bloque.pagina)

        por_id = {str(b.id): b for b in bloques}

        for pagina in sorted(paginas_encoladas):
            resultados_pagina = resolver_lote_pagina(
                pagina, imagen_pagina_por_num.get(pagina)
            )
            escalaciones_micro.extend(resultados_pagina)

            for escalacion in resultados_pagina:
                # Sin esto el resultado del modelo se perdía apenas terminaba el
                # pipeline: quedaba el costo registrado, pero no la corrección ni
                # la razón, que es lo que el revisor necesita ver.
                _aplicar_al_bloque(por_id.get(str(escalacion.bloque_id)), escalacion)

                registrar_costo(
                    documento_id=documento.documento_id,
                    bloque_id=escalacion.bloque_id,
                    costo=escalacion.costo,
                    razon_escalacion=escalacion.razon_escalacion,
                    tipo_cola="micro_segmento",
                )

                if escalacion.requiere_revision_humana and escalacion.bloque_id:
                    bloque_id = str(escalacion.bloque_id)
                    if bloque_id not in bloques_revision_humana:
                        bloques_revision_humana.append(bloque_id)

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
    # Acotadas a este documento: sin el filtro devolvía el acumulado del proceso
    # entero, mezclando el costo de documentos de otros usuarios.
    estadisticas = obtener_estadisticas(documento.documento_id)

    return {
        "escalaciones_micro_segmentos": escalaciones_micro,
        "escalaciones_inconsistencias": escalaciones_inconsistencias,
        "estadisticas_costo": estadisticas,
        "bloques_requieren_revision_humana": bloques_revision_humana
    }


def _aplicar_al_bloque(bloque, escalacion) -> None:
    """Vuelca el resultado de la Capa 5 sobre el bloque que lo originó."""

    if bloque is None:
        return

    bloque.escalacion.requirio_escalacion = True
    bloque.escalacion.cola_origen = ColaOrigen.MICRO_SEGMENTO
    bloque.escalacion.contenido_llm = escalacion.contenido_final
    bloque.escalacion.confianza_llm = escalacion.confianza_llm
    bloque.escalacion.requiere_revision_humana = escalacion.requiere_revision_humana
    bloque.escalacion.razon_escalacion = escalacion.razon_escalacion
    bloque.escalacion.costo = escalacion.costo


def _recortar_bloque(bloque: Bloque, imagen_pagina):
    """Recorta de la página la región del bloque, o None si el bbox no es válido."""

    if imagen_pagina is None:
        return None

    # El bbox está normalizado, así que este recorte ya no depende de si el
    # bloque vino del camino nativo (puntos) o del escaneado (píxeles): antes,
    # un bloque nativo se recortaba a ~36 % de su tamaño real sobre una página
    # renderizada a 200 dpi.
    alto, ancho = imagen_pagina.shape[:2]
    x0, y0, x1, y1 = desnormalizar_bbox(bloque.layout.bbox, (ancho, alto))

    if x1 <= x0 or y1 <= y0:
        return None

    recorte = imagen_pagina[y0:y1, x0:x1]
    return recorte if recorte.size else None


def _contexto_de_bloque(bloque: Bloque, limite: int = 300) -> str:
    """Texto del bloque que acompaña al recorte, para que el LLM corrija con contexto."""

    texto = getattr(bloque.contenido, "texto_plano", "") or ""
    return texto[:limite]


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
