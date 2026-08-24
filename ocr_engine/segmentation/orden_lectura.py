"""Resolución de orden de lectura, incluyendo layouts de dos columnas.

En una sola columna es trivial (arriba hacia abajo). En dos columnas (común
en libros de matemática) se requiere agrupar por columna antes de asignar el
índice — de lo contrario el texto sale desordenado y ninguna corrección
posterior lo repara bien.

La detección de columnas busca una *calle*: una banda vertical que ningún
bloque cruza. Es la señal que define a un layout de dos columnas y no aparece
en uno de una sola. La versión anterior comparaba huecos entre los bordes
izquierdos (`max_gap > avg_gap * 2`), lo que con muchos bloques por página se
cumple casi siempre por sangrías y títulos centrados: activaba el modo
multi-columna en documentos de una columna y reordenaba el texto por grupos,
dejándolo ilegible.
"""

from __future__ import annotations

from ocr_engine.models import Bloque

# Una calle creíble cae en la franja central de la página.
_BANDA_BUSQUEDA = (0.35, 0.65)
# Ambos lados tienen que tener contenido real para hablar de dos columnas.
_MIN_PROPORCION_POR_LADO = 0.2


def resolver_orden_lectura(bloques: list[Bloque]) -> list[Bloque]:
    """Resuelve orden de lectura incluyendo layouts multi-columna."""
    if not bloques:
        return bloques

    calle = _detectar_calle(bloques)

    if calle is None:
        return _ordenar_una_columna(bloques)

    return _ordenar_dos_columnas(bloques, calle)


def _detectar_calle(bloques: list[Bloque]) -> float | None:
    """Devuelve la x de la calle entre columnas, o None si es una sola columna."""

    if len(bloques) < 4:
        return None

    izquierdas = [b.layout.bbox[0] for b in bloques]
    derechas = [b.layout.bbox[2] for b in bloques]

    x_min, x_max = min(izquierdas), max(derechas)
    ancho = x_max - x_min
    if ancho <= 0:
        return None

    inicio = x_min + ancho * _BANDA_BUSQUEDA[0]
    fin = x_min + ancho * _BANDA_BUSQUEDA[1]

    mejor_x = None
    mejor_equilibrio = 0.0

    # Se prueban cortes dentro de la franja central y se conserva el que deja
    # los dos lados más parejos sin que ningún bloque lo cruce.
    pasos = 30
    for i in range(pasos + 1):
        x = inicio + (fin - inicio) * i / pasos

        cruzan = sum(1 for b in bloques if b.layout.bbox[0] < x < b.layout.bbox[2])
        if cruzan:
            continue

        izquierda = sum(1 for b in bloques if b.layout.bbox[2] <= x)
        derecha = len(bloques) - izquierda

        proporcion_menor = min(izquierda, derecha) / len(bloques)
        if proporcion_menor < _MIN_PROPORCION_POR_LADO:
            continue

        if proporcion_menor > mejor_equilibrio:
            mejor_equilibrio = proporcion_menor
            mejor_x = x

    return mejor_x


def _ordenar_una_columna(bloques: list[Bloque]) -> list[Bloque]:
    """Arriba hacia abajo y, a igual altura, de izquierda a derecha.

    El desempate por x importa cuando el detector devuelve varias líneas con
    coordenadas verticales casi idénticas: sin él el orden queda a merced de
    cómo vinieran en la lista.
    """
    ordenados = sorted(bloques, key=lambda b: (b.layout.bbox[1], b.layout.bbox[0]))

    for i, bloque in enumerate(ordenados):
        bloque.layout.orden_lectura = i

    return ordenados


def _ordenar_dos_columnas(bloques: list[Bloque], calle: float) -> list[Bloque]:
    """Columna izquierda completa y después la derecha, cada una de arriba abajo."""

    izquierda = [b for b in bloques if b.layout.bbox[2] <= calle]
    derecha = [b for b in bloques if b.layout.bbox[2] > calle]

    ordenados = []
    for columna in (izquierda, derecha):
        columna.sort(key=lambda b: (b.layout.bbox[1], b.layout.bbox[0]))
        ordenados.extend(columna)

    for i, bloque in enumerate(ordenados):
        bloque.layout.orden_lectura = i

    return ordenados
