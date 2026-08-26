#!/usr/bin/env python
"""Test script for Capa 5 (LLM Escalation) with test PDFs."""

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
from motor_ocr.correccion import corregir_documento
from motor_ocr.escalacion import procesar_escalaciones, obtener_estadisticas
from motor_ocr.modelos import Documento, Origen

import pymupdf as fitz
import cv2
import numpy as np

test_pdf_dir = Path(__file__).parent / "pdfs_de_prueba"
output_dir = Path(__file__).parent / "resultados_capa5"
output_dir.mkdir(exist_ok=True)

pdf_files = sorted(test_pdf_dir.glob("*.pdf"))

estadisticas_globales = {
    "pdfs_procesados": 0,
    "bloques_totales": 0,
    "inconsistencias_detectadas": 0,
    "escalaciones_realizadas": 0,
    "bloques_revision_humana": 0,
    "costo_total_usd": 0.0,
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
            version_pipeline="0.4",
            zonas_dpi=zonas,
        )

        # Capa 2: Segmentation
        bloques = segmentar_documento(
            documento, str(pdf_file), resultados_triage
        )

        # Capa 4: Correction
        resultado_correccion = corregir_documento(documento, bloques)

        # Capa 5: Escalation
        resultado_escalacion = procesar_escalaciones(
            documento=documento,
            bloques=bloques,
            resultado_correccion=resultado_correccion
        )

        # Recolectar estadísticas
        total_escalaciones = (
            len(resultado_escalacion["escalaciones_micro_segmentos"]) +
            len(resultado_escalacion["escalaciones_inconsistencias"])
        )

        estadisticas_globales["pdfs_procesados"] += 1
        estadisticas_globales["bloques_totales"] += len(bloques)
        estadisticas_globales["inconsistencias_detectadas"] += len(
            resultado_correccion.inconsistencias_detectadas
        )
        estadisticas_globales["escalaciones_realizadas"] += total_escalaciones
        estadisticas_globales["bloques_revision_humana"] += len(
            resultado_escalacion["bloques_requieren_revision_humana"]
        )

        # Save results
        output_file = output_dir / f"{pdf_file.stem}_escalacion.json"

        result_dict = {
            "pdf": pdf_file.name,
            "fecha": datetime.now().isoformat(),
            "documento": documento.model_dump(),
            "estadisticas": {
                "bloques_totales": len(bloques),
                "inconsistencias": len(resultado_correccion.inconsistencias_detectadas),
                "escalaciones_micro": len(resultado_escalacion["escalaciones_micro_segmentos"]),
                "escalaciones_inconsistencias": len(resultado_escalacion["escalaciones_inconsistencias"]),
                "bloques_revision_humana": len(resultado_escalacion["bloques_requieren_revision_humana"]),
            },
            "inconsistencias_detectadas": [
                {
                    "tipo": inc.tipo,
                    "detalle": inc.detalle,
                    "ubicacion_pagina": inc.ubicacion_pagina,
                }
                for inc in resultado_correccion.inconsistencias_detectadas[:5]
            ],
            "escalaciones": [
                {
                    "tipo_cola": esc.cola_origen,
                    "confianza_llm": esc.confianza_llm,
                    "requiere_revision": esc.requiere_revision_humana,
                    "contenido": esc.contenido_final[:100] if esc.contenido_final else None,
                }
                for esc in resultado_escalacion["escalaciones_inconsistencias"][:3]
            ],
            "costo": resultado_escalacion.get("estadisticas_costo", {}),
        }

        with open(output_file, "w") as f:
            json.dump(result_dict, f, indent=2, default=str)

        print(f"  Escalacion completada")
        print(f"  - Bloques procesados: {len(bloques)}")
        print(f"  - Inconsistencias detectadas: {len(resultado_correccion.inconsistencias_detectadas)}")
        print(f"  - Escalaciones realizadas: {total_escalaciones}")
        print(f"  - Bloques para revision humana: {len(resultado_escalacion['bloques_requieren_revision_humana'])}")

        # Show cost if any
        costo_stats = resultado_escalacion.get("estadisticas_costo", {})
        if costo_stats.get("total_llamadas", 0) > 0:
            print(f"  - Costo estimado: ${costo_stats.get('costo_estimado_usd', 0):.4f}")
            estadisticas_globales["costo_total_usd"] += costo_stats.get('costo_estimado_usd', 0)

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

print(f"\n" + "=" * 50)
print(f"ESTADISTICAS GLOBALES (Capa 5)")
print(f"=" * 50)
print(f"PDFs procesados: {estadisticas_globales['pdfs_procesados']}")
print(f"Bloques totales: {estadisticas_globales['bloques_totales']}")
print(f"Inconsistencias detectadas: {estadisticas_globales['inconsistencias_detectadas']}")
print(f"Escalaciones realizadas: {estadisticas_globales['escalaciones_realizadas']}")
print(f"Bloques para revision humana: {estadisticas_globales['bloques_revision_humana']}")
print(f"Costo total estimado: ${estadisticas_globales['costo_total_usd']:.4f}")

print(f"\nResultados guardados en: {output_dir}")
