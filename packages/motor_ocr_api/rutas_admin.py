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
from motor_ocr_api.persistencia import (
    ConfiguracionMotorIA,
    CostoRegistrado,
    DocumentoAlmacenado,
    obtener_sesion,
)

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
