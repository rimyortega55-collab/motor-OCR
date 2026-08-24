"""API REST con FastAPI para procesamiento OCR completo.

Todos los endpoints de datos exigen una API key en la cabecera `X-API-Key`, y
cada documento y cada costo quedan atribuidos al usuario que los originó: sin
eso no hay forma de facturar ni de saber quién consume.

El estado vive en base de datos (ver ocr_engine/persistence). Antes se guardaba
en un diccionario de módulo, que se perdía en cada reinicio y no se compartía
entre instancias, con lo que ni el historial ni el registro de costos
sobrevivían a un despliegue.

Endpoints:
- POST /procesar — Procesa PDF completo (Capas 1-5)
- GET /documentos — Lista los documentos del usuario
- GET /documentos/<id> — Obtiene resultado de documento
- POST /revision/<id>/decision — Registra decisión humana
- GET /consumo — Consumo y costo acumulado del usuario
- GET /metricas — Dashboard de métricas
- POST /auto-ajuste — Aplica cambios de umbrales
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ocr_engine.escalation.costo_tracking import limpiar_registro, obtener_registros
from ocr_engine.persistence import (
    CostoRegistrado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    Usuario,
    init_db,
)
from ocr_engine.pipeline import Pipeline
from ocr_engine.revision import AnalizadorFeedback, DecisionRevision, GestorDecisiones
from .ajuste_umbrales import AjustadorUmbrales
from .auth import obtener_sesion, usuario_actual

app = FastAPI(
    title="OCR Pipeline API",
    description="7 capas con persistencia y autenticación",
    version="0.8"
)

ajustador = AjustadorUmbrales()
gestor_decisiones = GestorDecisiones()


@app.on_event("startup")
def _preparar_base() -> None:
    init_db()


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
    costo_usd: float


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
# ENDPOINTS PÚBLICOS
# ============================================================================

@app.get("/")
async def root():
    """Health check."""
    return {
        "status": "ok",
        "version": "0.8",
        "capas": [1, 2, 3, 4, 5, 6, 7],
        "features": ["triage", "segmentacion", "ocr", "correccion", "llm", "revision", "web"]
    }


@app.get("/salud")
async def health_check(sesion: Session = Depends(obtener_sesion)):
    """Health check con métricas. No expone datos de ningún usuario."""
    return {
        "status": "ok",
        "documentos": sesion.query(func.count(DocumentoAlmacenado.id)).scalar() or 0,
        "usuarios": sesion.query(func.count(Usuario.id)).scalar() or 0,
        "capas_activas": 7,
    }


# ============================================================================
# ENDPOINTS AUTENTICADOS
# ============================================================================

@app.post("/procesar")
async def procesar_pdf(
    file: UploadFile = File(...),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Procesa un PDF a través de las Capas 1-5."""

    documento_id = str(uuid4())
    # tempfile en vez de "/tmp" fijo: esa ruta no existe en Windows y hacía
    # fallar el endpoint antes siquiera de abrir el PDF.
    ruta_temporal = Path(tempfile.gettempdir()) / f"ocr_{documento_id}.pdf"

    registro = DocumentoAlmacenado(
        id=documento_id,
        usuario_id=usuario.id,
        titulo=file.filename or "sin-nombre.pdf",
        estado="procesando",
    )
    sesion.add(registro)
    sesion.commit()

    try:
        ruta_temporal.write_bytes(await file.read())

        # Pipeline completo. Antes se llamaba a las capas sueltas y quedaban
        # afuera la 3 (OCR) y la 5 (escalación).
        documento, bloques = Pipeline().ejecutar(str(ruta_temporal))

        inconsistencias = len(documento.inconsistencias_no_resueltas)
        baja_confianza = [
            b for b in bloques
            if (b.ocr.confianza_global is not None and b.ocr.confianza_global < 0.7)
        ]

        costo_total = _persistir_costos(
            sesion, usuario, registro, documento.documento_id
        )

        registro.estado = "completado"
        registro.total_paginas = documento.total_paginas
        registro.total_bloques = len(bloques)
        registro.inconsistencias = inconsistencias
        registro.necesita_revision = bool(baja_confianza or inconsistencias)
        registro.resultado = _resumir_documento(documento, bloques)
        registro.actualizado_en = datetime.now(timezone.utc)
        sesion.commit()

        return ResultadoOCR(
            documento_id=documento_id,
            titulo=registro.titulo,
            total_paginas=documento.total_paginas,
            total_bloques=len(bloques),
            bloques_con_baja_confianza=len(baja_confianza),
            inconsistencias=inconsistencias,
            necesita_revision=registro.necesita_revision,
            costo_usd=costo_total,
        )

    except Exception as e:
        # El documento queda registrado como fallido en vez de desaparecer: el
        # usuario necesita poder ver que su envío se procesó y con qué error.
        registro.estado = "error"
        registro.error = str(e)
        registro.actualizado_en = datetime.now(timezone.utc)
        sesion.commit()
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        ruta_temporal.unlink(missing_ok=True)
        limpiar_registro(documento_id)


