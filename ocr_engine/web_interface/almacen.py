"""Guarda los PDF originales y renderiza sus páginas a demanda.

El visor de revisión muestra la página con el overlay de bloques encima, así que
necesita una imagen. Hay dos formas de tenerla: guardar los PNG de todas las
páginas al procesar, o guardar el PDF y renderizar la que se pida.

Se eligió lo segundo. Un PDF de 200 páginas pesa unos pocos MB; sus 200 páginas
renderizadas a 200 dpi pesan cientos. Y el revisor abre unas pocas: renderizar a
demanda con caché en disco paga el costo sólo por lo que se mira de verdad.
"""

from __future__ import annotations

import os
from pathlib import Path

import pymupdf as fitz

# Mismo directorio que usa la base de datos: un solo volumen que respaldar.
DIRECTORIO_DATOS = Path(os.environ.get("MOTOR_OCR_DATA_DIR", "datos"))
PDFS = DIRECTORIO_DATOS / "pdfs"
CACHE_PAGINAS = DIRECTORIO_DATOS / "paginas"

DPI_VISOR = 150
ANCHO_MAXIMO = 2400


def guardar_pdf(documento_id: str, contenido: bytes) -> str:
    """Guarda el PDF y devuelve su ruta relativa al directorio de datos."""

    PDFS.mkdir(parents=True, exist_ok=True)
    destino = PDFS / f"{documento_id}.pdf"
    destino.write_bytes(contenido)
    return str(destino.relative_to(DIRECTORIO_DATOS))


def ruta_absoluta(ruta_relativa: str | None) -> Path | None:
    if not ruta_relativa:
        return None

    ruta = (DIRECTORIO_DATOS / ruta_relativa).resolve()
    # El valor viene de la base, pero si alguna vez se pudiera influir sobre él
    # un `..` sacaría la lectura del directorio de datos.
    if not ruta.is_relative_to(DIRECTORIO_DATOS.resolve()):
        return None

    return ruta if ruta.is_file() else None


def borrar_pdf(ruta_relativa: str | None) -> None:
    ruta = ruta_absoluta(ruta_relativa)
    if ruta is not None:
        ruta.unlink(missing_ok=True)


def dimensiones(ruta_pdf: Path) -> list[dict]:
    """Tamaño en píxeles de cada página al DPI del visor.

    El frontend lo necesita para desnormalizar los bbox y reservar el espacio de
    la imagen antes de que cargue, sin saltos de layout.
    """
    documento = fitz.open(ruta_pdf)
    try:
        zoom = DPI_VISOR / 72.0
        return [
            {
                "pagina": numero,
                "ancho_px": int(pagina.rect.width * zoom),
                "alto_px": int(pagina.rect.height * zoom),
                "dpi": DPI_VISOR,
            }
            for numero, pagina in enumerate(documento)
        ]
    finally:
        documento.close()


def renderizar_pagina(
    documento_id: str, ruta_pdf: Path, numero: int, ancho: int | None = None
) -> Path | None:
    """Devuelve el PNG de una página, renderizándolo la primera vez.

    `ancho` pide una versión reescalada: el visor al 86 % no necesita los 1240 px
    del render completo, y bajar el tamaño reduce mucho lo que viaja por la red.
    """

    if ancho is not None:
        ancho = max(200, min(ancho, ANCHO_MAXIMO))

    CACHE_PAGINAS.mkdir(parents=True, exist_ok=True)
    sufijo = f"-{ancho}" if ancho else ""
    destino = CACHE_PAGINAS / f"{documento_id}-{numero}{sufijo}.png"

    if destino.is_file():
        return destino

    documento = fitz.open(ruta_pdf)
    try:
        if numero < 0 or numero >= len(documento):
            return None

        pagina = documento[numero]
        zoom = DPI_VISOR / 72.0
        if ancho:
            # El ancho pedido manda sobre el DPI: así el cliente controla cuánto
            # baja sin tener que razonar en puntos ni en densidad.
            zoom = ancho / (pagina.rect.width or 1)

        pixmap = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pixmap.save(destino)
        return destino
    finally:
        documento.close()


def borrar_cache(documento_id: str) -> int:
    """Borra las páginas renderizadas de un documento."""
    if not CACHE_PAGINAS.is_dir():
        return 0

    borradas = 0
    for archivo in CACHE_PAGINAS.glob(f"{documento_id}-*.png"):
        archivo.unlink(missing_ok=True)
        borradas += 1
    return borradas
