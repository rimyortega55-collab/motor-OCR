"""API REST con FastAPI para procesamiento OCR completo.

Endpoints:
- POST /procesar — Procesa PDF completo
- GET /documentos/<id> — Obtiene resultado de documento
- GET /bloques/<id> — Detalle de bloque
- POST /revision/<id>/decision — Registra decisión humana
- GET /metricas — Dashboard de métricas
- POST /auto-ajuste — Aplica cambios de umbrales
"""

from __future__ import annotations

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
from uuid import UUID, uuid4
import json

from ocr_engine.triage import procesar_triage
from ocr_engine.segmentation import segmentar_documento
from ocr_engine.correction import corregir_documento
from ocr_engine.revision import GestorDecisiones, DecisionRevision, AnalizadorFeedback
from ocr_engine.models import Documento, Origen
from .ajuste_umbrales import AjustadorUmbrales

# Inicializar FastAPI
app = FastAPI(
    title="OCR Pipeline API",
    description="6-capas + Capa 7 (Web Interface)",
    version="0.7"
)

# Almacenamiento en-memory para demo (en producción usar DB)
documentos_procesados = {}
ajustador = AjustadorUmbrales()
gestor_decisiones = GestorDecisiones()

# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class ResultadoOCR(BaseModel):
    documento_id: str
    titulo: str
    total_paginas: int
    total_bloques: int
    bloques_con_baja_confianza: int
    inconsistencias: int
    necesita_revision: bool

class DecisionUsuario(BaseModel):
    bloque_id: str
    decision: str  # "aceptar", "rechazar", "editar", "escalar"
    contenido_final: str
    comentarios: str = ""
    confianza_usuario: float

