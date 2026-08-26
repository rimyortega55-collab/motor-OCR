#!/usr/bin/env python
"""Test script for Capa 4 (Deterministic Correction) with test PDFs."""

import json
import sys
from pathlib import Path
from datetime import datetime

# Handle Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from motor_ocr.triage import procesar_triage
from motor_ocr.layout import segmentar_documento
from motor_ocr.reconocimiento import enrutar_bloque
from motor_ocr.correccion import corregir_documento
from motor_ocr.modelos import Documento, Origen

import pymupdf as fitz
import cv2
import numpy as np

test_pdf_dir = Path(__file__).parent / "pdfs_de_prueba"
output_dir = Path(__file__).parent / "resultados_capa4"
output_dir.mkdir(exist_ok=True)

pdf_files = sorted(test_pdf_dir.glob("*.pdf"))

estadisticas_globales = {
    "bloques_procesados": 0,
    "bloques_con_reparaciones": 0,
    "reparaciones_totales": 0,
    "inconsistencias_detectadas": 0,
    "bloques_escalados": 0,
}

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
            version_pipeline="0.3",
            zonas_dpi=zonas,
        )

        # Capa 2: Segmentation
        bloques = segmentar_documento(
            documento, str(pdf_file), resultados_triage
        )

        # Capa 3: Specialized OCR (simplified - use native text for test PDFs)
        # In real scenario, this would run OCR on scanned content

        # Capa 4: Deterministic Correction
        resultado_correccion = corregir_documento(documento, bloques)

        # Recolectar estadísticas
        bloques_con_repairs = [
            b for b in resultado_correccion.bloques_corregidos
            if b.reparaciones_aplicadas
        ]

        total_repairs = sum(
            len(b.reparaciones_aplicadas)
            for b in resultado_correccion.bloques_corregidos
        )

        estadisticas_globales["bloques_procesados"] += len(bloques)
        estadisticas_globales["bloques_con_reparaciones"] += len(bloques_con_repairs)
        estadisticas_globales["reparaciones_totales"] += total_repairs
        estadisticas_globales["inconsistencias_detectadas"] += len(
            resultado_correccion.inconsistencias_detectadas
        )
        estadisticas_globales["bloques_escalados"] += len(
            resultado_correccion.bloques_pendientes_escalacion
        )

        # Save results
        output_file = output_dir / f"{pdf_file.stem}_correccion.json"

        result_dict = {
            "pdf": pdf_file.name,
            "fecha": datetime.now().isoformat(),
            "documento": documento.model_dump(),
            "estadisticas": {
                "bloques_totales": len(bloques),
                "bloques_corregidos": len(bloques_con_repairs),
                "reparaciones_aplicadas": total_repairs,
                "inconsistencias": len(resultado_correccion.inconsistencias_detectadas),
                "bloques_escalados": len(resultado_correccion.bloques_pendientes_escalacion),
            },
            "muestras_correcciones": [
                {
                    "bloque_id": str(b.id),
                    "reparaciones": b.reparaciones_aplicadas[:5],  # Primeras 5
                    "total_reparaciones": len(b.reparaciones_aplicadas),
                }
                for b in resultado_correccion.bloques_corregidos[:10]
            ],
            "inconsistencias": [
                {
                    "tipo": inc.tipo,
                    "detalle": inc.detalle,
                    "ubicacion_pagina": inc.ubicacion_pagina,
                }
                for inc in resultado_correccion.inconsistencias_detectadas[:5]
            ],
        }

        with open(output_file, "w") as f:
            json.dump(result_dict, f, indent=2, default=str)

        print(f"  Correccion completada")
        print(f"  - Bloques procesados: {len(bloques)}")
        print(f"  - Bloques con reparaciones: {len(bloques_con_repairs)}")
        print(f"  - Reparaciones totales: {total_repairs}")
        print(f"  - Inconsistencias detectadas: {len(resultado_correccion.inconsistencias_detectadas)}")
        print(f"  - Bloques para escalacion: {len(resultado_correccion.bloques_pendientes_escalacion)}")

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

print(f"\n" + "=" * 50)
print(f"ESTADISTICAS GLOBALES (Capa 4)")
print(f"=" * 50)
print(f"Bloques procesados: {estadisticas_globales['bloques_procesados']}")
print(f"Bloques con reparaciones: {estadisticas_globales['bloques_con_reparaciones']}")
print(f"Reparaciones totales: {estadisticas_globales['reparaciones_totales']}")
print(f"Inconsistencias detectadas: {estadisticas_globales['inconsistencias_detectadas']}")
print(f"Bloques para escalacion: {estadisticas_globales['bloques_escalados']}")

print(f"\nResultados guardados en: {output_dir}")