@app.get("/documentos")
async def listar_documentos(
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
    limite: int = 50,
):
    """Documentos del usuario, del más reciente al más viejo."""

    documentos = (
        sesion.query(DocumentoAlmacenado)
        .filter(DocumentoAlmacenado.usuario_id == usuario.id)
        .order_by(DocumentoAlmacenado.creado_en.desc())
        .limit(min(limite, 200))
        .all()
    )

    return [
        {
            "documento_id": d.id,
            "titulo": d.titulo,
            "estado": d.estado,
            "total_paginas": d.total_paginas,
            "total_bloques": d.total_bloques,
            "necesita_revision": d.necesita_revision,
            "creado_en": d.creado_en.isoformat() if d.creado_en else None,
        }
        for d in documentos
    ]


@app.get("/documentos/{documento_id}")
async def obtener_documento(
    documento_id: str,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Obtiene el resultado de un documento procesado."""

    documento = _documento_del_usuario(sesion, usuario, documento_id)

    costo = (
        sesion.query(func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0))
        .filter(CostoRegistrado.documento_id == documento_id)
        .scalar()
    )

    return {
        "documento_id": documento.id,
        "titulo": documento.titulo,
        "estado": documento.estado,
        "error": documento.error,
        "total_paginas": documento.total_paginas,
        "total_bloques": documento.total_bloques,
        "inconsistencias": documento.inconsistencias,
        "necesita_revision": documento.necesita_revision,
        "costo_usd": float(costo or 0.0),
        "creado_en": documento.creado_en.isoformat() if documento.creado_en else None,
        "resumen": documento.resultado,
    }


@app.post("/revision/{documento_id}/decision")
async def registrar_decision(
    documento_id: str,
    decision: DecisionUsuario,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Registra una decisión de revisión humana."""

    documento = _documento_del_usuario(sesion, usuario, documento_id)

    try:
        almacenada = DecisionAlmacenada(
            documento_id=documento.id,
            bloque_id=decision.bloque_id,
            tipo_bloque="",
            decision=decision.decision,
            contenido_final=decision.contenido_final,
            confianza_usuario=decision.confianza_usuario,
            comentarios=decision.comentarios,
            revisor=usuario.nombre,
        )
        sesion.add(almacenada)

        # Se mantiene el gestor en memoria porque el analizador de feedback y el
        # auto-ajuste de umbrales (Capa 7) consumen su caché.
        gestor_decisiones.registrar_decision(
            DecisionRevision(
                bloque_id=UUID(decision.bloque_id),
                documento_id=UUID(documento.id),
                pagina=0,
                tipo_bloque="",
                decision=decision.decision,
                contenido_original="",
                contenido_final=decision.contenido_final,
                confianza_engine=0.0,
                confianza_usuario=decision.confianza_usuario,
                comentarios=decision.comentarios,
                revisor=usuario.nombre,
            )
        )

        sesion.commit()
        return {"status": "ok", "decision_id": almacenada.id}

    except HTTPException:
        raise
    except Exception as e:
        sesion.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/consumo")
async def obtener_consumo(
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Consumo acumulado del usuario. Es la base para facturar."""

    documentos = (
        sesion.query(func.count(DocumentoAlmacenado.id))
        .filter(DocumentoAlmacenado.usuario_id == usuario.id)
        .scalar()
    ) or 0

    paginas = (
        sesion.query(func.coalesce(func.sum(DocumentoAlmacenado.total_paginas), 0))
        .filter(DocumentoAlmacenado.usuario_id == usuario.id)
        .scalar()
    ) or 0

    fila = (
        sesion.query(
            func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0),
            func.coalesce(func.sum(CostoRegistrado.tokens_entrada), 0),
            func.coalesce(func.sum(CostoRegistrado.tokens_salida), 0),
            func.count(CostoRegistrado.id),
        )
        .filter(CostoRegistrado.usuario_id == usuario.id)
        .one()
    )

    return {
        "usuario": usuario.nombre,
        "plan": usuario.plan,
        "documentos_procesados": documentos,
        "paginas_procesadas": paginas,
        "llamadas_llm": fila[3],
        "tokens_entrada": fila[1],
        "tokens_salida": fila[2],
        "costo_llm_usd": round(float(fila[0]), 6),
    }


@app.get("/metricas")
async def obtener_metricas(
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Métricas del usuario."""

    stats = gestor_decisiones.obtener_estadisticas()

    documentos = (
        sesion.query(func.count(DocumentoAlmacenado.id))
        .filter(DocumentoAlmacenado.usuario_id == usuario.id)
        .scalar()
    ) or 0

    bloques = (
        sesion.query(func.coalesce(func.sum(DocumentoAlmacenado.total_bloques), 0))
        .filter(DocumentoAlmacenado.usuario_id == usuario.id)
        .scalar()
    ) or 0

    revisados = (
        sesion.query(func.count(DecisionAlmacenada.id))
        .join(DocumentoAlmacenado)
        .filter(DocumentoAlmacenado.usuario_id == usuario.id)
        .scalar()
    ) or 0

    return EstadisticasGlobales(
        documentos_procesados=documentos,
        bloques_totales=bloques,
        bloques_revisados=revisados,
        tasa_cambio=stats.get("tasa_cambio", 0),
        confianza_promedio=stats.get("confianza_promedio_usuario", 0),
        ajustes_pendientes=0,
    )


@app.post("/auto-ajuste")
async def aplicar_auto_ajuste(usuario: Usuario = Depends(usuario_actual)):
    """Aplica auto-ajuste de umbrales basado en feedback."""

    try:
        ajustes = ajustador.calcular_umbrales_optimos(gestor_decisiones._decisiones_cache)
        ajustes_aplicables = [a for a in ajustes if a.aplicable()]

        if not ajustes_aplicables:
            return {
                "status": "no_cambios",
                "razon": "No hay cambios significativos recomendados"
            }

        cantidad = ajustador.aplicar_ajustes(ajustes_aplicables)
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
async def obtener_umbrales(usuario: Usuario = Depends(usuario_actual)):
    """Obtiene la configuración actual de umbrales."""
    return ajustador.obtener_resumen_umbrales()


# ============================================================================
# AUXILIARES
# ============================================================================

def _documento_del_usuario(
    sesion: Session, usuario: Usuario, documento_id: str
) -> DocumentoAlmacenado:
    """Busca el documento restringido al usuario.

    El filtro por usuario es lo que impide que alguien lea documentos ajenos
    adivinando identificadores; se devuelve 404 y no 403 para no confirmar que
    ese documento existe.
    """
    documento = (
        sesion.query(DocumentoAlmacenado)
        .filter(
            DocumentoAlmacenado.id == documento_id,
            DocumentoAlmacenado.usuario_id == usuario.id,
        )
        .one_or_none()
    )

    if documento is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    return documento


def _persistir_costos(
    sesion: Session,
    usuario: Usuario,
    registro: DocumentoAlmacenado,
    documento_interno_id,
) -> float:
    """Vuelca a la base los costos que la Capa 5 acumuló para este documento."""

    total = 0.0
    for r in obtener_registros(documento_interno_id):
        total += r.costo_usd
        sesion.add(
            CostoRegistrado(
                usuario_id=usuario.id,
                documento_id=registro.id,
                bloque_id=r.bloque_id,
                tipo_cola=r.tipo_cola,
                modelo=r.modelo,
                tokens_entrada=r.tokens_entrada,
                tokens_salida=r.tokens_salida,
                costo_usd=r.costo_usd,
                razon_escalacion=r.razon_escalacion,
            )
        )

    return total


def _resumir_documento(documento, bloques) -> dict:
    """Resumen serializable del resultado, para devolverlo sin reprocesar."""

    por_tipo: dict[str, int] = {}
    for bloque in bloques:
        clave = bloque.tipo.value if hasattr(bloque.tipo, "value") else str(bloque.tipo)
        por_tipo[clave] = por_tipo.get(clave, 0) + 1

    confianzas = [
        b.ocr.confianza_global for b in bloques if b.ocr.confianza_global is not None
    ]

    return {
        "bloques_por_tipo": por_tipo,
        "confianza_media": (sum(confianzas) / len(confianzas)) if confianzas else None,
        "inconsistencias": [
            {"tipo": i.tipo, "detalle": i.detalle, "pagina": i.ubicacion_pagina}
            for i in documento.inconsistencias_no_resueltas
        ],
    }
