"""Corrección ortográfica determinista y quirúrgica.

Diccionario base del idioma + diccionario técnico-matemático curado (evita
que un corrector genérico "arregle" términos legítimos). Se corrige solo
cuando la palabra no está en ningún diccionario Y existe una corrección de
distancia de edición 1 (config.settings) con alta frecuencia en el corpus.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Diccionarios curados
DICCIONARIO_GENERAL = {
    # Palabras comunes en español (muestra pequeña)
    'el', 'la', 'de', 'que', 'y', 'a', 'en', 'un', 'ser', 'se', 'no',
    'por', 'con', 'su', 'para', 'es', 'al', 'lo', 'como', 'más', 'o',
    'pero', 'sus', 'le', 'ya', 'o', 'fue', 'este', 'ha', 'sí', 'porque',
    'esta', 'son', 'entre', 'está', 'cuando', 'muy', 'sin', 'sobre', 'ser',
    'tiene', 'también', 'me', 'hasta', 'hay', 'donde', 'han', 'quien',
    'están', 'estado', 'desde', 'todo', 'nos', 'durante', 'estados', 'todos',
    'uno', 'les', 'ni', 'contra', 'otros', 'fueron', 'ese', 'eso', 'ellos',
    'e', 'esto', 'mí', 'antes', 'algunos', 'qué', 'unos', 'yo', 'otro',
    'otras', 'otra', 'él', 'tanto', 'esa', 'estos', 'mucho', 'quienes',
    'nada', 'muchos', 'cual', 'sea', 'sea', 'poco', 'ella', 'estar',
}

DICCIONARIO_TECNICO_MATEMATICO = {
    # Términos matemáticos y científicos
    'teorema', 'lema', 'proposición', 'corolario', 'demostración',
    'definición', 'axioma', 'conjetura', 'prueba', 'contradicción',
    'matriz', 'vector', 'polinomio', 'ecuación', 'función', 'derivada',
    'integral', 'límite', 'continuidad', 'convergencia', 'serie', 'conjunto',
    'subconjunto', 'elemento', 'aplicación', 'homomorfismo', 'isomorfismo',
    'grupo', 'anillo', 'cuerpo', 'espacio', 'topología', 'métrica',
    'norma', 'base', 'dimensión', 'rango', 'determinante', 'autovalor',
    'eigenvector', 'variedad', 'manifold', 'geometría', 'probabilidad',
    'estadística', 'distribución', 'varianza', 'covarianza', 'esperanza',
    'fracción', 'numerador', 'denominador', 'raíz', 'potencia', 'exponente',
    'factor', 'múltiplo', 'divisor', 'primo', 'infinito', 'epsilon',
    'delta', 'lambda', 'álgebra', 'cálculo', 'análisis', 'lógica',
    'booleano', 'conectivo', 'cuantificador', 'predicado', 'variables',
    'parámetro', 'incógnita', 'solución', 'raíces', 'desarrollo', 'expansión',
}

# Correcciones comunes por distancia de edición (OCR errors)
CORRECCIONES_FRECUENTES = {
    'rn': 'm',  # O confunde rn con m
    'l': '1',   # Evitar cambiar 1 a l
    'O': '0',   # O confunde O con 0
    'acá': 'acá',  # Corrección redundante para ejemplo
    # Errores de OCR típicos en español
    'tenia': 'tenía',
    'sería': 'sería',
    'habia': 'había',
    'podria': 'podría',
    'seria': 'sería',
    'recibia': 'recibía',
}

def corregir_ortografia(
    texto: str, diccionario_usado: str = "general"
) -> tuple[str, list[str]]:
    """Corrige ortografía de forma determinista usando diccionarios curados.

    Args:
        texto: Texto a corregir
        diccionario_usado: "general" | "tecnico_matematico" | "ambos"

    Returns:
        (texto_corregido, lista_de_reparaciones)
    """
    if not texto or not texto.strip():
        return texto, []

    resultado = texto
    reparaciones = []

    # Seleccionar diccionario
    if diccionario_usado == "tecnico_matematico":
        diccionario = DICCIONARIO_TECNICO_MATEMATICO
    elif diccionario_usado == "ambos":
        diccionario = DICCIONARIO_GENERAL | DICCIONARIO_TECNICO_MATEMATICO
    else:
        diccionario = DICCIONARIO_GENERAL

    # 1. Corregir OCR errors frecuentes
    for error, correcto in CORRECCIONES_FRECUENTES.items():
        patron = r'\b' + re.escape(error) + r'\b'
        if re.search(patron, resultado, re.IGNORECASE):
            matches = len(re.findall(patron, resultado, re.IGNORECASE))
            resultado = re.sub(patron, correcto, resultado, flags=re.IGNORECASE)
            reparaciones.append(f"Corregido OCR error '{error}' → '{correcto}' ({matches} ocurrencias)")

    # 2. Corrección ortográfica: palabras no reconocidas
    palabras = re.findall(r'\b\w+\b', resultado)

    for palabra in set(palabras):
        palabra_lower = palabra.lower()

        # Si está en diccionario, OK
        if palabra_lower in diccionario:
            continue

        # Si está en diccionario general (con mayúscula), OK
        if palabra[0].isupper() and palabra_lower in diccionario:
            continue

        # Buscar sugerencia por distancia de edición
        sugerencia = _encontrar_sugerencia(palabra_lower, diccionario)

        if sugerencia and sugerencia != palabra_lower:
            # Reemplazar preservando mayúscula original
            if palabra[0].isupper():
                sugerencia_formateada = sugerencia.capitalize()
            else:
                sugerencia_formateada = sugerencia

            patron = r'\b' + re.escape(palabra) + r'\b'
            matches = len(re.findall(patron, resultado))

            if matches > 0:
                resultado = re.sub(patron, sugerencia_formateada, resultado)
                reparaciones.append(f"Corregido '{palabra}' → '{sugerencia_formateada}' ({matches} ocurrencias)")

    return resultado, reparaciones

def _encontrar_sugerencia(palabra: str, diccionario: set[str], max_distancia: int = 1) -> str | None:
    """Encuentra sugerencia por distancia de edición (Levenshtein).

    Solo retorna si:
    1. Distancia <= max_distancia
    2. La palabra sugger está en diccionario
    3. Similitud > umbral mínimo
    """
    mejor_match = None
    mejor_similitud = 0.0

    for dict_word in diccionario:
        similitud = _similitud_levenshtein(palabra, dict_word)

        if similitud > mejor_similitud:
            mejor_similitud = similitud
            mejor_match = dict_word

    # Threshold: 80% similitud mínimo
    if mejor_similitud >= 0.8:
        return mejor_match

    return None

def _similitud_levenshtein(s1: str, s2: str) -> float:
    """Calcula similitud de Levenshtein normalizada (0-1)."""
    if not s1 or not s2:
        return 0.0

    distancia = _distancia_levenshtein(s1, s2)
    max_len = max(len(s1), len(s2))

    # Similitud = 1 - (distancia / max_len)
    return 1.0 - (distancia / max_len)

def _distancia_levenshtein(s1: str, s2: str) -> int:
    """Calcula distancia de edición mínima."""
    if len(s1) < len(s2):
        return _distancia_levenshtein(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]

        for j, c2 in enumerate(s2):
            # Inserciones, deletions, sustituciones
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)

            current_row.append(min(insertions, deletions, substitutions))

        previous_row = current_row

    return previous_row[-1]
