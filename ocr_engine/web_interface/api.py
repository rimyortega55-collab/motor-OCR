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

import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi import Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from ocr_engine.escalation.costo_tracking import limpiar_registro, obtener_registros
from ocr_engine.persistence import (
    BloqueAlmacenado,
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
from .cuotas import exigir_cuota, validar_archivo
from .limites import exigir_limite
from .retencion import DIAS_RETENCION_PDF, borrar_documento, purgar_pdfs_vencidos
from .seleccion import extraer_paginas, interpretar_rango
from .estaticos import INDICE, hay_build, montar_spa
from .rutas_bloques import router as router_bloques
from .rutas_consumo import router as router_consumo
from .rutas_cuenta import router as router_cuenta
from .rutas_traduccion import router as router_traduccion
from .rutas_umbrales import router as router_umbrales
from .trabajos import encolar, marcar_colgados, progreso_inicial

app = FastAPI(
    title="OCR Pipeline API",
    description="7 capas con persistencia y autenticación",
    version="0.9"
)

# Toda la API cuelga de /api. Sin ese prefijo, `GET /documentos` es a la vez el
# endpoint de datos y la ruta principal del SPA: el navegador recibe JSON en vez
# de la aplicacion.
router_api = APIRouter(prefix="/api")

ajustador = AjustadorUmbrales()
gestor_decisiones = GestorDecisiones()


@app.on_event("startup")
def _preparar_base() -> None:
    init_db()
    # Si el proceso se reinició, los trabajos que estaban corriendo murieron con
    # él: sin esto quedan en "procesando" para siempre.
    colgados = marcar_colgados()
    if colgados:
        print(f"[TRABAJOS] {colgados} documentos colgados marcados como error")

    # El PDF sólo hace falta mientras alguien vaya a mirar sus páginas. Sin esto
    # el directorio de datos crecía sin techo y el archivo de un usuario quedaba
    # guardado para siempre.
    purgados = purgar_pdfs_vencidos()
    if purgados:
        print(f"[RETENCION] {purgados} PDF borrados por antigüedad "
              f"(> {DIAS_RETENCION_PDF} días)")


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

@app.get("/", include_in_schema=False)
async def root():
    """El SPA si esta compilado; si no, un health check.

    En desarrollo el frontend lo sirve Vite en su propio puerto, asi que este
    endpoint responde el JSON y sirve para verificar que la API esta viva.
    """
    if hay_build():
        return FileResponse(INDICE, headers={"Cache-Control": "no-cache"})

    return {
        "status": "ok",
        "version": "0.9",
        "spa": "sin compilar (corre `npm run build` en frontend/)",
        "capas": [1, 2, 3, 4, 5, 6, 7],
        "features": ["triage", "segmentacion", "ocr", "correccion", "llm", "revision", "web"]
    }


@router_api.get("/salud")
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

class TrabajoEncolado(BaseModel):
    documento_id: str
    estado: str
    titulo: str


@router_api.post("/procesar", status_code=202)
async def procesar_pdf(
    request: Request,
    file: UploadFile = File(...),
    paginas: str = Form(default=""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
) -> TrabajoEncolado:
    """Encola un PDF y devuelve enseguida.

    Antes corría las cinco capas dentro del request. Un PDF de 92 páginas tarda
    minutos: el navegador cortaba por timeout mucho antes y el usuario no tenía
    forma de saber si había pasado algo. Ahora el pipeline corre aparte y el
    avance se consulta en `GET /documentos/{id}/estado`.
    """

    # Cada documento cuesta cómputo y, si escala, llamadas al modelo: sin tope,
    # una cuenta puede vaciar el crédito de Anthropic del despliegue.
    exigir_limite(request, "procesar")

    contenido = await file.read()

    # Validar antes de crear la fila: si el archivo no sirve, no tiene sentido
    # dejar un documento en la base ni ocupar un hilo del worker.
    total_paginas = validar_archivo(contenido)

    # Elegir el rango antes de procesar es la forma más directa de que el usuario
    # no pague por lo que no va a leer: cada página escaneada son segundos de
    # docTR y, si sale con baja confianza, llamadas al modelo.
    elegidas = interpretar_rango(paginas, total_paginas)
    seleccion_parcial = len(elegidas) < total_paginas
    if seleccion_parcial:
        contenido = extraer_paginas(contenido, elegidas)

    exigir_cuota(sesion, usuario, len(elegidas))

    documento_id = str(uuid4())
    registro = DocumentoAlmacenado(
        id=documento_id,
        usuario_id=usuario.id,
        titulo=file.filename or "sin-nombre.pdf",
        estado="en_cola",
        total_paginas=len(elegidas),
        paginas_origen=elegidas if seleccion_parcial else None,
        progreso=progreso_inicial(),
    )
    sesion.add(registro)
    sesion.commit()

    # Se pasa el contenido en memoria y no la ruta: el archivo temporal lo crea
    # el worker, así no depende de que el request siga vivo.
    encolar(documento_id, contenido, usuario.id)

    return TrabajoEncolado(
        documento_id=documento_id, estado="en_cola", titulo=registro.titulo
    )


@router_api.get("/documentos/{documento_id}/estado")
async def estado_documento(
    documento_id: str,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Progreso por capa. Es lo que hace posible la barra de la pantalla de subida."""

    documento = _documento_del_usuario(sesion, usuario, documento_id)
    progreso = documento.progreso or progreso_inicial()

    costo_parcial = (
        sesion.query(func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0))
        .filter(CostoRegistrado.documento_id == documento_id)
        .scalar()
    )

    return {
        "documento_id": documento.id,
        "titulo": documento.titulo,
        "estado": documento.estado,
        "capa_actual": progreso.get("capa_actual"),
        "capas": progreso.get("capas", []),
        "total_paginas": documento.total_paginas,
        "total_bloques": documento.total_bloques,
        "costo_usd_parcial": float(costo_parcial or 0.0),
        "error": documento.error,
        "actualizado_en": (
            documento.actualizado_en.isoformat() if documento.actualizado_en else None
        ),
    }


@router_api.get("/documentos")
async def listar_documentos(
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
    limite: int = 50,
    cursor: str | None = None,
    estado: str | None = None,
    buscar: str | None = None,
    necesita_revision: bool | None = None,
):
    """Documentos del usuario, del más reciente al más viejo.

    Pagina por cursor y no por OFFSET: con miles de documentos, saltear filas
    obliga a la base a recorrer todo lo salteado en cada página.
    """

    limite = max(1, min(limite, 200))

    consulta = sesion.query(DocumentoAlmacenado).filter(
        DocumentoAlmacenado.usuario_id == usuario.id
    )

    if estado:
        consulta = consulta.filter(DocumentoAlmacenado.estado == estado)

    if buscar:
        # `ilike` con comodines a los dos lados: el usuario busca por un pedazo
        # del nombre del archivo, no por su prefijo.
        patron = f"%{buscar.strip()}%"
        consulta = consulta.filter(DocumentoAlmacenado.titulo.ilike(patron))

    if necesita_revision is not None:
        consulta = consulta.filter(
            DocumentoAlmacenado.necesita_revision.is_(necesita_revision)
        )

    # El total se cuenta antes del cursor: es "cuántos hay en este filtro", no
    # "cuántos quedan", que es lo que la interfaz muestra junto a los chips.
    total = consulta.count()

    if cursor:
        fecha_corte, id_corte = _descifrar_cursor(cursor)
        consulta = consulta.filter(
            or_(
                DocumentoAlmacenado.creado_en < fecha_corte,
                and_(
                    DocumentoAlmacenado.creado_en == fecha_corte,
                    DocumentoAlmacenado.id < id_corte,
                ),
            )
        )

    # El id desempata: dos documentos subidos en el mismo instante harían que el
    # cursor saltee o repita filas si el orden no fuera total.
    documentos = (
        consulta.order_by(
            DocumentoAlmacenado.creado_en.desc(), DocumentoAlmacenado.id.desc()
        )
        .limit(limite + 1)
        .all()
    )

    hay_mas = len(documentos) > limite
    documentos = documentos[:limite]

    siguiente = (
        _cifrar_cursor(documentos[-1].creado_en, documentos[-1].id)
        if hay_mas and documentos
        else None
    )

    return {
        "items": [
            {
                "documento_id": d.id,
                "titulo": d.titulo,
                "estado": d.estado,
                "total_paginas": d.total_paginas,
                "total_bloques": d.total_bloques,
                "inconsistencias": d.inconsistencias,
                "necesita_revision": d.necesita_revision,
                "creado_en": d.creado_en.isoformat() if d.creado_en else None,
            }
            for d in documentos
        ],
        "siguiente_cursor": siguiente,
        "total": total,
    }


@router_api.get("/documentos/{documento_id}")
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


@router_api.delete("/documentos/{documento_id}", status_code=204)
async def eliminar_documento(
    documento_id: str,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Borra un documento con sus bloques, costos, decisiones y archivos.

    Hasta ahora no había forma de borrar nada: el PDF de un usuario quedaba en
    disco para siempre y él no podía hacer nada al respecto. Los archivos se
    borran a mano porque viven fuera de la base y el cascade no los alcanza.
    """

    documento = _documento_del_usuario(sesion, usuario, documento_id)
    borrar_documento(sesion, documento)
    sesion.commit()

    return Response(status_code=204)


@router_api.post("/revision/{documento_id}/decision")
async def registrar_decision(
    documento_id: str,
    decision: DecisionUsuario,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Registra una decisión de revisión humana y la aplica al bloque.

    El cliente manda sólo la decisión y el contenido: el tipo de bloque, la
    página y la confianza del motor los completa el servidor leyendo el bloque.
    Antes se guardaban vacíos porque el cliente no los mandaba, y el auto-ajuste
    de umbrales agrupa las decisiones justamente por tipo de bloque, así que el
    feedback loop no podía aprender nada.
    """

    documento = _documento_del_usuario(sesion, usuario, documento_id)

    bloque = (
        sesion.query(BloqueAlmacenado)
        .filter(
            BloqueAlmacenado.id == decision.bloque_id,
            BloqueAlmacenado.documento_id == documento.id,
        )
        .one_or_none()
    )

    if bloque is None:
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": "bloque_no_pertenece_al_documento",
                "detail": "Ese bloque no es de este documento",
            },
        )

    contenido_original = bloque.contenido_final or bloque.latex or bloque.texto_plano or ""

    almacenada = DecisionAlmacenada(
        documento_id=documento.id,
        bloque_id=bloque.id,
        pagina=bloque.pagina,
        tipo_bloque=bloque.tipo,
        decision=decision.decision,
        contenido_original=contenido_original,
        contenido_final=decision.contenido_final,
        confianza_engine=bloque.confianza_global or 0.0,
        confianza_usuario=decision.confianza_usuario,
        comentarios=decision.comentarios,
        revisor=usuario.nombre,
    )
    sesion.add(almacenada)

    # La decisión se escribe en el bloque: sin esto quedaba registrada pero la
    # exportación seguía entregando el texto sin corregir.
    if decision.decision != "escalar":
        bloque.contenido_final = decision.contenido_final
        bloque.estado_revision = "resuelto"

    # La sesión se crea con autoflush=False, así que sin esto las consultas de
    # abajo verían el bloque todavía pendiente y devolverían un conteo de más.
    sesion.flush()

    # El gestor en memoria alimenta el analizador de feedback y el auto-ajuste.
    gestor_decisiones.registrar_decision(
        DecisionRevision(
            bloque_id=UUID(bloque.id),
            documento_id=UUID(documento.id),
            pagina=bloque.pagina,
            tipo_bloque=bloque.tipo,
            decision=decision.decision,
            contenido_original=contenido_original,
            contenido_final=decision.contenido_final,
            confianza_engine=bloque.confianza_global or 0.0,
            confianza_usuario=decision.confianza_usuario,
            comentarios=decision.comentarios,
            revisor=usuario.nombre,
        )
    )

    siguiente = (
        sesion.query(BloqueAlmacenado)
        .filter(
            BloqueAlmacenado.documento_id == documento.id,
            BloqueAlmacenado.estado_revision == "pendiente",
            BloqueAlmacenado.id != bloque.id,
        )
        .order_by(
            BloqueAlmacenado.confianza_global.is_(None),
            BloqueAlmacenado.confianza_global.asc(),
        )
        .first()
    )

    # Quedan pendientes: si ya no hay ninguno, la revisión terminó.
    pendientes = (
        sesion.query(func.count(BloqueAlmacenado.id))
        .filter(
            BloqueAlmacenado.documento_id == documento.id,
            BloqueAlmacenado.estado_revision == "pendiente",
        )
        .scalar()
    ) or 0

    documento.necesita_revision = pendientes > 0
    sesion.commit()

    return {
        "decision_id": almacenada.id,
        # Evita un round-trip: el visor avanza sin volver a pedir la cola.
        "siguiente_bloque_id": siguiente.id if siguiente else None,
        "pendientes": pendientes,
    }


@router_api.get("/metricas")
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


# ============================================================================
# AUXILIARES
# ============================================================================

def _cifrar_cursor(creado_en: datetime | None, documento_id: str) -> str:
    """Empaqueta la última fila de la página como cursor opaco.

    Se codifica en base64 para que el frontend no lo interprete ni lo arme a
    mano: si mañana el orden cambia, el contenido del cursor cambia sin romper
    a nadie.
    """
    marca = creado_en.isoformat() if creado_en else ""
    crudo = f"{marca}|{documento_id}".encode("utf-8")
    return base64.urlsafe_b64encode(crudo).decode("ascii")


def _descifrar_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        crudo = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        marca, documento_id = crudo.split("|", 1)
        return datetime.fromisoformat(marca), documento_id
    except (ValueError, TypeError, binascii.Error):
        # Un cursor inválido es un pedido mal formado, no un error del servidor.
        raise HTTPException(
            status_code=400,
            detail={"codigo": "cursor_invalido", "detail": "El cursor no es válido"},
        )


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


# ============================================================================
# CABLEADO
# ============================================================================

app.include_router(router_api)
app.include_router(router_cuenta, prefix="/api")
app.include_router(router_bloques, prefix="/api")
app.include_router(router_umbrales, prefix="/api")
app.include_router(router_consumo, prefix="/api")
app.include_router(router_traduccion, prefix="/api")
# Al final del modulo a proposito: el catch-all del SPA tiene que registrarse
# despues de todas las rutas de la API para no taparlas.
montar_spa(app)
