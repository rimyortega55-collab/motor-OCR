"""Extrae recortes de las regiones matematicas de los 11 PDF de prueba, para
anotarlas como ground truth de evaluacion del modelo de OCR matematico.

Corre el pipeline completo (`Pipeline().ejecutar`) sobre cada PDF, se queda con
los bloques `formula_display`/`formula_inline`, recorta esa region de la
pagina renderizada segun su bbox normalizado, y guarda un manifiesto con la
transcripcion que el motor actual (pix2tex) ya produjo para cada una -para
poder comparar despues- y un campo `latex_referencia` vacio a completar.

Uso:
    python entrenamiento/extraer_muestra_evaluacion.py [c1 c2 ...]

Sin argumentos corre los 11 PDF de `pruebas/pdfs_de_prueba/`.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from motor_ocr.layout.bbox import desnormalizar_bbox
from motor_ocr.modelos import TipoBloque
from motor_ocr.pipeline import Pipeline

RAIZ_PRUEBAS = Path(__file__).parent.parent / "pruebas"
DIR_PDFS = RAIZ_PRUEBAS / "pdfs_de_prueba"
DIR_SALIDA = Path(__file__).parent / "evaluacion_real"
DPI_RECORTE = 300

TIPOS_MATEMATICOS = {TipoBloque.FORMULA_DISPLAY, TipoBloque.FORMULA_INLINE}


def _pixmap_a_pil(pix: fitz.Pixmap) -> Image.Image:
    return Image.open(io.BytesIO(pix.tobytes("png")))


def extraer_uno(ruta_pdf: Path, manifiesto: list[dict]) -> None:
    nombre = ruta_pdf.stem
    documento, bloques = Pipeline().ejecutar(str(ruta_pdf))
    bloques_math = [b for b in bloques if b.tipo in TIPOS_MATEMATICOS]
    if not bloques_math:
        print(f"[{nombre}] sin bloques matematicos detectados")
        return

    dir_pdf = DIR_SALIDA / nombre
    dir_pdf.mkdir(parents=True, exist_ok=True)
    doc_fitz = fitz.open(str(ruta_pdf))

    cache_paginas: dict[int, Image.Image] = {}
    extraidos = 0
    for i, b in enumerate(bloques_math):
        if b.pagina not in cache_paginas:
            page = doc_fitz[b.pagina]
            zoom = DPI_RECORTE / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            cache_paginas[b.pagina] = _pixmap_a_pil(pix)
        imagen_pagina = cache_paginas[b.pagina]
        x0, y0, x1, y1 = desnormalizar_bbox(b.layout.bbox, imagen_pagina.size)
        if x1 <= x0 or y1 <= y0:
            continue

        nombre_archivo = f"{i:03d}.png"
        imagen_pagina.crop((x0, y0, x1, y1)).save(str(dir_pdf / nombre_archivo))
        extraidos += 1
        manifiesto.append({
            "pdf": nombre,
            "archivo": f"{nombre}/{nombre_archivo}",
            "pagina": b.pagina,
            "tipo": b.tipo.value,
            "bbox": list(b.layout.bbox),
            "prediccion_actual": b.contenido.latex or b.contenido.texto_plano or "",
            "latex_referencia": None,
        })
    doc_fitz.close()
    print(f"[{nombre}] {extraidos}/{len(bloques_math)} bloques matematicos extraidos")


def _cargar_manifiesto_previo(nombres_a_reemplazar: set[str]) -> list[dict]:
    """Carga entradas de un manifiesto.jsonl previo, descartando las de los
    PDF que se van a (re)procesar en esta corrida -- asi se puede correr el
    resto de los PDF en otro entorno (p.ej. Colab) y combinar resultados sin
    duplicar ni perder lo ya extraido localmente."""
    ruta_previa = DIR_SALIDA / "manifiesto.jsonl"
    if not ruta_previa.exists():
        return []
    filas = []
    with open(ruta_previa, encoding="utf-8") as fh:
        for linea in fh:
            fila = json.loads(linea)
            if fila["pdf"] not in nombres_a_reemplazar:
                filas.append(fila)
    return filas


def main() -> None:
    pedidos = sys.argv[1:]
    if pedidos:
        pdfs = [DIR_PDFS / f"{p}.pdf" for p in pedidos]
    else:
        pdfs = sorted(DIR_PDFS.glob("c*.pdf"), key=lambda p: int(p.stem[1:]))

    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    manifiesto = _cargar_manifiesto_previo({p.stem for p in pdfs})
    for ruta in pdfs:
        try:
            extraer_uno(ruta, manifiesto)
        except Exception as e:
            print(f"[{ruta.stem}] ERROR: {type(e).__name__}: {e}")
        finally:
            # Se reescribe tras cada PDF (no solo al final) para no perder lo
            # ya procesado si la corrida se corta a mitad de camino.
            with open(DIR_SALIDA / "manifiesto.jsonl", "w", encoding="utf-8") as fh:
                for fila in manifiesto:
                    fh.write(json.dumps(fila, ensure_ascii=False) + "\n")

    print(f"\nTotal: {len(manifiesto)} recortes -> {DIR_SALIDA}")


if __name__ == "__main__":
    main()
