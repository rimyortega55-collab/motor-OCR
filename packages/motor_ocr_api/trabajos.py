"""Procesamiento de documentos fuera del request.

`POST /procesar` corría el pipeline entero dentro del request y devolvía el
resultado. Un PDF de 92 páginas tarda minutos: el navegador corta por timeout
mucho antes, y mientras tanto no hay forma de saber en qué va.

Acá el endpoint encola y responde 202 con el id; el pipeline corre en un hilo
aparte que va escribiendo el progreso por capa en la fila del documento, y la
interfaz lo consulta con `GET /documentos/{id}/estado`.

**Límite conocido:** los trabajos viven en el proceso. Alcanza para una
instancia; con varias, cada una sólo ve los suyos, y si el proceso muere los
documentos quedan en `procesando`. Por eso se escribe `latido_en`: `marcar_colgados`
los cierra como error en vez de dejarlos colgados para siempre. Cuando haga falta
escalar a varias instancias, esto se reemplaza por una cola real (RQ, Celery,
arq) sin tocar los endpoints.
"""

from __future__ import annotations

import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_ocr_api.persistencia import (
    BloqueAlmacenado,
    CostoRegistrado,
    DocumentoAlmacenado,
    session_scope,
)
from motor_ocr.config.settings import settings
from motor_ocr.escalacion.costo_tracking import limpiar_registro, obtener_registros
from motor_ocr.pipeline import Pipeline

from .almacen import guardar_pdf

CAPAS = {
    1: "triage",
    2: "segmentacion",
    3: "ocr",
    4: "correccion",
    5: "escalacion",
}

# Un documento sin latido por más de esto se da por muerto. Diez minutos es
# holgado incluso para un PDF grande, porque la Capa 3 late cada 1 % de avance.
LATIDO_MAXIMO = timedelta(minutes=10)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def progreso_inicial() -> dict:
    return {
        "capa_actual": None,
        "capas": [
            {"capa": numero, "nombre": nombre, "estado": "pendiente"}
            for numero, nombre in CAPAS.items()
        ],
    }


class _Reportero:
    """Traduce los avisos del pipeline a la fila del documento.

    Escribe en su propia sesión: la del request ya se cerró cuando este hilo
    empieza a correr.
    """

    def __init__(self, documento_id: str) -> None:
        self.documento_id = documento_id
        self.progreso = progreso_inicial()

    def __call__(self, capa: int, estado: str, **datos) -> None:
        for entrada in self.progreso["capas"]:
            if entrada["capa"] != capa:
                continue

            entrada["estado"] = estado
            if "detalle" in datos:
                entrada["detalle"] = datos["detalle"]
            if "hechos" in datos and "total" in datos:
                entrada["progreso"] = {"hechos": datos["hechos"], "total": datos["total"]}
            if "engines" in datos:
                entrada["detalle_engines"] = datos["engines"]

        self.progreso["capa_actual"] = capa if estado == "en_curso" else capa

        with session_scope() as sesion:
            documento = sesion.get(DocumentoAlmacenado, self.documento_id)
            if documento is None:
                return

            # Copia nueva y no mutación in situ: SQLAlchemy no detecta cambios
            # dentro de un JSON ya asignado, y el progreso no se guardaría.
            documento.progreso = {
                "capa_actual": self.progreso["capa_actual"],
                "capas": [dict(c) for c in self.progreso["capas"]],
            }
            documento.latido_en = _ahora()

            if "total_paginas" in datos:
                documento.total_paginas = datos["total_paginas"]
            if "total_bloques" in datos:
                documento.total_bloques = datos["total_bloques"]


def encolar(documento_id: str, contenido: bytes) -> None:
    """Arranca el procesamiento en segundo plano y vuelve enseguida."""

    hilo = threading.Thread(
        target=_procesar,
        args=(documento_id, contenido),
        name=f"ocr-{documento_id[:8]}",
        daemon=True,
    )
    hilo.start()


