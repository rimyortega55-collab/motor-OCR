"""Renderizado a Markdown.

Segundo formato del producto, despues de LaTeX. Las convenciones estan elegidas
para que el resultado se lea como un documento y no como un volcado del motor:
los folios corrientes se omiten, los encabezados llevan el nivel que indica su
numeracion de seccion, y los items de una lista van pegados para no producir una
lista "suelta" con un parrafo por item.
"""

from __future__ import annotations

import re
from typing import Sequence

from .contrato import BloqueRenderizable, DocumentoRenderizable, ordenar

# Tipos que no son contenido del documento: folios corrientes y numeros de
# pagina. El visor de revision los muestra, pero en el .md son ruido de imprenta
# y cortan la lectura en medio de un parrafo.
TIPOS_OMITIDOS = {"ruido"}

# Bloques con enunciado propio. En LaTeX salen como entornos de amsthm; en
# Markdown no hay equivalente, asi que se marca la etiqueta en negrita y se cita
# el cuerpo, que es la convencion usual para destacarlos.
_ETIQUETA_ENUNCIADO = re.compile(
    r"^((?:teorema|theorem|lema|lemma|proposici[óo]n|proposition|definici[óo]n|"
    r"definition|corolario|corollary|proof|prueba|demostraci[óo]n)"
    r"(?:\s+\d+(?:\.\d+)*)?(?:\s*\([^)]{0,60}\))?\s*[.:])\s*",
    re.IGNORECASE,
)
TIPOS_ENUNCIADO = {
    "teorema",
    "lema",
    "proposicion",
    "definicion",
    "corolario",
    "demostracion",
}

# "3.4.1 Describing Expressions" -> nivel 4. La numeracion de la seccion es la
# unica jerarquia que sobrevive a la conversion: el tamano de fuente que la
# revelo en la capa de layout no viaja hasta aca.
_NUMERACION_SECCION = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")

# Un item que ya viene marcado no se vuelve a marcar.
_ITEM_MARCADO = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


def nivel_encabezado(texto: str) -> str:
    coincidencia = _NUMERACION_SECCION.match(texto)
    if not coincidencia:
        return "##"
    profundidad = coincidencia.group(1).count(".") + 2
    return "#" * min(profundidad, 6)


def _como_lista(texto: str) -> str:
    """Un item por linea, sin duplicar la marca de los que ya la traen."""
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    items = []
    for linea in lineas:
        linea = re.sub(r"^[•·]\s*", "", linea)
        items.append(linea if _ITEM_MARCADO.match(linea) else f"- {linea}")
    return "\n".join(items)


def _como_enunciado(texto: str) -> str:
    etiqueta = _ETIQUETA_ENUNCIADO.match(texto)
    if etiqueta:
        cuerpo = texto[etiqueta.end():].strip()
        texto = f"**{etiqueta.group(1)}** {cuerpo}".strip()
    return "\n".join(f"> {linea}" for linea in texto.splitlines())


def bloque_a_markdown(tipo: str, texto: str) -> str:
    if tipo == "encabezado":
        return f"{nivel_encabezado(texto)} {texto}"
    if tipo == "formula_display":
        return f"$$\n{texto}\n$$"
    if tipo == "codigo":
        return f"```\n{texto}\n```"
    if tipo == "lista":
        return _como_lista(texto)
    if tipo in TIPOS_ENUNCIADO:
        return _como_enunciado(texto)
    return texto


def renderizar(
    documento: DocumentoRenderizable, bloques: Sequence[BloqueRenderizable]
) -> str:
    # El titulo del documento es el nombre del archivo subido. La extension no
    # aporta nada como encabezado de nivel 1.
    titulo = re.sub(r"\.pdf$", "", documento.titulo or "documento", flags=re.IGNORECASE)
    partes = [f"# {titulo}"]
    pagina_actual = None
    tipo_anterior = None

    for bloque in ordenar(bloques):
        if bloque.tipo in TIPOS_OMITIDOS:
            continue

        texto = bloque.texto.strip()
        if not texto:
            continue

        if bloque.pagina != pagina_actual:
            pagina_actual = bloque.pagina
            partes.extend(["", f"<!-- página {pagina_actual + 1} -->"])
            tipo_anterior = None

        # Los items de una misma lista van pegados: separarlos con una linea en
        # blanco la vuelve una lista "suelta", que se renderiza con un parrafo
        # por item y separa un indice general en decenas de bloques sueltos.
        if not (tipo_anterior == "lista" and bloque.tipo == "lista"):
            partes.append("")

        partes.append(bloque_a_markdown(bloque.tipo, texto))
        tipo_anterior = bloque.tipo

    partes.append("")
    return "\n".join(partes)
