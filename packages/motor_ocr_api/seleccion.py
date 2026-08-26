"""Selección de páginas a procesar.

Procesar un libro entero para leer un capítulo cuesta tiempo y, si el documento
es escaneado, plata: cada página son segundos de docTR y las de baja confianza
se escalan al modelo. Elegir el rango antes de empezar es la forma más directa de
que el usuario no pague por lo que no va a leer.

Las páginas elegidas se extraen a un PDF nuevo y el pipeline corre sobre ese, sin
enterarse. La alternativa —saltear páginas dentro de las capas— obligaría a que
triage, segmentación y OCR llevaran cuenta de qué páginas existen y cuáles no,
para el mismo resultado.

El costo de esa decisión es que la numeración queda re-basada: si se eligen las
páginas 5 a 10, dentro del documento procesado son la 0 a la 5. Por eso se guarda
el mapeo en `documentos.paginas_origen`, y la interfaz puede mostrar el número
que el usuario reconoce.
"""

from __future__ import annotations

import io
import re

from fastapi import HTTPException, status

# Un rango absurdo casi siempre es un error de tipeo, no una intención.
_PATRON = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


def _error(codigo: str, detalle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"codigo": codigo, "detail": detalle},
    )


def interpretar_rango(expresion: str, total_paginas: int) -> list[int]:
    """Convierte "1-5, 8, 11-13" en índices 0-based ordenados y sin repetidos.

    El usuario escribe páginas 1-based, que es lo que ve en su lector de PDF; el
    pipeline trabaja 0-based. La conversión se hace acá y una sola vez.
    """

    if not expresion or not expresion.strip():
        return list(range(total_paginas))

    elegidas: set[int] = set()

    for trozo in expresion.split(","):
        if not trozo.strip():
            continue

        coincidencia = _PATRON.match(trozo)
        if not coincidencia:
            raise _error(
                "rango_invalido",
                f'No se entiende "{trozo.strip()}". Se escribe como "1-5, 8, 11-13".',
            )

        desde = int(coincidencia.group(1))
        hasta = int(coincidencia.group(2)) if coincidencia.group(2) else desde

        if desde < 1:
            raise _error("rango_invalido", "Las páginas se cuentan desde 1")

        if desde > hasta:
            raise _error(
                "rango_invalido",
                f"El rango {desde}-{hasta} está al revés",
            )

        if desde > total_paginas:
            raise _error(
                "pagina_inexistente",
                f"Pediste la página {desde} y el documento tiene {total_paginas}",
            )

        # Un `hasta` que se pasa del final se recorta en silencio: pedir "10-999"
        # de un documento de 30 páginas es una forma habitual de decir "de la 10
        # hasta el final", no un error que valga la pena rechazar.
        elegidas.update(range(desde - 1, min(hasta, total_paginas)))

    if not elegidas:
        raise _error("seleccion_vacia", "No seleccionaste ninguna página")

    return sorted(elegidas)


def extraer_paginas(contenido: bytes, paginas: list[int]) -> bytes:
    """Devuelve un PDF nuevo con sólo las páginas indicadas, en ese orden."""

    import pymupdf

    with pymupdf.open(stream=io.BytesIO(contenido), filetype="pdf") as origen:
        if len(paginas) == len(origen):
            # Nada que recortar: se evita reescribir el archivo y perder calidad
            # o metadatos por un viaje de ida y vuelta innecesario.
            return contenido

        destino = pymupdf.open()
        try:
            for numero in paginas:
                destino.insert_pdf(origen, from_page=numero, to_page=numero)
            return destino.tobytes()
        finally:
            destino.close()
