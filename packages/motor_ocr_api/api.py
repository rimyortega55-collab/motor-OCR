"""API REST con FastAPI para procesamiento OCR completo.

Sin cuentas: el proyecto es open source y de un solo operador. Si la instancia
define `MOTOR_OCR_CLAVE_ACCESO`, todos los endpoints de datos exigen la cookie
de acceso (`exigir_acceso`); sin esa variable, la API queda abierta, como
corresponde a correrla en una notebook.

El estado vive en base de datos (ver motor_ocr_api/persistencia). Antes se
guardaba en un diccionario de módulo, que se perdía en cada reinicio y no se
compartía entre instancias, con lo que ni el historial ni el registro de
costos sobrevivían a un despliegue.

Endpoints:
- POST /procesar — Procesa PDF completo (Capas 1-5)
- GET /documentos — Lista los documentos de la instancia
- GET /documentos/<id> — Obtiene resultado de documento
- POST /revision/<id>/decision — Registra decisión humana
- GET /metricas — Dashboard de métricas
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

from motor_ocr.escalacion.costo_tracking import limpiar_registro, obtener_registros
from motor_ocr.modelos import ModoMotor
from motor_ocr_api.persistencia import (
    BloqueAlmacenado,
    CostoRegistrado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    init_db,
    obtener_sesion,
    session_scope,
)
from motor_ocr.pipeline import Pipeline
from motor_ocr_api.revision import AnalizadorFeedback, DecisionRevision, GestorDecisiones
from .acceso import exigir_acceso
from .ajuste_umbrales import AjustadorUmbrales
from .cuotas import validar_archivo
from .limites import exigir_limite
from .retencion import DIAS_RETENCION_PDF, borrar_documento, purgar_pdfs_vencidos
from .seleccion import extraer_paginas, interpretar_rango
from .estaticos import INDICE, hay_build, montar_spa
from .rutas_acceso import router as router_acceso
from .rutas_admin import aplicar_configuracion, obtener_o_crear as obtener_config_motor_ia
from .rutas_admin import aplicar_modelo_matematico, obtener_o_crear_modelo_matematico
from .rutas_admin import obtener_o_crear_procesamiento
from .rutas_admin import router as router_admin
from .rutas_bloques import router as router_bloques
from .rutas_consumo import router as router_consumo
from .rutas_traduccion import router as router_traduccion
from .rutas_umbrales import router as router_umbrales
from .trabajos import aplicar_limite_paralelo, encolar, marcar_colgados, progreso_inicial

app = FastAPI(
    title="Motor OCR",
    description="7 capas con persistencia. Sin cuentas: una instancia, un operador.",
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

    # La configuración de proveedor de IA vive en base y no sólo en variables de
    # entorno desde que existe el panel de administración; sin esto, un cambio
    # guardado antes del último reinicio se perdía y el proceso volvía a hablar
    # con Anthropic por variables de entorno sin que nadie lo pidiera.
    with session_scope() as sesion:
        aplicar_configuracion(obtener_config_motor_ia(sesion))

    # Mismo motivo: cuánto paralelismo se configuró desde el panel antes del
    # último reinicio no debería perderse y volver al default del entorno.
    with session_scope() as sesion:
        aplicar_limite_paralelo(obtener_o_crear_procesamiento(sesion).max_paralelo)

    # Y qué checkpoint de pix2tex se eligió para reconocer fórmulas: sin esto,
    # probar un fine-tuning duraría hasta el próximo reinicio y el motor volvía
    # a los pesos base sin avisar.
    with session_scope() as sesion:
        aplicar_modelo_matematico(obtener_o_crear_modelo_matematico(sesion))

    # El PDF sólo hace falta mientras alguien vaya a mirar sus páginas. Sin esto
    # el directorio de datos crecía sin techo y el archivo quedaba guardado para
    # siempre.
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
    """Health check con métricas. No requiere clave de acceso."""
    return {
        "status": "ok",
        "documentos": sesion.query(func.count(DocumentoAlmacenado.id)).scalar() or 0,
        "capas_activas": 7,
    }


# ============================================================================
# ENDPOINTS DE DATOS — protegidos por `exigir_acceso` cuando hay clave configurada
# ============================================================================

class TrabajoEncolado(BaseModel):
    documento_id: str
    estado: str
    titulo: str
    modo_motor: str


def _parsear_modo_motor(modo: str | None) -> ModoMotor:
    """`None` o vacío = híbrido, que es como venía procesando el motor siempre.

    Se valida acá y no más adentro para que un valor mal escrito devuelva 400
    en el momento de subir, y no un documento que arranca a procesarse y muere
    en el worker media hora después.
    """
    if modo is None or not modo.strip():
        return ModoMotor.HIBRIDO

    try:
        return ModoMotor(modo.strip().lower())
    except ValueError:
        opciones = ", ".join(m.value for m in ModoMotor)
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "modo_motor_invalido",
                "detail": f"modo_motor debe ser uno de: {opciones}",
            },
        )


# Por debajo de 72 (la resolución nativa del PDF, zoom=1) la imagen no alcanza
# ni para texto; por encima de 600 el renderizado por página empieza a costar
# memoria de sobra para lo que un motor de OCR aprovecha.
DPI_MINIMO = 72
DPI_MAXIMO = 600


def _parsear_dpi(dpi: str | None) -> int | None:
    """`None` o "auto" (default): DPI adaptativo por zona, como decide el triage."""
    if dpi is None or dpi.strip() == "" or dpi.strip().lower() == "auto":
        return None

    try:
        valor = int(dpi)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"codigo": "dpi_invalido", "detail": "dpi debe ser un entero o \"auto\""},
        )

    if not DPI_MINIMO <= valor <= DPI_MAXIMO:
        raise HTTPException(
            status_code=400,
            detail={
                "codigo": "dpi_invalido",
                "detail": f"dpi debe estar entre {DPI_MINIMO} y {DPI_MAXIMO}",
            },
        )

    return valor


@router_api.post("/procesar", status_code=202, dependencies=[Depends(exigir_acceso)])
async def procesar_pdf(
    request: Request,
    file: UploadFile = File(...),
    paginas: str = Form(default=""),
    dpi: str | None = Form(default=None),
    idioma_original: str | None = Form(default=None),
    modo_motor: str | None = Form(default=None),
    sesion: Session = Depends(obtener_sesion),
) -> TrabajoEncolado:
    """Encola un PDF y devuelve enseguida.

    Antes corría las cinco capas dentro del request. Un PDF de 92 páginas tarda
    minutos: el navegador cortaba por timeout mucho antes y no había forma de
    saber si había pasado algo. Ahora el pipeline corre aparte y el avance se
    consulta en `GET /documentos/{id}/estado`.

    `dpi` reemplaza el DPI adaptativo del triage para todo el documento; sin
    mandarlo (o mandando "auto") sigue variando por zona como siempre.
    `idioma_original` es sólo metadato para ofrecer un default al traducir, no
    cambia qué motor de OCR reconoce el documento (ver `Pipeline.ejecutar`).

    `modo_motor` sí lo cambia: `hibrido` (default) reconoce con el motor
    determinista y reserva el modelo de IA para los recortes de fórmula;
    `solo_ia` manda todos los bloques al modelo. Ver `ModoMotor`.
    """

    # Cada documento cuesta cómputo y, si escala, llamadas al modelo: sin tope,
    # un solo cliente puede vaciar el crédito del proveedor de IA configurado.
    exigir_limite(request, "procesar")

    dpi_valido = _parsear_dpi(dpi)
    modo = _parsear_modo_motor(modo_motor)

    contenido = await file.read()

    # Validar antes de crear la fila: si el archivo no sirve, no tiene sentido
    # dejar un documento en la base ni ocupar un hilo del worker.
    total_paginas = validar_archivo(contenido)

    # Elegir el rango antes de procesar es la forma más directa de no gastar en
    # lo que no se va a leer: cada página escaneada son segundos de docTR y, si
    # sale con baja confianza, llamadas al modelo.
    elegidas = interpretar_rango(paginas, total_paginas)
    seleccion_parcial = len(elegidas) < total_paginas
    if seleccion_parcial:
        contenido = extraer_paginas(contenido, elegidas)

    documento_id = str(uuid4())
    registro = DocumentoAlmacenado(
        id=documento_id,
        titulo=file.filename or "sin-nombre.pdf",
        estado="en_cola",
        total_paginas=len(elegidas),
        paginas_origen=elegidas if seleccion_parcial else None,
        progreso=progreso_inicial(),
        idioma_original=idioma_original.strip() if idioma_original and idioma_original.strip() else None,
        modo_motor=modo.value,
    )
    sesion.add(registro)
    sesion.commit()

    # Se pasa el contenido en memoria y no la ruta: el archivo temporal lo crea
    # el worker, así no depende de que el request siga vivo.
    encolar(
        documento_id,
        contenido,
        dpi_override=dpi_valido,
        idioma_original=registro.idioma_original,
        modo=modo,
    )

    return TrabajoEncolado(
        documento_id=documento_id,
        estado="en_cola",
        titulo=registro.titulo,
        modo_motor=modo.value,
    )


@router_api.get("/documentos/{documento_id}/estado", dependencies=[Depends(exigir_acceso)])
async def estado_documento(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Progreso por capa. Es lo que hace posible la barra de la pantalla de subida."""

    documento = _documento(sesion, documento_id)
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
        "idioma_original": documento.idioma_original,
        "modo_motor": documento.modo_motor,
        "error": documento.error,
        "actualizado_en": (
            documento.actualizado_en.isoformat() if documento.actualizado_en else None
        ),
    }


