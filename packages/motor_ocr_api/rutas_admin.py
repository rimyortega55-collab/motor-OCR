"""Configuración de la instancia: proveedor de IA y resumen de uso.

Existe porque el proyecto es open source y auto-hospedado: quien levanta su
propia instancia necesita poder elegir de dónde sale la inteligencia de la
Capa 5 (Anthropic, cualquier API compatible con OpenAI, o en el futuro un
modelo local) sin editar variables de entorno ni reiniciar el proceso. Sin
cuentas, no hay "quién puede tocar esto": el gate es el mismo que el resto de
la API (`exigir_acceso`, la clave de instancia si hay una configurada).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from motor_ocr.escalacion.cliente_llm import configurar_proveedor
from motor_ocr.reconocimiento.engines import pix2tex_engine
from motor_ocr_api.persistencia import (
    ConfiguracionModeloMatematico,
    ConfiguracionMotorIA,
    ConfiguracionProcesamiento,
    CostoRegistrado,
    DocumentoAlmacenado,
    obtener_sesion,
)

from . import trabajos
from .acceso import clave_configurada, origen_clave, revocar_clave, rotada_en, rotar_clave

router = APIRouter(tags=["admin"])

PROVEEDORES_VALIDOS = {"anthropic", "openai_compatible", "local"}


class ActualizacionMotorIA(BaseModel):
    proveedor: str | None = None
    modelo: str | None = None
    base_url: str | None = None
    # None = no tocar la clave guardada; "" = borrarla.
    api_key: str | None = None
    habilitado: bool | None = None


def _iso(momento: datetime | None) -> str | None:
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.isoformat()


def obtener_o_crear(sesion: Session) -> ConfiguracionMotorIA:
    fila = sesion.get(ConfiguracionMotorIA, "global")
    if fila is not None:
        return fila

    fila = ConfiguracionMotorIA(id="global")
    sesion.add(fila)
    sesion.commit()
    return fila


def _serializar(fila: ConfiguracionMotorIA) -> dict:
    """Nunca devuelve la clave: sólo si está configurada y sus últimos 4 caracteres,
    igual que el prefijo visible de una API key de proveedor."""
    return {
        "proveedor": fila.proveedor,
        "modelo": fila.modelo,
        "base_url": fila.base_url,
        "api_key_configurada": bool(fila.api_key),
        "api_key_sufijo": fila.api_key[-4:] if fila.api_key else None,
        "habilitado": fila.habilitado,
        "actualizado_en": _iso(fila.actualizado_en),
    }


def aplicar_configuracion(fila: ConfiguracionMotorIA) -> None:
    """Empuja la fila vigente al cliente LLM en uso por el pipeline."""
    configurar_proveedor(
        proveedor=fila.proveedor,
        modelo=fila.modelo,
        base_url=fila.base_url,
        api_key=fila.api_key,
    )


@router.get("/admin/motor-ia")
async def leer_motor_ia(sesion: Session = Depends(obtener_sesion)):
    return _serializar(obtener_o_crear(sesion))


@router.put("/admin/motor-ia")
async def actualizar_motor_ia(
    cambios: ActualizacionMotorIA,
    sesion: Session = Depends(obtener_sesion),
):
    fila = obtener_o_crear(sesion)

    if cambios.proveedor is not None:
        proveedor = cambios.proveedor.strip().lower()
        if proveedor not in PROVEEDORES_VALIDOS:
            raise HTTPException(
                status_code=422,
                detail={
                    "codigo": "proveedor_invalido",
                    "detail": f"proveedor debe ser uno de {sorted(PROVEEDORES_VALIDOS)}",
                },
            )
        fila.proveedor = proveedor

    if cambios.modelo is not None:
        fila.modelo = cambios.modelo.strip() or fila.modelo
    if cambios.base_url is not None:
        fila.base_url = cambios.base_url.strip() or None
    if cambios.api_key is not None:
        fila.api_key = cambios.api_key.strip() or None
    if cambios.habilitado is not None:
        fila.habilitado = cambios.habilitado

    fila.actualizado_en = datetime.now(timezone.utc)
    sesion.commit()

    # Se aplica en caliente: el próximo bloque escalado ya usa el proveedor
    # nuevo, sin reiniciar el proceso.
    aplicar_configuracion(fila)

    return _serializar(fila)


def _serializar_clave_acceso(sesion: Session) -> dict:
    return {
        "requiere_clave": clave_configurada(sesion) is not None,
        "origen": origen_clave(sesion),
        "rotada_en": _iso(rotada_en(sesion)),
    }


@router.get("/admin/clave-acceso")
async def leer_clave_acceso(sesion: Session = Depends(obtener_sesion)):
    """Estado de la clave de acceso vigente, sin devolverla nunca en claro.

    `origen` distingue si la clave activa viene de rotarla en el panel
    ("panel") o de `MOTOR_OCR_CLAVE_ACCESO` en el entorno ("entorno"); `None`
    significa instancia abierta.
    """
    return _serializar_clave_acceso(sesion)


@router.post("/admin/clave-acceso/rotar")
async def rotar_clave_acceso(sesion: Session = Depends(obtener_sesion)):
    """Genera una clave nueva y cierra las sesiones ya abiertas, sin reiniciar el proceso.

    La clave nueva viaja en claro sólo en esta respuesta; después de leerla no
    vuelve a mostrarse en ningún otro endpoint.
    """
    nueva = rotar_clave(sesion)
    return {**_serializar_clave_acceso(sesion), "clave": nueva}


@router.delete("/admin/clave-acceso", status_code=204)
async def revocar_clave_acceso(sesion: Session = Depends(obtener_sesion)):
    """Quita la clave administrada desde el panel y cierra las sesiones ya abiertas.

    Si `MOTOR_OCR_CLAVE_ACCESO` sigue configurada en el entorno, la instancia
    vuelve a pedir esa; si no, queda abierta.
    """
    revocar_clave(sesion)


class ActualizacionProcesamiento(BaseModel):
    max_paralelo: int


def obtener_o_crear_procesamiento(sesion: Session) -> ConfiguracionProcesamiento:
    fila = sesion.get(ConfiguracionProcesamiento, "global")
    if fila is not None:
        return fila

    fila = ConfiguracionProcesamiento(id="global", max_paralelo=trabajos.paralelo_actual())
    sesion.add(fila)
    sesion.commit()
    return fila


def _serializar_procesamiento(fila: ConfiguracionProcesamiento) -> dict:
    return {
        "max_paralelo": fila.max_paralelo,
        "minimo": trabajos.MIN_PARALELO,
        "maximo": trabajos.MAX_PARALELO_PERMITIDO,
        "actualizado_en": _iso(fila.actualizado_en),
    }


@router.get("/admin/procesamiento")
async def leer_procesamiento(sesion: Session = Depends(obtener_sesion)):
    """Cuántos documentos procesa el pipeline a la vez, ahora mismo."""
    return _serializar_procesamiento(obtener_o_crear_procesamiento(sesion))


@router.put("/admin/procesamiento")
async def actualizar_procesamiento(
    cambios: ActualizacionProcesamiento,
    sesion: Session = Depends(obtener_sesion),
):
    """Sube o baja cuántos documentos corren en simultáneo, sin reiniciar el proceso.

    Los que ya estaban procesándose o esperando lugar bajo el límite anterior
    terminan igual; el límite nuevo rige recién para lo que se suba de acá en
    más (ver `trabajos.aplicar_limite_paralelo`).
    """
    try:
        trabajos.aplicar_limite_paralelo(cambios.max_paralelo)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"codigo": "max_paralelo_invalido", "detail": str(e)},
        )

    fila = obtener_o_crear_procesamiento(sesion)
    fila.max_paralelo = cambios.max_paralelo
    fila.actualizado_en = datetime.now(timezone.utc)
    sesion.commit()

    return _serializar_procesamiento(fila)


class ActualizacionModeloMatematico(BaseModel):
    # None = volver a los pesos pre-entrenados de pix2tex.
    checkpoint: str | None = None


def obtener_o_crear_modelo_matematico(sesion: Session) -> ConfiguracionModeloMatematico:
    fila = sesion.get(ConfiguracionModeloMatematico, "global")
    if fila is not None:
        return fila

    fila = ConfiguracionModeloMatematico(
        id="global", checkpoint=pix2tex_engine.checkpoint_actual()
    )
    sesion.add(fila)
    sesion.commit()
    return fila


def _serializar_modelo_matematico(fila: ConfiguracionModeloMatematico) -> dict:
    disponibles = pix2tex_engine.checkpoints_disponibles()
    return {
        # Lo que dice la fila guardada frente a lo que el proceso tiene cargado
        # ahora mismo: difieren si el .pth se borró del disco después de
        # elegirlo, y el panel necesita poder decirlo en vez de mentir.
        "checkpoint": fila.checkpoint,
        "checkpoint_en_uso": pix2tex_engine.checkpoint_actual(),
        "directorio": str(pix2tex_engine.DIRECTORIO_CHECKPOINTS),
        "disponibles": disponibles,
        "actualizado_en": _iso(fila.actualizado_en),
    }


@router.get("/admin/modelo-matematico")
async def leer_modelo_matematico(sesion: Session = Depends(obtener_sesion)):
    """Qué checkpoint de pix2tex reconoce las fórmulas (Capa 3), y cuáles hay para elegir."""
    return _serializar_modelo_matematico(obtener_o_crear_modelo_matematico(sesion))


@router.put("/admin/modelo-matematico")
async def actualizar_modelo_matematico(
    cambios: ActualizacionModeloMatematico,
    sesion: Session = Depends(obtener_sesion),
):
    """Cambia el checkpoint en caliente, para poder probar un fine-tuning recién bajado.

    Rige para los documentos que se suban de acá en más: lo que ya está a mitad
    del pipeline termina con el modelo que tenía cargado.
    """
    nombre = (cambios.checkpoint or "").strip() or None

    try:
        pix2tex_engine.configurar_checkpoint(nombre)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"codigo": "checkpoint_invalido", "detail": str(e)},
        )

    fila = obtener_o_crear_modelo_matematico(sesion)
    fila.checkpoint = nombre
    fila.actualizado_en = datetime.now(timezone.utc)
    sesion.commit()

    return _serializar_modelo_matematico(fila)


def aplicar_modelo_matematico(fila: ConfiguracionModeloMatematico) -> None:
    """Empuja la fila guardada al engine al arrancar el proceso.

    Si el .pth ya no está (se borró, o la instancia se movió de máquina), no
    corta el arranque: avisa y sigue con los pesos pre-entrenados, que es lo
    que el motor hacía antes de que esto existiera.
    """
    try:
        pix2tex_engine.configurar_checkpoint(fila.checkpoint)
    except ValueError as e:
        print(f"[MODELO] Checkpoint guardado no utilizable ({e}); se usan los pesos base")
        pix2tex_engine.configurar_checkpoint(None)


@router.get("/admin/resumen")
async def resumen(sesion: Session = Depends(obtener_sesion)):
    """Números generales de la instancia, para orientarse al entrar al panel."""

    documentos_totales = sesion.query(func.count(DocumentoAlmacenado.id)).scalar() or 0
    costo_total = (
        sesion.query(func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0)).scalar() or 0.0
    )

    return {
        "documentos_totales": documentos_totales,
        "costo_llm_usd_total": float(costo_total),
    }
