"""Última pieza del pipeline: ensambla la salida final según
.contexto/05-esquema-metadata-bloque-ocr.md, lista para ser indexada por
Graphify (nodos = Bloque, edges = Bloque.relaciones).
"""

from __future__ import annotations

from ocr_engine.models import Bloque, Documento


def exportar_documento(documento: Documento, bloques: list[Bloque]) -> dict:
    """Serializa documento + bloques a un dict JSON-listo para Graphify.

    Los bloques son los nodos; `Bloque.relaciones` (entrantes/salientes)
    quedan embebidas en cada nodo como edges, tal como describe
    .contexto/05-esquema-metadata-bloque-ocr.md.
    """
    return {
        "documento": documento.model_dump(mode="json"),
        "bloques": [bloque.model_dump(mode="json") for bloque in bloques],
    }