def _procesar(documento_id: str, contenido: bytes) -> None:
    ruta = Path(tempfile.gettempdir()) / f"ocr_{documento_id}.pdf"
    reportero = _Reportero(documento_id)

    with session_scope() as sesion:
        documento = sesion.get(DocumentoAlmacenado, documento_id)
        if documento is None:
            return
        documento.estado = "procesando"
        documento.progreso = progreso_inicial()
        documento.latido_en = _ahora()

    try:
        ruta.write_bytes(contenido)
        # El PDF se conserva: el visor de revisión renderiza sus páginas a
        # demanda, y antes se borraba apenas terminaba el pipeline.
        ruta_guardada = guardar_pdf(documento_id, contenido)

        documento_ocr, bloques = Pipeline(al_progresar=reportero).ejecutar(str(ruta))

        inconsistencias = len(documento_ocr.inconsistencias_no_resueltas)
        baja_confianza = [
            b for b in bloques
            if b.ocr.confianza_global is not None and b.ocr.confianza_global < 0.7
        ]

        with session_scope() as sesion:
            registro = sesion.get(DocumentoAlmacenado, documento_id)
            if registro is None:
                return

            _persistir_costos(sesion, documento_id, documento_ocr.documento_id)

            _persistir_bloques(sesion, documento_id, bloques)

            registro.ruta_pdf = ruta_guardada
            registro.estado = "completado"
            registro.total_paginas = documento_ocr.total_paginas
            registro.total_bloques = len(bloques)
            registro.inconsistencias = inconsistencias
            registro.necesita_revision = bool(baja_confianza or inconsistencias)
            registro.resultado = _resumir(documento_ocr, bloques)
            registro.progreso = reportero.progreso
            registro.latido_en = _ahora()
            registro.actualizado_en = _ahora()

    except Exception as e:
        # El documento queda registrado como fallido en vez de desaparecer: hay
        # que poder ver que el envío se procesó y con qué error.
        with session_scope() as sesion:
            registro = sesion.get(DocumentoAlmacenado, documento_id)
            if registro is not None:
                registro.estado = "error"
                registro.error = str(e)
                registro.progreso = reportero.progreso
                registro.actualizado_en = _ahora()

    finally:
        ruta.unlink(missing_ok=True)
        limpiar_registro(documento_id)


def marcar_colgados() -> int:
    """Cierra como error los documentos cuyo worker dejó de dar señales.

    Se llama al arrancar la API: si el proceso se reinició, los trabajos que
    estaban corriendo murieron con él y nadie los va a terminar.
    """

    corte = _ahora() - LATIDO_MAXIMO
    cerrados = 0

    with session_scope() as sesion:
        en_curso = (
            sesion.query(DocumentoAlmacenado)
            .filter(DocumentoAlmacenado.estado.in_(("procesando", "en_cola")))
            .all()
        )

        for documento in en_curso:
            latido = documento.latido_en or documento.creado_en
            if latido is not None and latido.tzinfo is None:
                latido = latido.replace(tzinfo=timezone.utc)

            if latido is not None and latido > corte:
                continue

            documento.estado = "error"
            documento.error = (
                "El procesamiento se interrumpió: el proceso que lo atendía dejó de "
                "responder. Volvé a subir el documento."
            )
            cerrados += 1

    return cerrados


