#!/usr/bin/env python
"""Test script for Capa 2 (Segmentation) with test PDFs."""

import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime

from ocr_engine.triage import procesar_triage
from ocr_engine.segmentation import segmentar_documento
from ocr_engine.models import Documento, Origen

test_pdf_dir = Path(__file__).parent / "pdfs_de_prueba"
output_dir = Path(__file__).parent / "resultados_capa2"
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
            version_pipeline="0.1",
            zonas_dpi=zonas,
        )

        # Capa 2: Segmentation
        bloques = segmentar_documento(
            documento, str(pdf_file), resultados_triage
        )

        # Save results
        output_file = output_dir / f"{pdf_file.stem}_segmentacion.json"
        result_dict = {
            "pdf": pdf_file.name,
            "documento": documento.model_dump(),
            "total_bloques": len(bloques),
            "bloques": [
                {
                    "id": str(b.id),
                    "pagina": b.pagina,
                    "tipo": b.tipo.value,
                    "bbox": b.layout.bbox,
                    "orden_lectura": b.layout.orden_lectura,
                    "origen_contenido": b.origen_contenido.value,
                    "confianza_layout": b.layout.confianza_layout,
                    "texto_preview": b.contenido.texto_plano[:100]
                    if b.contenido.texto_plano
                    else None,
                }
                for b in bloques
            ],
        }

        with open(output_file, "w") as f:
            json.dump(result_dict, f, indent=2, default=str)

        print(f"  ✓ Segmentación completada")
        print(f"  - Total bloques: {len(bloques)}")

        # Count by type
        tipos = {}
        for b in bloques:
            tipo_name = b.tipo.value
            tipos[tipo_name] = tipos.get(tipo_name, 0) + 1

        for tipo, count in sorted(tipos.items()):
            print(f"    - {tipo}: {count}")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback

        traceback.print_exc()

print(f"\n✓ Resultados guardados en: {output_dir}")
