"""Combinación de las tres señales de confianza por micro-segmento.

1. Confianza nativa del engine (score propio de EasyOCR / pix2tex).
2. Validación estructural: ¿el LaTeX resultante compila/parsea sin errores
   de sintaxis? (parser ligero, no requiere pdflatex completo).
3. Consenso entre engines: comparación con Tesseract como fallback barato;
   si difieren mucho, confianza baja.

Solo cuando la combinación cae bajo umbral (config.settings), el
micro-segmento —no el bloque completo— se marca para escalación en Capa 5.
"""

from __future__ import annotations

import re

def calcular_confianza_micro_segmento(
    confianza_engine: float,
    contenido: str,
    es_formula: bool = False,
    consenso_tesseract: float | None = None,
) -> float:
    """Combina tres señales de confianza en una métrica unificada.

    Args:
        confianza_engine: Score nativo del engine (0-1)
        contenido: Contenido extraído (para validación estructural)
        es_formula: ¿Es contenido LaTeX?
        consenso_tesseract: Similitud con resultado de Tesseract (0-1), si aplica

    Returns:
        Confianza combinada (0-1)
    """

    # Señal 1: Confianza nativa del engine
    score_engine = max(0.0, min(1.0, confianza_engine))

    # Señal 2: Validación estructural
    score_estructura = _validar_estructura(contenido, es_formula)

    # Señal 3: Consenso con Tesseract (si aplica)
    score_consenso = consenso_tesseract if consenso_tesseract is not None else 0.5

    # Combinación: promedio ponderado
    # Si la estructura falla, penalizar fuertemente
    if not score_estructura and es_formula:
        # Fórmula con errores sintácticos: baja confianza
        confianza_final = score_engine * 0.3

    else:
        # Promedio ponderado: engine (40%), estructura (30%), consenso (30%)
        confianza_final = (
            score_engine * 0.4 +
            score_estructura * 0.3 +
            score_consenso * 0.3
        )

    return max(0.0, min(1.0, confianza_final))

def _validar_estructura(contenido: str, es_formula: bool) -> float:
    """Valida sintaxis LaTeX o estructura de texto.

    Args:
        contenido: Texto o LaTeX a validar
        es_formula: ¿Es LaTeX?

    Returns:
        1.0 si válido, 0.5 si dudoso, 0.0 si inválido
    """

    if not contenido or not contenido.strip():
        return 0.0

    if not es_formula:
        # Texto plano: validar básicamente que tiene caracteres
        return 1.0 if len(contenido.split()) > 0 else 0.0

    # Validación de LaTeX
    return _validar_latex(contenido)

def _validar_latex(latex_str: str) -> float:
    """Valida sintaxis básica de LaTeX.

    No se requiere compilación completa, solo detectar errores obvios.
    """

    if not latex_str or not latex_str.strip():
        return 0.0

    # Contar paréntesis, corchetes, llaves
    issues = 0

    # Llaves desbalanceadas
    open_braces = latex_str.count('{')
    close_braces = latex_str.count('}')
    if open_braces != close_braces:
        issues += 1

    # Dólares desbalanceados (para $$...$$)
    dollars = latex_str.count('$')
    if dollars % 2 != 0:
        issues += 1

    # Paréntesis
    open_parens = latex_str.count('(')
    close_parens = latex_str.count(')')
    if open_parens != close_parens:
        issues += 0.5

    # Patrones comunes problemáticos
    if '\\\\' in latex_str and not _valida_secuencia_barras(latex_str):
        issues += 0.5

    # Calcular score
    if issues >= 2:
        return 0.0
    elif issues >= 1:
        return 0.5
    else:
        return 1.0

def _valida_secuencia_barras(s: str) -> bool:
    r"""Valida que las secuencias \\ y \ sean válidas."""
    # \\ es válido (salto de línea en LaTeX)
    # \{ es válido (escape de llave)
    # \$ es válido (escape de dólar)
    # Un solo \ al final es inválido

    if s.endswith('\\') and not s.endswith('\\\\'):
        return False

    # Más validaciones podrían agregarse
    return True

def calcular_confianza_bloque(micro_segmentos: list[dict]) -> float:
    """Combina confianzas de micro-segmentos para obtener confianza global del bloque.

    Args:
        micro_segmentos: Lista de dicts con 'confianza_engine', 'confianza_estructural'

    Returns:
        Confianza global (0-1)
    """

    if not micro_segmentos:
        return 0.0

    # Promedio simple (podrían usarse pesos si se desea)
    confianzas = [ms.get('confianza_estructural', 0.0) for ms in micro_segmentos]
    confianza_global = sum(confianzas) / len(confianzas) if confianzas else 0.0

    return max(0.0, min(1.0, confianza_global))