def _persistir_bloques(sesion, documento_id: str, bloques) -> int:
    """Vuelca los bloques del pipeline a la tabla `bloques`.

    Antes se descartaban al terminar de procesar y sólo quedaba un resumen con
    conteos, así que la revisión bloque a bloque no tenía de dónde leer.
    """

    # Un documento puede reprocesarse; sin esto quedarían los bloques viejos
    # mezclados con los nuevos.
    sesion.query(BloqueAlmacenado).filter(
        BloqueAlmacenado.documento_id == documento_id
    ).delete(synchronize_session=False)

    filas = []
    for bloque in bloques:
        confianza = bloque.ocr.confianza_global
        escalacion = bloque.escalacion

        filas.append(
            BloqueAlmacenado(
                id=str(bloque.id),
                documento_id=documento_id,
                pagina=bloque.pagina,
                orden_lectura=bloque.layout.orden_lectura,
                tipo=_valor(bloque.tipo),
                origen_contenido=_valor(bloque.origen_contenido),
                bbox=_bbox(bloque.layout.bbox),
                confianza_layout=bloque.layout.confianza_layout,
                confianza_global=confianza,
                texto_plano=bloque.contenido.texto_plano,
                latex=bloque.contenido.latex,
                micro_segmentos=[
                    {
                        "tipo": m.tipo,
                        "contenido": m.contenido,
                        "engine_usado": _valor(m.engine_usado),
                        "confianza_engine": m.confianza_engine,
                        "confianza_estructural": m.confianza_estructural,
                    }
                    for m in bloque.ocr.micro_segmentos
                ],
                escalacion=_escalacion(escalacion) if escalacion.requirio_escalacion else None,
                estado_revision=_estado_revision(confianza, escalacion),
            )
        )

    # bulk_save_objects en vez de add() uno por uno: un documento de 30 000
    # bloques con inserciones individuales tarda minutos.
    sesion.bulk_save_objects(filas)
    return len(filas)


def _valor(valor):
    """Los enums de Pydantic viajan como su `.value`; el resto, como texto."""
    return getattr(valor, "value", str(valor))


def _bbox(bbox) -> dict:
    x0, y0, x1, y1 = bbox
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _escalacion(escalacion) -> dict:
    costo = escalacion.costo
    return {
        "requirio_escalacion": True,
        "cola_origen": _valor(escalacion.cola_origen) if escalacion.cola_origen else None,
        "contenido_llm": escalacion.contenido_llm,
        "confianza_llm": escalacion.confianza_llm,
        "razon_escalacion": escalacion.razon_escalacion,
        "requiere_revision_humana": escalacion.requiere_revision_humana,
        "tokens_entrada": costo.tokens_entrada,
        "tokens_salida": costo.tokens_salida,
        "modelo_usado": list(costo.modelo_usado),
    }


def _estado_revision(confianza: float | None, escalacion) -> str:
    """Qué bloques entran a la cola de revisión humana.

    Los que el modelo marcó explícitamente, y los que quedaron por debajo del
    umbral de confianza. El resto no necesita que nadie los mire.
    """
    if escalacion.requiere_revision_humana:
        return "pendiente"

    if confianza is not None and confianza < settings.umbral_confianza_global_escalacion:
        return "pendiente"

    return "no_requiere"


def _persistir_costos(sesion, documento_id: str, documento_interno_id) -> float:
    """Vuelca a la base los costos que la Capa 5 acumuló para este documento."""

    total = 0.0
    for r in obtener_registros(documento_interno_id):
        total += r.costo_usd
        sesion.add(
            CostoRegistrado(
                documento_id=documento_id,
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


def _resumir(documento, bloques) -> dict:
    """Resumen serializable del resultado, para devolverlo sin reprocesar."""

    por_tipo: dict[str, int] = {}
    for bloque in bloques:
        clave = bloque.tipo.value if hasattr(bloque.tipo, "value") else str(bloque.tipo)
        por_tipo[clave] = por_tipo.get(clave, 0) + 1

    confianzas = [b.ocr.confianza_global for b in bloques if b.ocr.confianza_global is not None]

    return {
        "bloques_por_tipo": por_tipo,
        "confianza_media": (sum(confianzas) / len(confianzas)) if confianzas else None,
        "inconsistencias": [
            {"tipo": i.tipo, "detalle": i.detalle, "pagina": i.ubicacion_pagina}
            for i in documento.inconsistencias_no_resueltas
        ],
    }