@router_api.get("/documentos", dependencies=[Depends(exigir_acceso)])
async def listar_documentos(
    sesion: Session = Depends(obtener_sesion),
    limite: int = 50,
    cursor: str | None = None,
    estado: str | None = None,
    buscar: str | None = None,
    necesita_revision: bool | None = None,
):
    """Documentos de la instancia, del más reciente al más viejo.

    Pagina por cursor y no por OFFSET: con miles de documentos, saltear filas
    obliga a la base a recorrer todo lo salteado en cada página.
    """

    limite = max(1, min(limite, 200))

    consulta = sesion.query(DocumentoAlmacenado)

    if estado:
        consulta = consulta.filter(DocumentoAlmacenado.estado == estado)

    if buscar:
        # `ilike` con comodines a los dos lados: se busca por un pedazo del
        # nombre del archivo, no por su prefijo.
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
                # El motivo viaja en el listado y no sólo en el detalle: una
                # fila en rojo sin explicación obliga a abrir el documento para
                # enterarse de algo que entra en un tooltip.
                "error": d.error,
                "total_paginas": d.total_paginas,
                "total_bloques": d.total_bloques,
                "inconsistencias": d.inconsistencias,
                "necesita_revision": d.necesita_revision,
                # Con qué modo se reconoció: dos documentos de la misma
                # instancia pueden tener calidades muy distintas y el modo es
                # la primera explicación a mirar.
                "modo_motor": d.modo_motor,
                "creado_en": d.creado_en.isoformat() if d.creado_en else None,
            }
            for d in documentos
        ],
        "siguiente_cursor": siguiente,
        "total": total,
    }


