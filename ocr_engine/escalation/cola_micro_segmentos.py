"""Cola 1 — micro-segmentos de baja confianza (origen: Capa 3).

Requiere modelo con visión: el error suele venir de algo que el engine
determinista no pudo interpretar visualmente. Unidad de batching: por
página — todos los micro-segmentos dudosos de una misma página en una sola
llamada. Se envía: recorte de imagen del segmento (no la página completa) +
1-2 líneas de contexto textual antes/después + el resultado del engine
determinista (para que el LLM corrija, no transcriba desde cero).
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from ocr_engine.models import EscalationResult, MicroSegmento
from .cliente_llm import llamar_llm_micro_segmento

# Cola global de micro-segmentos agrupada por página
_cola_por_pagina = defaultdict(list)

class ElementoCola:
    """Elemento en la cola de micro-segmentos."""

    def __init__(
        self,
        bloque_id: UUID,
        micro_segmento_idx: int,
        pagina: int,
        micro_segmento: MicroSegmento,
        imagen_recorte,
        contexto_texto: str
    ):
        self.bloque_id = bloque_id
        self.micro_segmento_idx = micro_segmento_idx
        self.pagina = pagina
        self.micro_segmento = micro_segmento
        self.imagen_recorte = imagen_recorte
        self.contexto_texto = contexto_texto

def encolar_micro_segmento(
    bloque_id: UUID,
    micro_segmento_idx: int,
    pagina: int,
    micro_segmento: MicroSegmento,
    imagen_recorte,
    contexto_texto: str = ""
) -> None:
    """Encola micro-segmento para procesamiento LLM.

    Args:
        bloque_id: ID del bloque padre
        micro_segmento_idx: Índice del micro-segmento dentro del bloque
        pagina: Número de página
        micro_segmento: Objeto MicroSegmento
        imagen_recorte: Imagen del recorte (numpy array)
        contexto_texto: Texto de contexto antes/después
    """

    elemento = ElementoCola(
        bloque_id=bloque_id,
        micro_segmento_idx=micro_segmento_idx,
        pagina=pagina,
        micro_segmento=micro_segmento,
        imagen_recorte=imagen_recorte,
        contexto_texto=contexto_texto
    )

    _cola_por_pagina[pagina].append(elemento)


def resolver_lote_pagina(pagina: int, imagen_pagina=None) -> list[EscalationResult]:
    """Resuelve todos los micro-segmentos de una página en una sola llamada.

    Args:
        pagina: Número de página
        imagen_pagina: Imagen de la página completa (contexto visual)

    Returns:
        Lista de EscalationResult, uno por micro-segmento
    """

    if pagina not in _cola_por_pagina or not _cola_por_pagina[pagina]:
        return []

    elementos = _cola_por_pagina[pagina]
    resultados = []

    for elemento in elementos:
        # Llamar LLM para este micro-segmento
        resultado = llamar_llm_micro_segmento(
            imagen_recorte=elemento.imagen_recorte,
            contexto_texto=elemento.contexto_texto,
            resultado_engine=elemento.micro_segmento.contenido,
            tipo_segmento=elemento.micro_segmento.tipo
        )

        # Agregar metadatos de trazabilidad (campos declarados en EscalationResult;
        # asignarlos sobre un modelo que no los define lanza ValueError en pydantic)
        resultado.bloque_id = elemento.bloque_id
        resultado.micro_segmento_idx = elemento.micro_segmento_idx

        resultados.append(resultado)

    # Limpiar cola
    del _cola_por_pagina[pagina]

    return resultados


def limpiar_cola() -> None:
    """Limpia toda la cola (para tests o reinicio)."""
    _cola_por_pagina.clear()


def obtener_estadisticas_cola() -> dict:
    """Obtiene estadísticas de la cola actual."""
    total_elementos = sum(len(v) for v in _cola_por_pagina.values())

    return {
        "total_paginas": len(_cola_por_pagina),
        "total_micro_segmentos": total_elementos,
        "paginas": list(_cola_por_pagina.keys())
    }
