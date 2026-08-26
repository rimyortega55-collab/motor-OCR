"""Coordenadas de los bloques, en un único espacio.

Los dos caminos de segmentación producían el bbox en unidades distintas:
`nativo_digital` lo toma de PyMuPDF, en **puntos PDF** (72 dpi), y `escaneado`
lo toma de docTR o de la morfología, en **píxeles del render**. Cualquier
consumidor que reciba bloques de los dos caminos —el recorte que la Capa 5 le
manda al modelo, el overlay del visor de revisión— tenía que adivinar cuál era
cuál, y un bloque nativo dibujado sobre una página a 200 dpi salía a un tercio
de su tamaño real.

Acá el bbox se guarda siempre **normalizado a la caja de la página**: cuatro
flotantes en `[0, 1]`. Quien necesita píxeles multiplica por el tamaño de la
imagen que tiene en la mano, y deja de importar de qué capa vino el bloque.
"""

from __future__ import annotations

Bbox = tuple[float, float, float, float]


def normalizar_bbox(bbox: Bbox, caja: tuple[float, float]) -> Bbox:
    """Lleva un bbox absoluto a fracciones de la página.

    `caja` es (ancho, alto) en las mismas unidades que el bbox: puntos para el
    camino nativo, píxeles para el escaneado.
    """
    ancho, alto = caja
    if not ancho or not alto:
        # Una página sin dimensiones no debería existir, pero dividir por cero
        # rompería la segmentación entera por un caso degenerado.
        return (0.0, 0.0, 0.0, 0.0)

    x0, y0, x1, y1 = bbox
    return (
        _acotar(x0 / ancho),
        _acotar(y0 / alto),
        _acotar(x1 / ancho),
        _acotar(y1 / alto),
    )


def desnormalizar_bbox(bbox: Bbox, caja: tuple[float, float]) -> tuple[int, int, int, int]:
    """Devuelve el bbox en píxeles enteros de una imagen de tamaño `caja`.

    Los valores salen ya acotados a la imagen, listos para recortar sin
    verificar rangos otra vez.
    """
    ancho, alto = caja
    x0, y0, x1, y1 = bbox

    return (
        max(0, min(int(x0 * ancho), int(ancho))),
        max(0, min(int(y0 * alto), int(alto))),
        max(0, min(int(x1 * ancho), int(ancho))),
        max(0, min(int(y1 * alto), int(alto))),
    )


def _acotar(valor: float) -> float:
    """Recorta a [0, 1].

    docTR devuelve de vez en cuando cajas que se salen apenas del borde de la
    página; sin acotar, el recorte pediría píxeles inexistentes.
    """
    return 0.0 if valor < 0.0 else (1.0 if valor > 1.0 else float(valor))
