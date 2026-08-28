"""Extrae recortes de las regiones matematicas de los 11 PDF de prueba, para
anotarlas como ground truth de evaluacion del modelo de OCR matematico.

Corre Capas 1-2 (triage + segmentacion) sobre cada PDF -sin pasar por el
pipeline completo, que ademas correria pix2tex una vez por bloque sin que lo
necesitemos aca- y arma un candidato de recorte por cada region que la propia
Capa 3 le pasaria a pix2tex en produccion:

- Bloques `formula_display`: el bbox del bloque completo (asi es como los
  procesa `_procesar_formula_display` en enrutador.py: sin sub-segmentar).
- Bloques nativo-digital con formulas inline (parrafo/teorema/lema/...): el
  bbox de cada tramo `formula` en `bloque.segmentos_capa2`, que es el mismo
  bbox exacto por span que usa `_procesar_bloque_nativo_con_formulas` en
  enrutador.py -no el bbox del bloque/parrafo entero, que mezclaria prosa.

Los bloques escaneados (sin `segmentos_capa2`) quedan fuera de este muestreo:
el proyecto prioriza LaTeX antes que abordar esa via (ver
docs/direccion del proyecto).

Se llama a `ocr_formula` directamente sobre cada recorte -la misma funcion
que usa el pipeline en Capa 3- para que la prediccion del manifiesto sea
exactamente la que produciria una corrida real, sin pasar por la
recomposicion de texto+formula pensada para el documento final.

Uso:
    python entrenamiento/extraer_muestra_evaluacion.py [c1 c2 ...]

Sin argumentos corre los 11 PDF de `pruebas/pdfs_de_prueba/`.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf as fitz
from PIL import Image

from motor_ocr.layout import segmentar_documento
from motor_ocr.layout.bbox import desnormalizar_bbox
from motor_ocr.modelos import Documento, Origen, OrigenContenido, TipoBloque
from motor_ocr.reconocimiento.engines.pix2tex_engine import ocr_formula
from motor_ocr.triage import procesar_triage

RAIZ_PRUEBAS = Path(__file__).parent.parent / "pruebas"
DIR_PDFS = RAIZ_PRUEBAS / "pdfs_de_prueba"
DIR_SALIDA = Path(__file__).parent / "evaluacion_real"
DPI_RECORTE = 300


def _candidatos_de_bloque(bloque) -> list[tuple[str, tuple[float, float, float, float]]]:
    """[(tipo, bbox_normalizado), ...] de las regiones que pix2tex vería en produccion."""
    if bloque.tipo == TipoBloque.FORMULA_DISPLAY:
        return [("formula_display", bloque.layout.bbox)]

    if bloque.origen_contenido == OrigenContenido.TEXTO_NATIVO and bloque.segmentos_capa2:
        return [
            ("formula_inline", seg.bbox)
            for seg in bloque.segmentos_capa2
            if seg.tipo == "formula" and seg.bbox is not None
        ]

    return []


def extraer_uno(ruta_pdf: Path, manifiesto: list[dict]) -> None:
    nombre = ruta_pdf.stem

    resultados_triage, zonas = procesar_triage(str(ruta_pdf))
    documento = Documento(
        titulo=ruta_pdf.name,
        origen=Origen.NATIVO_DIGITAL,
        idioma_original="es",
        total_paginas=len(resultados_triage),
        version_pipeline="0.1.0",
        zonas_dpi=zonas,
    )
    bloques = segmentar_documento(documento, str(ruta_pdf), resultados_triage)

    candidatos = [
        (bloque.pagina, tipo, bbox)
        for bloque in bloques
        for tipo, bbox in _candidatos_de_bloque(bloque)
    ]
    if not candidatos:
        print(f"[{nombre}] sin bloques matematicos detectados")
        return

    dir_pdf = DIR_SALIDA / nombre
    dir_pdf.mkdir(parents=True, exist_ok=True)
    doc_fitz = fitz.open(str(ruta_pdf))

    cache_paginas: dict[int, Image.Image] = {}
    extraidos = 0
    for i, (pagina, tipo, bbox) in enumerate(candidatos):
        if pagina not in cache_paginas:
            page = doc_fitz[pagina]
            zoom = DPI_RECORTE / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            cache_paginas[pagina] = Image.open(io.BytesIO(pix.tobytes("png")))
        imagen_pagina = cache_paginas[pagina]

        x0, y0, x1, y1 = desnormalizar_bbox(bbox, imagen_pagina.size)
        if x1 <= x0 or y1 <= y0:
            continue

        recorte_pil = imagen_pagina.crop((x0, y0, x1, y1))
        latex, confianza = ocr_formula(np.array(recorte_pil))

        nombre_archivo = f"{i:03d}.png"
        recorte_pil.save(str(dir_pdf / nombre_archivo))
        extraidos += 1
        manifiesto.append({
            "pdf": nombre,
            "archivo": f"{nombre}/{nombre_archivo}",
            "pagina": pagina,
            "tipo": tipo,
            "bbox": list(bbox),
            "prediccion_actual": latex,
            "confianza_engine": confianza,
            "latex_referencia": None,
        })
    doc_fitz.close()
    print(f"[{nombre}] {extraidos}/{len(candidatos)} bloques matematicos extraidos")


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
