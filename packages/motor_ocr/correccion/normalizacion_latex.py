"""Normalización de comandos LaTeX equivalentes según guía de estilo interna.

- \\dfrac{}{} vs \\frac{}{} -> estandarizar.
- \\left(/\\right) vs paréntesis sueltos -> aplicar consistentemente cuando
  el contenido lo amerita (fracciones, matrices).
- Espaciado redundante (\\,\\,\\,) -> colapsar.
- Alias de comandos (\\varnothing vs \\emptyset) -> estandarizar.
"""

from __future__ import annotations

import re

# Mapa de equivalencias: {no_estándar: estándar}
EQUIVALENCIAS_LATEX = {
    # Fracciones
    r'\\dfrac': r'\frac',

    # Conjuntos
    r'\\varnothing': r'\emptyset',
    r'\\emptyset': r'\emptyset',  # Idempotente

    # Operadores
    r'\\cdot': r'\cdot',  # Estándar
    r'\\times': r'\times',  # Estándar

    # Delimitadores
    r'\\vert': r'|',
    r'\\Vert': r'\|',

    # Espaciado redundante
    r'\\,\\,\\,': r'\,',
    r'\\;\\;\\;': r'\;',
    r'\\:\\:\\:': r'\:',

    # Notación de límites
    r'\limit': r'\lim',
    r'\liminf': r'\liminf',
    r'\limsup': r'\limsup',
}

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

    # 1. Comandos equivalentes
    for no_estandar, estandar in EQUIVALENCIAS_LATEX.items():
        patron = re.escape(no_estandar)
        matches = re.findall(patron, resultado)
        if matches:
            resultado = re.sub(patron, estandar, resultado)
            reparaciones.append(f"Normalizado {no_estandar} → {estandar} ({len(matches)} ocurrencias)")

    # 2. Colapsar espaciado múltiple
    espacios_multiples = re.findall(r'\\s{2,}', resultado)
    if espacios_multiples:
        resultado = re.sub(r'\\s{2,}', r'\\,', resultado)
        reparaciones.append(f"Colapsado espaciado múltiple ({len(espacios_multiples)} ocurrencias)")

    # 3. Normalizar delimitadores redundantes: \left( ... \right) sin contenido
    resultado, repairs_delim = _normalizar_delimitadores(resultado)
    reparaciones.extend(repairs_delim)

    # 4. Normalizar super/subíndices inconsistentes
    resultado, repairs_indice = _normalizar_indices(resultado)
    reparaciones.extend(repairs_indice)

    return resultado, reparaciones

def _normalizar_delimitadores(latex: str) -> tuple[str, list[str]]:
    """Normaliza \\left( y \\right) según contenido."""
    reparaciones = []

    # Patrón: \left(contenido\right)
    patron = r'\\left\(([^()]*)\\\right\)'
    matches = list(re.finditer(patron, latex))

    for match in matches:
        contenido = match.group(1)
        # Si es corto, quitar \left \right
        if len(contenido) < 30:
            reemplazo = f'({contenido})'
            latex = latex[:match.start()] + reemplazo + latex[match.end():]
            reparaciones.append(f"Removido \\left\\right de contenido corto")

    return latex, reparaciones

def _normalizar_indices(latex: str) -> tuple[str, list[str]]:
    """Normaliza superíndices/subíndices inconsistentes."""
    reparaciones = []

    # Patrón: x^ a (espacio entre ^ y índice) → x^a
    patron_super = r'\^(\s+)'
    if re.search(patron_super, latex):
        latex = re.sub(patron_super, '^', latex)
        reparaciones.append("Normalizado espaciado en superíndices")

    # Patrón: x_ a → x_a
    patron_sub = r'_(\s+)'
    if re.search(patron_sub, latex):
        latex = re.sub(patron_sub, '_', latex)
        reparaciones.append("Normalizado espaciado en subíndices")

    return latex, reparaciones
