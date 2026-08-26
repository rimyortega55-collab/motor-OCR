"""Tipos que los renderizadores consumen, y adaptadores hacia ellos.

Este paquete no importa el motor ni la base de datos: recibe estructuras planas
y devuelve texto. Antes, el exportador de LaTeX recibia filas `BloqueAlmacenado`
mas una funcion `_contenido` suelta, y el de Markdown vivia dentro de un modulo
de rutas de FastAPI. Eso ataba el trabajo de formato a la capa web y obligaba a
levantar media aplicacion para probar un renderizador.

Los adaptadores usan acceso por atributo y no importan las clases de origen, asi
que sirven tanto para el `Bloque` en memoria del motor (pydantic, anidado) como
para la fila de la base (plana), sin que este paquete dependa de ninguno.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class DocumentoRenderizable:
    titulo: str
    id: str | None = None
    total_paginas: int | None = None


@dataclass(frozen=True)
class BloqueRenderizable:
    """Un bloque ya resuelto, listo para escribir.

    `texto` viene decidido: no queda regla de prioridad que aplicar aguas abajo.
    """

    pagina: int
    orden_lectura: int
    tipo: str
    texto: str

    id: str | None = None
    bbox: Any = None
    origen_contenido: str | None = None
    confianza_global: float | None = None
    revisado_por_humano: bool = False
    micro_segmentos: tuple = field(default_factory=tuple)


def contenido_efectivo(
    contenido_final: str | None, latex: str | None, texto_plano: str | None
) -> str:
    """Que texto vale para exportar, en orden de prioridad.

    `contenido_final` primero: si la revision humana corrigio un bloque y la
    exportacion siguiera entregando el texto del motor, revisar no serviria de
    nada. Despues el LaTeX, mas fiel que el texto plano para formulas.

    La regla vive aca, una sola vez, porque es la misma para todos los formatos.
    """
    return contenido_final or latex or texto_plano or ""


def desde_almacenado(fila: Any) -> BloqueRenderizable:
    """Adapta una fila `BloqueAlmacenado` de la base."""
    return BloqueRenderizable(
        pagina=fila.pagina,
        orden_lectura=fila.orden_lectura,
        tipo=fila.tipo,
        texto=contenido_efectivo(fila.contenido_final, fila.latex, fila.texto_plano),
        id=getattr(fila, "id", None),
        bbox=getattr(fila, "bbox", None),
        origen_contenido=getattr(fila, "origen_contenido", None),
        confianza_global=getattr(fila, "confianza_global", None),
        # Quien indexe esto necesita distinguir lo verificado por una persona de
        # lo que solo paso por el motor.
        revisado_por_humano=getattr(fila, "estado_revision", None) == "resuelto",
    )


def desde_bloque(bloque: Any) -> BloqueRenderizable:
    """Adapta el `Bloque` en memoria del motor, sin importarlo."""
    contenido = bloque.contenido
    tipo = getattr(bloque.tipo, "value", str(bloque.tipo))
    origen = getattr(bloque.origen_contenido, "value", str(bloque.origen_contenido))

    return BloqueRenderizable(
        pagina=bloque.pagina,
        orden_lectura=bloque.layout.orden_lectura,
        tipo=tipo,
        texto=contenido_efectivo(None, contenido.latex, contenido.texto_plano),
        id=str(bloque.id),
        bbox=tuple(bloque.layout.bbox),
        origen_contenido=origen,
        confianza_global=bloque.ocr.confianza_global,
        micro_segmentos=tuple(bloque.ocr.micro_segmentos),
    )


def ordenar(bloques: Iterable[BloqueRenderizable]) -> list[BloqueRenderizable]:
    """Orden de lectura del documento: por pagina y dentro de ella por posicion."""
    return sorted(bloques, key=lambda b: (b.pagina, b.orden_lectura))
