#!/usr/bin/env python
"""Test script for Capa 1 (Triage) with test PDFs."""

import json
from pathlib import Path
from motor_ocr.triage import procesar_triage

test_pdf_dir = Path(__file__).parent / "pdfs_de_prueba"
output_dir = Path(__file__).parent / "resultados_capa1"
output_dir.mkdir(exist_ok=True)

pdf_files = sorted(test_pdf_dir.glob("*.pdf"))

for pdf_file in pdf_files:
    print(f"\nProcesando: {pdf_file.name}")
    try:
        resultados, zonas = procesar_triage(str(pdf_file))

        # Save results
        output_file = output_dir / f"{pdf_file.stem}_triage.json"
        result_dict = {
            "pdf": pdf_file.name,
            "total_paginas": len(resultados),
            "paginas": [r.model_dump() for r in resultados],
            "zonas": [z.model_dump() for z in zonas],
        }

        with open(output_file, "w") as f:
            json.dump(result_dict, f, indent=2, default=str)

        print(f"  ✓ Triage completado")
        print(f"  - Total páginas: {len(resultados)}")
        print(f"  - Zonas identificadas: {len(zonas)}")
        for i, zona in enumerate(zonas):
            print(f"    Zona {i}: páginas {zona.paginas}, DPI {zona.dpi}, perfil: {zona.perfil_dominante}")

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()

print(f"\n✓ Resultados guardados en: {output_dir}")
