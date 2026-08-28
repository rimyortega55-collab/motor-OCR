"""Normalización de comandos LaTeX equivalentes según guía de estilo interna.

- \\dfrac{}{} vs \\frac{}{} -> estandarizar.
- \\left(/\\right) vs paréntesis sueltos -> quitar los delimitadores elásticos
  cuando el contenido es corto y no los amerita.
- Espaciado redundante (\\,\\,\\,) -> colapsar.
- Alias de comandos (\\varnothing vs \\emptyset) -> estandarizar.

Sobre los patrones
------------------
Las claves de `EQUIVALENCIAS_LATEX` son el comando tal como aparece en el
LaTeX de entrada, con **un solo** backslash, y se escapan con `re.escape` al
armar el patrón. Escribirlas con doble backslash pensando en la sintaxis de
expresiones regulares y encima pasarlas por `re.escape` produce un patrón que
exige dos backslashes literales, que en LaTeX real no ocurre nunca: el mapa
entero queda inerte sin que falle ningún test. Es el defecto que tenía esta
función y por eso vale la pena dejarlo dicho.

Cada comando se ancla con `(?![A-Za-z])` para no reemplazar dentro de un
comando más largo: sin ese anclaje, `\\vert` pisaría el prefijo de
`\\vertical` y `\\lim` el de `\\liminf`.
"""

from __future__ import annotations

import re

# Mapa de equivalencias: {como_viene: como_queda}. Sólo entradas que cambian
# algo; un alias que se mapea a sí mismo no es idempotencia, es una reparación
# fantasma que se reporta al usuario sin haber tocado nada.
EQUIVALENCIAS_LATEX = {
    # Fracciones
    r"\dfrac": r"\frac",
    r"\tfrac": r"\frac",

    # Conjuntos
    r"\varnothing": r"\emptyset",

    # Delimitadores
    r"\vert": r"|",
    r"\Vert": r"\|",

    # Notación de límites
    r"\limit": r"\lim",
}

# Comandos de espaciado fino de LaTeX. Una tirada de dos o más colapsa a uno:
# el OCR tiende a multiplicarlos y no cambian el significado de la fórmula.
_ESPACIADOS = (r"\,", r"\;", r"\:")

# Un contenido más largo que esto se queda con `\left`/`\right`: son los casos
# -fracciones altas, matrices- donde el delimitador elástico sí hace falta.
_LARGO_MAXIMO_SIN_DELIMITADOR = 30


def normalizar_latex(latex: str) -> tuple[str, list[str]]:
    """Normaliza comandos LaTeX equivalentes.

    Args:
        latex: Cadena LaTeX a normalizar

    Returns:
        (latex_normalizado, lista_de_reparaciones)
    """
    if not latex or not latex.strip():
        return latex, []

    resultado = latex
    reparaciones = []

    # 1. Comandos equivalentes. Se ordena de más largo a más corto para que
    #    `\Vert` se resuelva antes que `\vert` aunque el diccionario cambie de
    #    orden con el tiempo.
    for no_estandar in sorted(EQUIVALENCIAS_LATEX, key=len, reverse=True):
        estandar = EQUIVALENCIAS_LATEX[no_estandar]
        patron = re.escape(no_estandar) + r"(?![A-Za-z])"
        resultado, cambios = re.subn(patron, estandar.replace("\\", r"\\"), resultado)
        if cambios:
            reparaciones.append(
                f"Normalizado {no_estandar} → {estandar} ({cambios} ocurrencias)"
            )

    # 2. Colapsar espaciado fino repetido
    for espaciado in _ESPACIADOS:
        patron = f"(?:{re.escape(espaciado)}){{2,}}"
        resultado, cambios = re.subn(patron, espaciado.replace("\\", r"\\"), resultado)
        if cambios:
            reparaciones.append(
                f"Colapsado espaciado repetido {espaciado} ({cambios} ocurrencias)"
            )

    # 3. Normalizar delimitadores elásticos innecesarios
    resultado, repairs_delim = _normalizar_delimitadores(resultado)
    reparaciones.extend(repairs_delim)

    # 4. Normalizar super/subíndices inconsistentes
    resultado, repairs_indice = _normalizar_indices(resultado)
    reparaciones.extend(repairs_indice)

    return resultado, reparaciones


def _normalizar_delimitadores(latex: str) -> tuple[str, list[str]]:
    """Quita `\\left(...\\right)` cuando el contenido es corto.

    El reemplazo va por `re.sub` con callback y no por un bucle que corta y
    pega sobre la cadena: reescribir el texto mientras se usan los offsets de
    coincidencias calculadas sobre la versión anterior desplaza todo lo que
    viene después del primer reemplazo.
    """
    reparaciones = []

    def _reemplazar(match: re.Match) -> str:
        contenido = match.group(1)
        if len(contenido) < _LARGO_MAXIMO_SIN_DELIMITADOR:
            reparaciones.append("Removido \\left\\right de contenido corto")
            return f"({contenido})"
        return match.group(0)

    patron = r"\\left\(([^()]*)\\right\)"
    return re.sub(patron, _reemplazar, latex), reparaciones


def _normalizar_indices(latex: str) -> tuple[str, list[str]]:
    """Normaliza superíndices/subíndices inconsistentes."""
    reparaciones = []

    # Patrón: x^ a (espacio entre ^ y índice) → x^a
    patron_super = r"\^(\s+)"
    if re.search(patron_super, latex):
        latex = re.sub(patron_super, "^", latex)
        reparaciones.append("Normalizado espaciado en superíndices")

    # Patrón: x_ a → x_a
    patron_sub = r"_(\s+)"
    if re.search(patron_sub, latex):
        latex = re.sub(patron_sub, "_", latex)
        reparaciones.append("Normalizado espaciado en subíndices")

    return latex, reparaciones