class EstadisticasGlobales(BaseModel):
    documentos_procesados: int
    bloques_totales: int
    bloques_revisados: int
    tasa_cambio: float
    confianza_promedio: float
    ajustes_pendientes: int

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Health check."""
    return {
        "status": "ok",
        "version": "0.7",
        "capas": [1, 2, 3, 4, 5, 6, 7],
        "features": ["triage", "segmentacion", "ocr", "correccion", "llm", "revision", "web"]
    }

@app.post("/procesar")
async def procesar_pdf(file: UploadFile = File(...)):
    """Procesa PDF a través de Capas 1-5."""

    try:
        # Guardar archivo temporal
        ruta_temporal = Path(f"/tmp/ocr_{uuid4()}.pdf")
        contenido = await file.read()
        ruta_temporal.write_bytes(contenido)

        # Procesar
        documento_id = str(uuid4())

        resultados_triage, zonas = procesar_triage(str(ruta_temporal))

        documento = Documento(
            titulo=file.filename,
            origen=Origen.NATIVO_DIGITAL,
            idioma_original="es",
            total_paginas=len(resultados_triage),
            version_pipeline="0.7",
            zonas_dpi=zonas,
        )

        bloques = segmentar_documento(documento, str(ruta_temporal), resultados_triage)
        resultado_correccion = corregir_documento(documento, bloques)

        # Guardar resultado
        documentos_procesados[documento_id] = {
            "documento": documento,
            "bloques": bloques,
            "resultado_correccion": resultado_correccion,
            "timestamp": str(datetime.now())
        }

        # Limpiar
        ruta_temporal.unlink()

        return ResultadoOCR(
            documento_id=documento_id,
            titulo=file.filename,
            total_paginas=documento.total_paginas,
            total_bloques=len(bloques),
            bloques_con_baja_confianza=len([b for b in bloques if b.layout.confianza_layout < 0.7]),
            inconsistencias=len(resultado_correccion.inconsistencias_detectadas),
            necesita_revision=len(resultado_correccion.bloques_pendientes_escalacion) > 0
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/documentos/{documento_id}")
async def obtener_documento(documento_id: str):
    """Obtiene resultado de documento procesado."""

    if documento_id not in documentos_procesados:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    doc_info = documentos_procesados[documento_id]

    return {
        "documento_id": documento_id,
        "titulo": doc_info["documento"].titulo,
        "total_bloques": len(doc_info["bloques"]),
        "timestamp": doc_info["timestamp"],
        "resumen": {
            "parrafos": len([b for b in doc_info["bloques"] if b.tipo.value == "parrafo"]),
            "formulas": len([b for b in doc_info["bloques"] if "formula" in b.tipo.value]),
            "inconsistencias": len(doc_info["resultado_correccion"].inconsistencias_detectadas),
        }
    }

@app.post("/revision/{documento_id}/decision")
async def registrar_decision(documento_id: str, decision: DecisionUsuario):
    """Registra decisión de revisión humana."""

    if documento_id not in documentos_procesados:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    try:
        # Crear decisión
        doc_info = documentos_procesados[documento_id]
        bloque = next(
            (b for b in doc_info["bloques"] if str(b.id) == decision.bloque_id),
            None
        )

        if not bloque:
            raise ValueError("Bloque no encontrado")

        decision_rev = DecisionRevision(
            bloque_id=UUID(decision.bloque_id),
            documento_id=doc_info["documento"].documento_id,
            pagina=bloque.pagina,
            tipo_bloque=bloque.tipo.value,
            decision=decision.decision,
            contenido_original=bloque.contenido.texto_plano or "",
            contenido_final=decision.contenido_final,
            confianza_engine=bloque.layout.confianza_layout,
            confianza_usuario=decision.confianza_usuario,
            comentarios=decision.comentarios,
            revisor="usuario_web"
        )

        gestor_decisiones.registrar_decision(decision_rev)

        return {"status": "ok", "decision_id": str(decision_rev.bloque_id)}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/metricas")
async def obtener_metricas():
    """Obtiene métricas globales del sistema."""

    stats = gestor_decisiones.obtener_estadisticas()
    analizador = AnalizadorFeedback(gestor_decisiones._decisiones_cache)
    resumen = analizador.obtener_resumen_mejoras()

    return EstadisticasGlobales(
        documentos_procesados=len(documentos_procesados),
        bloques_totales=sum(len(d["bloques"]) for d in documentos_procesados.values()),
        bloques_revisados=stats.get("total", 0),
        tasa_cambio=stats.get("tasa_cambio", 0),
        confianza_promedio=stats.get("confianza_promedio_usuario", 0),
        ajustes_pendientes=0  # Calculado en auto-ajuste
    )

@app.post("/auto-ajuste")
async def aplicar_auto_ajuste():
    """Aplica auto-ajuste de umbrales basado en feedback."""

    try:
        # Analizar decisiones
        analizador = AnalizadorFeedback(gestor_decisiones._decisiones_cache)
        ajustes = ajustador.calcular_umbrales_optimos(gestor_decisiones._decisiones_cache)

        # Filtrar aplicables
        ajustes_aplicables = [a for a in ajustes if a.aplicable()]

        if not ajustes_aplicables:
            return {
                "status": "no_cambios",
                "razon": "No hay cambios significativos recomendados"
            }

        # Aplicar
        cantidad = ajustador.aplicar_ajustes(ajustes_aplicables)

        # Validar
        validacion = ajustador.validar_cambios([])

        return {
            "status": "ok" if validacion["mejora"] else "revertido",
            "cambios_aplicados": cantidad,
            "mejora": validacion["mejora"],
            "cambio_porcentaje": validacion["cambio_porcentaje"],
            "detalles": [str(a) for a in ajustes_aplicables]
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/umbrales")
async def obtener_umbrales():
    """Obtiene configuración actual de umbrales."""
    return ajustador.obtener_resumen_umbrales()

@app.get("/salud")
async def health_check():
    """Health check con métricas."""
    return {
        "status": "ok",
        "documentos": len(documentos_procesados),
        "decisiones": len(gestor_decisiones._decisiones_cache),
        "capas_activas": 7
    }

# ============================================================================
# EJECUTOR
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    print("\n" + "="*60)
    print("CAPA 7: Interfaz Web (FastAPI)")
    print("="*60)
    print("\nAPI corriendo en: http://localhost:8000")
    print("Docs Swagger: http://localhost:8000/docs")
    print("Docs ReDoc: http://localhost:8000/redoc")
    print("\n" + "="*60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
