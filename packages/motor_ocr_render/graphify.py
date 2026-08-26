"""Salida indexable por Graphify: los bloques son nodos y sus relaciones, edges.

Hay dos formas segun de donde salgan los datos. `renderizar` es la del producto:
serializa lo que quedo guardado, con la correccion humana ya aplicada. La otra,
`exportar_modelos`, vuelca los modelos del motor tal cual, con toda su metadata,
para quien consuma el pipeline como biblioteca sin pasar por la base.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from .contrato import BloqueRenderizable, DocumentoRenderizable, ordenar


def renderizar(
    documento: DocumentoRenderizable, bloques: Sequence[BloqueRenderizable]
) -> str:
    ordenados = ordenar(bloques)
    salida = {
        "documento_id": documento.id,
        "titulo": documento.titulo,
        "total_paginas": documento.total_paginas,
        "total_bloques": len(ordenados),
        "bloques": [
            {
                "id": b.id,
                "pagina": b.pagina,
                "orden_lectura": b.orden_lectura,
                "tipo": b.tipo,
                "origen_contenido": b.origen_contenido,
                "bbox": b.bbox,
                "confianza_global": b.confianza_global,
                "contenido": b.texto,
                # Se declara si lo reviso una persona: quien indexe esto necesita
                # poder distinguir lo verificado de lo que solo paso por el motor.
                "revisado_por_humano": b.revisado_por_humano,
            }
            for b in ordenados
        ],
    }
    return json.dumps(salida, ensure_ascii=False, indent=2)


def exportar_modelos(documento: Any, bloques: Sequence[Any]) -> dict:
    """Vuelca los modelos del motor completos, sin pasar por la base.

    Los bloques son los nodos; `Bloque.relaciones` (entrantes y salientes) quedan
    embebidas en cada nodo como edges.
    """
    return {
        "documento": documento.model_dump(mode="json"),
        "bloques": [bloque.model_dump(mode="json") for bloque in bloques],
    }
