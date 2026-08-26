#!/usr/bin/env python
"""Test de Capa 3 (OCR especializado) sobre PDFs escaneados.

Complementa a `test_capa3.py`, que sólo ejercita PDFs nativo-digitales y por eso
nunca llega a los motores OCR: todo bloque con origen TEXTO_NATIVO corta temprano
en `enrutar_bloque` con una confianza fija de 0.95. Acá las páginas no tienen capa
de texto, así que el enrutador cae en las ramas reales (easyocr / doctr / pix2tex)
y la confianza que se reporta es la que calculan los engines.

Requiere haber corrido antes `generar_pdfs_escaneados.py`.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Consola de Windows: forzar UTF-8 para los acentos.
# line_buffering es lo que hace visible el progreso cuando la salida se redirige a
# un archivo: envolver sys.stdout en un TextIOWrapper con write_through no alcanza,
# porque el BufferedWriter de abajo sigue acumulando.
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from motor_ocr.triage import procesar_triage
from motor_ocr.layout import segmentar_documento
from motor_ocr.reconocimiento import enrutar_bloque
from motor_ocr.modelos import Documento, Origen, OrigenContenido

import pymupdf
import cv2
import numpy as np

pdf_dir = Path(__file__).parent / "pdfs_escaneados"
output_dir = Path(__file__).parent / "resultados_capa3_escaneado"
output_dir.mkdir(exist_ok=True)

pdf_files = sorted(pdf_dir.glob("*.pdf"))

if not pdf_files:
    print("No hay PDFs escaneados. Corré primero: python generar_pdfs_escaneados.py")
    raise SystemExit(1)

totales = Counter()

for pdf_file in pdf_files:
    print(f"\nProcesando: {pdf_file.name}")
    try:
        resultados_triage, zonas = procesar_triage(str(pdf_file))

        origenes = Counter(r.origen for r in resultados_triage)
        print(f"  - Origen detectado: {dict(origenes)}")

        documento = Documento(
            titulo=pdf_file.stem,
            origen=Origen.ESCANEADO,
            idioma_original="es",
            total_paginas=len(resultados_triage),
            version_pipeline="0.3-escaneado",
            zonas_dpi=zonas,
        )

        bloques = segmentar_documento(documento, str(pdf_file), resultados_triage)

        origen_bloques = Counter(b.origen_contenido for b in bloques)
        print(f"  - Bloques: {len(bloques)} | origen_contenido: {dict(origen_bloques)}")

        doc = pymupdf.open(str(pdf_file))
        resultados_ocr = []

        for pagina_idx, triage_result in enumerate(resultados_triage):
            page = doc[pagina_idx]
            zoom = triage_result.dpi_objetivo / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if img_data.shape[2] == 3:
                imagen_pagina = cv2.cvtColor(img_data, cv2.COLOR_BGR2RGB)
            else:
                imagen_pagina = img_data[:, :, 0]

            for bloque in [b for b in bloques if b.pagina == pagina_idx]:
                try:
                    r = enrutar_bloque(bloque, imagen_pagina, triage_result.dpi_objetivo)
                    resultados_ocr.append({
                        "bloque_id": str(r.id),
                        "tipo": str(bloque.tipo),
                        "origen_contenido": str(bloque.origen_contenido),
                        "contenido": r.contenido[:200],
                        "confianza_global": r.confianza_global,
                        "micro_segmentos": len(r.micro_segmentos),
                        "requiere_escalacion": r.requiere_escalacion,
                    })
                except Exception as e:
                    print(f"    Error en bloque: {e}")
                    continue

        doc.close()

        # Un bloque pasó por OCR real si su origen no es texto nativo
        via_ocr = [
            r for r in resultados_ocr
            if r["origen_contenido"] != str(OrigenContenido.TEXTO_NATIVO)
        ]
        escalados = [r for r in resultados_ocr if r["requiere_escalacion"]]
        confianzas = [r["confianza_global"] for r in via_ocr]

        result_dict = {
            "pdf": pdf_file.name,
            "fecha": datetime.now().isoformat(),
            "total_bloques_procesados": len(resultados_ocr),
            "bloques_via_ocr_real": len(via_ocr),
            "ocr_results": resultados_ocr,
            "estadisticas": {
                "confianza_min": min(confianzas) if confianzas else None,
                "confianza_max": max(confianzas) if confianzas else None,
                "confianza_media": (sum(confianzas) / len(confianzas)) if confianzas else None,
                "bloques_escalados": len(escalados),
            },
        }

        salida = output_dir / f"{pdf_file.stem}_ocr.json"
        with open(salida, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, indent=2, ensure_ascii=False, default=str)

        totales["bloques"] += len(resultados_ocr)
        totales["via_ocr"] += len(via_ocr)
        totales["escalados"] += len(escalados)

        print(f"  OCR completado")
        print(f"  - Bloques procesados: {len(resultados_ocr)}")
        print(f"  - Bloques vía OCR real: {len(via_ocr)}")
        if confianzas:
            media = sum(confianzas) / len(confianzas)
            print(f"  - Confianza min/media/max: "
                  f"{min(confianzas):.3f} / {media:.3f} / {max(confianzas):.3f}")
        print(f"  - Requieren escalación: {len(escalados)}")

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 50)
print("RESUMEN (Capa 3 sobre escaneados)")
print("=" * 50)
print(f"Bloques procesados: {totales['bloques']}")
print(f"Bloques vía OCR real: {totales['via_ocr']}")
print(f"Bloques que requieren escalación: {totales['escalados']}")
if totales["via_ocr"] == 0:
    print("\nATENCION: ningun bloque paso por OCR real; el atajo de texto nativo "
          "sigue capturando todo y la Capa 3 continua sin cobertura.")
print(f"\nResultados guardados en: {output_dir}")