@router_api.get("/documentos/{documento_id}", dependencies=[Depends(exigir_acceso)])
async def obtener_documento(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Obtiene el resultado de un documento procesado."""

    documento = _documento(sesion, documento_id)

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
        "modo_motor": documento.modo_motor,
        "costo_usd": float(costo or 0.0),
        "creado_en": documento.creado_en.isoformat() if documento.creado_en else None,
        "resumen": documento.resultado,
    }


@router_api.delete("/documentos/{documento_id}", status_code=204, dependencies=[Depends(exigir_acceso)])
async def eliminar_documento(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Borra un documento con sus bloques, costos, decisiones y archivos.

    Los archivos se borran a mano porque viven fuera de la base y el cascade no
    los alcanza.
    """

    documento = _documento(sesion, documento_id)
    borrar_documento(sesion, documento)
    sesion.commit()

    return Response(status_code=204)


@router_api.post("/revision/{documento_id}/decision", dependencies=[Depends(exigir_acceso)])
async def registrar_decision(
    documento_id: str,
    decision: DecisionUsuario,
    sesion: Session = Depends(obtener_sesion),
):
    """Registra una decisión de revisión humana y la aplica al bloque.

    El cliente manda sólo la decisión y el contenido: el tipo de bloque, la
    página y la confianza del motor los completa el servidor leyendo el bloque.
    Antes se guardaban vacíos porque el cliente no los mandaba, y el auto-ajuste
    de umbrales agrupa las decisiones justamente por tipo de bloque, así que el
    feedback loop no podía aprender nada.
    """

    documento = _documento(sesion, documento_id)

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


@router_api.get("/metricas", dependencies=[Depends(exigir_acceso)])
async def obtener_metricas(sesion: Session = Depends(obtener_sesion)):
    """Métricas de calidad de toda la instancia."""

    stats = gestor_decisiones.obtener_estadisticas()

    documentos = sesion.query(func.count(DocumentoAlmacenado.id)).scalar() or 0
    bloques = (
        sesion.query(func.coalesce(func.sum(DocumentoAlmacenado.total_bloques), 0)).scalar()
    ) or 0
    revisados = sesion.query(func.count(DecisionAlmacenada.id)).scalar() or 0

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


def _documento(sesion: Session, documento_id: str) -> DocumentoAlmacenado:
    documento = sesion.get(DocumentoAlmacenado, documento_id)
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento


# ============================================================================
# CABLEADO
# ============================================================================

app.include_router(router_api)
app.include_router(router_acceso, prefix="/api")
app.include_router(router_bloques, prefix="/api", dependencies=[Depends(exigir_acceso)])
app.include_router(router_umbrales, prefix="/api", dependencies=[Depends(exigir_acceso)])
app.include_router(router_consumo, prefix="/api", dependencies=[Depends(exigir_acceso)])
app.include_router(router_traduccion, prefix="/api", dependencies=[Depends(exigir_acceso)])
app.include_router(router_admin, prefix="/api", dependencies=[Depends(exigir_acceso)])
# Al final del modulo a proposito: el catch-all del SPA tiene que registrarse
# despues de todas las rutas de la API para no taparlas.
montar_spa(app)
