#!/usr/bin/env python
"""Test script for Capa 3 (Specialized OCR) with test PDFs."""

import json
import sys
from pathlib import Path
from datetime import datetime

# Handle Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ocr_engine.triage import procesar_triage
from ocr_engine.segmentation import segmentar_documento
from ocr_engine.ocr_specialized import enrutar_bloque
from ocr_engine.models import Documento, Origen

import pymupdf as fitz
import cv2
import numpy as np

test_pdf_dir = Path(__file__).parent / "pdfs_de_prueba"
output_dir = Path(__file__).parent / "resultados_capa3"
output_dir.mkdir(exist_ok=True)

pdf_files = sorted(test_pdf_dir.glob("*.pdf"))

for pdf_file in pdf_files:
    print(f"\nProcesando: {pdf_file.name}")
    try:
        # Capa 1: Triage
        resultados_triage, zonas = procesar_triage(str(pdf_file))

        # Create Documento object
        documento = Documento(
            titulo=pdf_file.stem,
            origen=Origen.NATIVO_DIGITAL,
            idioma_original="es",
            total_paginas=len(resultados_triage),
            version_pipeline="0.2",
            zonas_dpi=zonas,
        )

        # Capa 2: Segmentation
        bloques = segmentar_documento(
            documento, str(pdf_file), resultados_triage
        )

        # Capa 3: Specialized OCR
        doc = fitz.open(str(pdf_file))
        resultados_ocr = []

        for pagina_idx, triage_result in enumerate(resultados_triage):
            # Render page to image
            page = doc[pagina_idx]
            zoom = (triage_result.dpi_objetivo / 72.0)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )

            # Convert to RGB
            if img_data.shape[2] == 3:
                imagen_pagina = cv2.cvtColor(img_data, cv2.COLOR_BGR2RGB)
            else:
                imagen_pagina = img_data[:, :, 0]

            # Process bloques in this page
            bloques_pagina = [b for b in bloques if b.pagina == pagina_idx]

            for bloque in bloques_pagina:
                try:
                    resultado_ocr = enrutar_bloque(
                        bloque, imagen_pagina, triage_result.dpi_objetivo
                    )
                    resultados_ocr.append({
                        "bloque_id": str(resultado_ocr.id),
                        "contenido": resultado_ocr.contenido[:200],
                        "confianza_global": resultado_ocr.confianza_global,
                        "micro_segmentos": len(resultado_ocr.micro_segmentos),
                        "requiere_escalacion": resultado_ocr.requiere_escalacion,
                    })
                except Exception as e:
                    print(f"    Error en bloque: {e}")
                    continue

        doc.close()

        # Save results
        output_file = output_dir / f"{pdf_file.stem}_ocr.json"
        result_dict = {
            "pdf": pdf_file.name,
            "fecha": datetime.now().isoformat(),
            "total_bloques_procesados": len(resultados_ocr),
            "ocr_results": resultados_ocr,
            "estadisticas": {
                "bloques_alta_confianza": len([r for r in resultados_ocr if r["confianza_global"] > 0.8]),
                "bloques_baja_confianza": len([r for r in resultados_ocr if r["confianza_global"] < 0.6]),
                "bloques_escalados": len([r for r in resultados_ocr if r["requiere_escalacion"]]),
            }
        }

        with open(output_file, "w") as f:
            json.dump(result_dict, f, indent=2, default=str)

        print(f"  ✓ OCR completado")
        print(f"  - Bloques procesados: {len(resultados_ocr)}")
        print(f"  - Alta confianza: {result_dict['estadisticas']['bloques_alta_confianza']}")
        print(f"  - Requieren escalación: {result_dict['estadisticas']['bloques_escalados']}")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()

print(f"\n✓ Resultados guardados en: {output_dir}")
