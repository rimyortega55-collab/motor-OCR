"""Validación estructural con reparación determinista de LaTeX.

- Paréntesis/llaves desbalanceados con desbalance simple -> inferir y cerrar
  automáticamente contando profundidad de anidamiento.
- \\begin{...} sin \\end{...} correspondiente -> intentar emparejar por
  proximidad.
- Si la reparación falla o el desbalance es ambiguo -> se marca para escalar
  (bloques_pendientes_escalacion en DocumentPostCorrection).
"""

from __future__ import annotations

import re
from collections import deque

def reparar_estructura(latex: str) -> tuple[str, list[str], bool]:
    """Repara estructura LaTeX y detecta si requiere escalación.

    Args:
        latex: Cadena LaTeX a reparar

    Returns:
        (latex_reparado, reparaciones_aplicadas, requiere_escalacion)
    """
    if not latex or not latex.strip():
        return latex, [], False

    resultado = latex
    reparaciones = []
    requiere_escalacion = False

    # 1. Reparar llaves desbalanceadas
    resultado, repairs_llaves, escala_llaves = _reparar_llaves(resultado)
    reparaciones.extend(repairs_llaves)
    requiere_escalacion = requiere_escalacion or escala_llaves

    # 2. Reparar paréntesis desbalanceados
    resultado, repairs_parens, escala_parens = _reparar_parentesis(resultado)
    reparaciones.extend(repairs_parens)
    requiere_escalacion = requiere_escalacion or escala_parens

    # 3. Reparar entornos \begin \end desbalanceados
    resultado, repairs_entornos, escala_entornos = _reparar_entornos(resultado)
    reparaciones.extend(repairs_entornos)
    requiere_escalacion = requiere_escalacion or escala_entornos

    # 4. Validación final: si sigue desbalanceado, requerir escalación
    if not _valida_estructura(resultado):
        requiere_escalacion = True
        reparaciones.append("Estructura aún desbalanceada tras reparación automática")

    return resultado, reparaciones, requiere_escalacion

def _reparar_llaves(latex: str) -> tuple[str, list[str], bool]:
    """Repara llaves desbalanceadas por conteo simple."""
    reparaciones = []
    requiere_escalacion = False

    open_count = latex.count('{')
    close_count = latex.count('}')

    if open_count == close_count:
        return latex, reparaciones, False

    # Verificar si están balanceadas por profundidad
    depth = 0
    max_depth = 0
    min_depth = 0

    for char in latex:
        if char == '{':
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == '}':
            depth -= 1
            min_depth = min(min_depth, depth)

    if depth > 0:
        # Faltan closes
        latex = latex + '}' * depth
        reparaciones.append(f"Agregadas {depth} llaves de cierre")

    elif depth < 0:
        # Faltan opens (más ambiguo)
        latex = '{' * (-depth) + latex
        reparaciones.append(f"Agregadas {-depth} llaves de apertura (ambiguo)")
        requiere_escalacion = True

    return latex, reparaciones, requiere_escalacion

def _reparar_parentesis(latex: str) -> tuple[str, list[str], bool]:
    """Repara paréntesis desbalanceados."""
    reparaciones = []
    requiere_escalacion = False

    open_count = latex.count('(')
    close_count = latex.count(')')

    if open_count == close_count:
        return latex, reparaciones, False

    if open_count > close_count:
        latex = latex + ')' * (open_count - close_count)
        reparaciones.append(f"Agregados {open_count - close_count} paréntesis de cierre")

    else:
        # Más closes que opens (ambiguo)
        latex = '(' * (close_count - open_count) + latex
        reparaciones.append(f"Agregados {close_count - open_count} paréntesis de apertura (ambiguo)")
        requiere_escalacion = True

    return latex, reparaciones, requiere_escalacion

def _reparar_entornos(latex: str) -> tuple[str, list[str], bool]:
    """Repara \\begin{...} \\end{...} desbalanceados."""
    reparaciones = []
    requiere_escalacion = False

    # Encontrar todos \begin{...}
    begins = re.findall(r'\\begin\{([^}]+)\}', latex)
    # Encontrar todos \end{...}
    ends = re.findall(r'\\end\{([^}]+)\}', latex)

    begin_set = list(begins)
    end_set = list(ends)

    # Emparejar: los últimos begins sin end
    for entorno in begin_set:
        if entorno not in end_set or begin_set.count(entorno) > end_set.count(entorno):
            # Falta un \end{entorno}
            latex = latex + f'\n\\end{{{entorno}}}'
            reparaciones.append(f"Agregado \\end{{{entorno}}} faltante")
            end_set.append(entorno)

    # Si hay \end sin \begin, es más ambiguo
    for entorno in end_set:
        if entorno not in begin_set or end_set.count(entorno) > begin_set.count(entorno):
            # Hay un \end sin \begin
            reparaciones.append(f"Detectado \\end{{{entorno}}} sin \\begin (ambiguo)")
            requiere_escalacion = True

    return latex, reparaciones, requiere_escalacion

def _valida_estructura(latex: str) -> bool:
    """Valida que la estructura sea correcta sin ser demasiado estricta."""
    # Conteos básicos
    if latex.count('{') != latex.count('}'):
        return False

    if latex.count('(') != latex.count(')'):
        return False

    # Profundidad: no debe ser negativa en ningún punto
    depth_braces = 0
    depth_parens = 0

    for char in latex:
        if char == '{':
            depth_braces += 1
        elif char == '}':
            depth_braces -= 1
            if depth_braces < 0:
                return False

        elif char == '(':
            depth_parens += 1
        elif char == ')':
            depth_parens -= 1
            if depth_parens < 0:
                return False

    return True
