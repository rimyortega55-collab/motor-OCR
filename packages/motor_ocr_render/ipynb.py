"""Renderizado a cuaderno Jupyter.

Formato secundario: para quien escribe codigo sobre lo convertido, no para leer.
"""

from __future__ import annotations

import json
from typing import Sequence

from .contrato import BloqueRenderizable, DocumentoRenderizable, ordenar
from .markdown import TIPOS_OMITIDOS


def renderizar(
    documento: DocumentoRenderizable, bloques: Sequence[BloqueRenderizable]
) -> str:
    celdas = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [f"# {documento.titulo}"],
        }
    ]

    for bloque in ordenar(bloques):
        if bloque.tipo in TIPOS_OMITIDOS:
            continue

        texto = bloque.texto.strip()
        if not texto:
            continue

        if bloque.tipo == "codigo":
            celdas.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": texto.splitlines(keepends=True),
            })
        else:
            fuente = f"$$\n{texto}\n$$" if bloque.tipo == "formula_display" else texto
            celdas.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": fuente.splitlines(keepends=True),
            })

    cuaderno = {
        "cells": celdas,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(cuaderno, ensure_ascii=False, indent=1)
