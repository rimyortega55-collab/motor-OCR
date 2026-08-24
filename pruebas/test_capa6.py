#!/usr/bin/env python
"""Test script for Capa 6 (Human Review Interface) - Simulated workflow."""

import json
import sys
from pathlib import Path
from datetime import datetime
from uuid import uuid4

# Handle Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from ocr_engine.triage import procesar_triage
from ocr_engine.segmentation import segmentar_documento
from ocr_engine.correction import corregir_documento
from ocr_engine.revision import (
    GestorDecisiones,
    DecisionRevision,
    AnalizadorFeedback
)
from ocr_engine.models import Documento, Origen

test_pdf_dir = Path(__file__).parent / "pdfs_de_prueba"
output_dir = Path(__file__).parent / "resultados_capa6"
output_dir.mkdir(exist_ok=True)

# Para demostración, usaremos c7.pdf (tiene 1 inconsistencia)
pdf_file = test_pdf_dir / "c7.pdf"

print(f"\nProcesando: {pdf_file.name}")
print("=" * 60)

try:
    # Capas 1-4
    resultados_triage, zonas = procesar_triage(str(pdf_file))

    documento = Documento(
        titulo=pdf_file.stem,
        origen=Origen.NATIVO_DIGITAL,
        idioma_original="es",
        total_paginas=len(resultados_triage),
        version_pipeline="0.5",
        zonas_dpi=zonas,
    )

    bloques = segmentar_documento(
        documento, str(pdf_file), resultados_triage
    )

    resultado_correccion = corregir_documento(documento, bloques)

    # Capa 6: Simular decisiones de revisión
    print(f"\n[SIMULACION DE REVISION HUMANA]")
    print(f"Total de bloques: {len(bloques)}")
    print(f"Bloques con baja confianza: {len([b for b in bloques if b.layout.confianza_layout < 0.7])}")
    print(f"Inconsistencias detectadas: {len(resultado_correccion.inconsistencias_detectadas)}")

    # Crear gestor de decisiones
    archivo_decisiones = output_dir / f"{pdf_file.stem}_decisiones.jsonl"
    gestor = GestorDecisiones(str(archivo_decisiones))

    # Simular decisiones humanas (sin interfaz interactiva)
    print(f"\n[GENERANDO DECISIONES SIMULADAS]")

    decisiones_simuladas = []

    # 1. Bloque aleatorio: aceptar
    bloque_test1 = bloques[0] if bloques else None
    if bloque_test1:
        decision1 = DecisionRevision(
            bloque_id=bloque_test1.id,
            documento_id=documento.documento_id,
            pagina=bloque_test1.pagina,
            tipo_bloque=bloque_test1.tipo.value,
            decision="aceptar",
            contenido_original="Springer Undergraduate Mathematics Series",
            contenido_final="Springer Undergraduate Mathematics Series",
            confianza_engine=0.95,
            confianza_usuario=0.95,
            comentarios="Aceptado como está",
            revisor="usuario_test"
        )
        gestor.registrar_decision(decision1)
        decisiones_simuladas.append(decision1)
        print(f"  + Decisión 1: {bloque_test1.tipo.value} - ACEPTADO")

    # 2. Bloque con fórmula: editar
    bloques_formula = [b for b in bloques if 'formula' in b.tipo.value]
    if bloques_formula:
        bloque_test2 = bloques_formula[0]
        decision2 = DecisionRevision(
            bloque_id=bloque_test2.id,
            documento_id=documento.documento_id,
            pagina=bloque_test2.pagina,
            tipo_bloque=bloque_test2.tipo.value,
            decision="editar",
            contenido_original="x^2 + y^2 = z^2",
            contenido_final="x^{2} + y^{2} = z^{2}",
            confianza_engine=0.72,
            confianza_usuario=0.88,
            comentarios="Corregido formato LaTeX de exponentes",
            revisor="usuario_test"
        )
        gestor.registrar_decision(decision2)
        decisiones_simuladas.append(decision2)
        print(f"  + Decisión 2: {bloque_test2.tipo.value} - EDITADO")

    # 3. Bloque para escalar
    if len(bloques) > 2:
        bloque_test3 = bloques[2]
        decision3 = DecisionRevision(
            bloque_id=bloque_test3.id,
            documento_id=documento.documento_id,
            pagina=bloque_test3.pagina,
            tipo_bloque=bloque_test3.tipo.value,
            decision="escalar",
            contenido_original="Contenido ambiguo",
            contenido_final="Contenido ambiguo",
            confianza_engine=0.45,
            confianza_usuario=0.0,
            comentarios="No se puede determinar con certeza",
            revisor="usuario_test"
        )
        gestor.registrar_decision(decision3)
        decisiones_simuladas.append(decision3)
        print(f"  + Decisión 3: {bloque_test3.tipo.value} - ESCALADO")

    # Análisis de decisiones
    print(f"\n[ANALISIS DE DECISIONES]")

    estadisticas = gestor.obtener_estadisticas(str(documento.documento_id))
    print(f"  Total revisados: {estadisticas['total']}")
    print(f"  Por tipo de decisión: {estadisticas['por_decision']}")
    print(f"  Tasa de cambio: {estadisticas['tasa_cambio']:.1f}%")
    print(f"  Confianza usuario promedio: {estadisticas['confianza_promedio_usuario']:.2f}")

    patrones = gestor.obtener_patrones()
    if patrones:
        print(f"\n  Patrones detectados:")
        if patrones.get('tipos_rechazados_frecuentemente'):
            print(f"    - Tipos rechazados: {patrones['tipos_rechazados_frecuentemente']}")
        if patrones.get('tipos_escalados_frecuentemente'):
            print(f"    - Tipos escalados: {patrones['tipos_escalados_frecuentemente']}")

    # Análisis de feedback para recomendaciones
    print(f"\n[RECOMENDACIONES DE AJUSTE]")

    analizador = AnalizadorFeedback(gestor._decisiones_cache)
    recomendaciones = analizador.generar_recomendaciones()

    if recomendaciones:
        for i, rec in enumerate(recomendaciones, 1):
            print(f"  {i}. {rec}")
    else:
        print("  No hay recomendaciones de cambio")

    resumen_mejoras = analizador.obtener_resumen_mejoras()
    print(f"\n  Potencial de automatización: {resumen_mejoras['potencial_automatizacion']:.1f}%")

    # Guardar resultados
    output_file = output_dir / f"{pdf_file.stem}_revision_results.json"

    result_dict = {
        "pdf": pdf_file.name,
        "fecha": datetime.now().isoformat(),
        "documento": documento.model_dump(),
        "estadisticas_revision": estadisticas,
        "patrones_detectados": patrones,
        "recomendaciones": [
            {
                "tipo_bloque": rec.tipo_bloque,
                "capa": rec.capa,
                "umbral_actual": rec.umbral_actual,
                "umbral_recomendado": rec.umbral_recomendado,
                "razon": rec.razon,
                "impacto": rec.impacto_esperado
            }
            for rec in recomendaciones
        ],
        "resumen_mejoras": {
            "potencial_automatizacion": resumen_mejoras['potencial_automatizacion'],
            "tipos_problematicos": [
                {"tipo": t, "tasa_problema": rate}
                for t, rate in resumen_mejoras['tipos_problematicos']
            ]
        }
    }

    with open(output_file, "w") as f:
        json.dump(result_dict, f, indent=2, default=str)

    print(f"\n[COMPLETADO]")
    print(f"  Decisiones guardadas en: {archivo_decisiones}")
    print(f"  Resultados guardados en: {output_file}")

    # Exportar a CSV
    csv_file = output_dir / f"{pdf_file.stem}_decisiones.csv"
    gestor.exportar_csv(csv_file)
    print(f"  CSV exportado en: {csv_file}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*60}\n")
