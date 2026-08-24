#!/usr/bin/env python
"""Genera un corpus de PDFs 'escaneados' a partir de los PDFs nativos digitales.

Los 11 PDFs de `pdfs_de_prueba/` son todos nativo-digital, así que el pipeline
nunca ejercita los motores OCR reales: `enrutar_bloque` corta por el atajo de
TEXTO_NATIVO y devuelve una confianza fija. Rasterizando las páginas a imagen
se elimina la capa de texto embebida, con lo que `detectar_origen` las clasifica
como ESCANEADO y la Capa 3 pasa por easyocr / doctr / pix2tex de verdad.

El corpus se mantiene chico a propósito: el OCR real es lento y la intención es
cubrir los caminos de código, no medir precisión sobre un corpus grande.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

# (pdf de origen, páginas a rasterizar) — pocas páginas, OCR real es lento
SELECCION = [
    ("c1.pdf", [0, 1, 2]),
    ("c7.pdf", [0, 1, 2]),
]

DPI = 200

origen_dir = Path(__file__).parent / "pdfs_de_prueba"
destino_dir = Path(__file__).parent / "pdfs_escaneados"
destino_dir.mkdir(exist_ok=True)


def rasterizar(ruta_origen: Path, paginas: list[int], ruta_destino: Path) -> None:
    """Reconstruye un PDF con las páginas dadas como imagen pura (sin texto)."""
    doc_origen = pymupdf.open(str(ruta_origen))
    doc_destino = pymupdf.open()

    zoom = DPI / 72.0
    matriz = pymupdf.Matrix(zoom, zoom)

    for num_pagina in paginas:
        if num_pagina >= len(doc_origen):
            continue
        pixmap = doc_origen[num_pagina].get_pixmap(matrix=matriz, alpha=False)
        pagina_nueva = doc_destino.new_page(
            width=pixmap.width * 72.0 / DPI,
            height=pixmap.height * 72.0 / DPI,
        )
        pagina_nueva.insert_image(pagina_nueva.rect, pixmap=pixmap)

    doc_destino.save(str(ruta_destino))
    doc_destino.close()
    doc_origen.close()


def main() -> None:
    for nombre, paginas in SELECCION:
        ruta_origen = origen_dir / nombre
        if not ruta_origen.exists():
            print(f"  ! No existe {nombre}, se omite")
            continue

        ruta_destino = destino_dir / f"{ruta_origen.stem}_escaneado.pdf"
        rasterizar(ruta_origen, paginas, ruta_destino)

        # Verificar que efectivamente perdió la capa de texto
        doc = pymupdf.open(str(ruta_destino))
        con_texto = sum(1 for pagina in doc if pagina.get_text().strip())
        total = len(doc)
        doc.close()

        estado = "OK" if con_texto == 0 else f"ATENCION: {con_texto} paginas conservan texto"
        print(f"  {ruta_destino.name}: {total} paginas, {estado}")

    print(f"\nCorpus escaneado en: {destino_dir}")


if __name__ == "__main__":
    main()
