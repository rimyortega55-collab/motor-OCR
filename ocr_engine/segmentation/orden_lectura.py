"""Resolución de orden de lectura, incluyendo layouts de dos columnas.

En una sola columna es trivial (arriba hacia abajo). En dos columnas (común
en libros de matemática) se requiere agrupar por columna antes de asignar el
índice — de lo contrario el texto sale desordenado y ninguna corrección
posterior lo repara bien.
"""

from __future__ import annotations

from ocr_engine.models import Bloque


def resolver_orden_lectura(bloques: list[Bloque]) -> list[Bloque]:
    """Resuelve orden de lectura incluyendo layouts multi-columna."""
    if not bloques:
        return bloques

    # Detect if multi-column layout
    bboxes = [b.layout.bbox for b in bloques]
    x_positions = [b[0] for b in bboxes]
    x_min = min(x_positions)
    x_max = max(x_positions)

    # Calculate gap in X distribution
    x_positions_sorted = sorted(set(x_positions))
    if len(x_positions_sorted) > 1:
        gaps = [
            x_positions_sorted[i + 1] - x_positions_sorted[i]
            for i in range(len(x_positions_sorted) - 1)
        ]
        max_gap = max(gaps) if gaps else 0
        avg_gap = sum(gaps) / len(gaps) if gaps else 0

        # If there's a significant gap, likely multi-column
        is_multicolumn = max_gap > avg_gap * 2
    else:
        is_multicolumn = False

    if not is_multicolumn:
        # Single column: sort by Y position (top to bottom)
        bloques_sorted = sorted(bloques, key=lambda b: b.layout.bbox[1])
        for i, b in enumerate(bloques_sorted):
            b.layout.orden_lectura = i
        return bloques_sorted

    # Multi-column: group by column position
    page_width = x_max - x_min
    column_threshold = page_width * 0.3  # blocks > 30% of page width apart are different columns

    # Find column centers
    column_groups = []
    for bloque in bloques:
        x_center = (bloque.layout.bbox[0] + bloque.layout.bbox[2]) / 2
        placed = False

        for group in column_groups:
            group_x = sum(
                (b.layout.bbox[0] + b.layout.bbox[2]) / 2 for b in group
            ) / len(group)
            if abs(x_center - group_x) < column_threshold:
                group.append(bloque)
                placed = True
                break

        if not placed:
            column_groups.append([bloque])

    # Sort each column by Y, then merge columns left to right
    column_groups.sort(key=lambda g: min(b.layout.bbox[0] for b in g))

    for col_idx, group in enumerate(column_groups):
        group.sort(key=lambda b: b.layout.bbox[1])

    # Assign reading order: column by column, top to bottom
    orden = 0
    for group in column_groups:
        for bloque in group:
            bloque.layout.orden_lectura = orden
            orden += 1

    # Merge all groups preserving order
    result = []
    for group in column_groups:
        result.extend(group)

    return result
