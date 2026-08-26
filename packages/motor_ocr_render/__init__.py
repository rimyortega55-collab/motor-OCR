"""Renderizado del documento convertido a los formatos de salida.

Un formato, un modulo. El paquete no importa el motor ni la base: recibe las
estructuras planas de `contrato.py` y devuelve texto, asi que un renderizador se
puede probar sin levantar la aplicacion ni tocar una fila.

LaTeX y Markdown son los formatos principales del producto y se refinan en ese
orden. ipynb queda como opcion para quien escribe codigo sobre lo convertido, y
graphify es la salida que consume el indexador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from . import graphify, ipynb, latex, markdown
from .contrato import (
    BloqueRenderizable,
    DocumentoRenderizable,
    contenido_efectivo,
    desde_almacenado,
    desde_bloque,
    ordenar,
)


@dataclass(frozen=True)
class Formato:
    """Un formato de salida y como se entrega."""

    renderizar: Callable[[DocumentoRenderizable, Sequence[BloqueRenderizable]], str]
    mime: str
    extension: str


FORMATOS: dict[str, Formato] = {
    "latex": Formato(latex.renderizar, "application/x-tex", "tex"),
    "markdown": Formato(markdown.renderizar, "text/markdown; charset=utf-8", "md"),
    "ipynb": Formato(ipynb.renderizar, "application/x-ipynb+json", "ipynb"),
    "graphify": Formato(graphify.renderizar, "application/json", "json"),
}


def renderizar(
    formato: str,
    documento: DocumentoRenderizable,
    bloques: Sequence[BloqueRenderizable],
) -> str:
    """Renderiza al formato pedido. Lanza KeyError si no existe."""
    return FORMATOS[formato].renderizar(documento, bloques)


__all__ = [
    "FORMATOS",
    "Formato",
    "BloqueRenderizable",
    "DocumentoRenderizable",
    "contenido_efectivo",
    "desde_almacenado",
    "desde_bloque",
    "ordenar",
    "renderizar",
    "graphify",
    "ipynb",
    "latex",
    "markdown",
]
