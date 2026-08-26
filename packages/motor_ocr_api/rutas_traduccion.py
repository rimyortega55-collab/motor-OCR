"""Traducción de un documento ya convertido.

El usuario decide el contexto —qué es el documento, para quién, con qué glosario,
qué partes y con qué tono— y eso es lo que separa una traducción técnica
utilizable de una literal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from motor_ocr_api.persistencia import (
    BloqueAlmacenado,
    DocumentoAlmacenado,
    TraduccionBloque,
    TraduccionDocumento,
    obtener_sesion,
)
from motor_ocr.traduccion import TIPOS_NO_TRADUCIBLES, bloques_a_traducir, extraer_terminos

from .trabajos_traduccion import contenido_de, encolar_traduccion

router = APIRouter(tags=["traduccion"])


class Seleccion(BaseModel):
    """Qué parte del documento se traduce. Vacío = todo lo traducible."""

    paginas: list[int] = Field(default_factory=list)
    tipos: list[str] = Field(default_factory=list)


class PedidoTraduccion(BaseModel):
    idioma: str = Field(min_length=2, max_length=12)
    descripcion: str = Field(default="", max_length=2000)
    tono: str = Field(default="academico", pattern="^(academico|accesible)$")
    glosario: dict[str, str] = Field(default_factory=dict)
    seleccion: Seleccion = Field(default_factory=Seleccion)


def _error(codigo: str, detalle: str, http: int) -> HTTPException:
    return HTTPException(status_code=http, detail={"codigo": codigo, "detail": detalle})


def _documento(sesion: Session, documento_id: str) -> DocumentoAlmacenado:
    documento = sesion.get(DocumentoAlmacenado, documento_id)
    if documento is None:
        raise _error("documento_no_encontrado", "No existe ese documento", 404)
    return documento


def _serializar(pedido: TraduccionDocumento) -> dict:
    return {
        "id": pedido.id,
        "idioma": pedido.idioma,
        "descripcion": pedido.descripcion or "",
        "tono": pedido.tono,
        "glosario": pedido.glosario or {},
        "seleccion": pedido.seleccion or {},
        "estado": pedido.estado,
        "bloques_totales": pedido.bloques_totales,
        "bloques_traducidos": pedido.bloques_traducidos,
        "costo_usd": round(pedido.costo_usd or 0.0, 6),
        "error": pedido.error,
    }


@router.get("/documentos/{documento_id}/glosario/sugerencias")
async def sugerir_glosario(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Términos frecuentes del documento, para fijar antes de traducir.

    El motor propone por frecuencia y el usuario corrige. Sin glosario, cada
    llamada ve sólo su lote y el mismo término sale distinto en cada capítulo.
    """

    _documento(sesion, documento_id)

    bloques = (
        sesion.query(BloqueAlmacenado)
        .filter(BloqueAlmacenado.documento_id == documento_id)
        .all()
    )

    if not bloques:
        raise _error(
            "sin_bloques",
            "El documento no tiene bloques guardados. Hay que volver a subirlo.",
            409,
        )

    return {"sugerencias": extraer_terminos(bloques, contenido_de)}


@router.get("/documentos/{documento_id}/traducciones")
async def listar_traducciones(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Las traducciones pedidas para el documento, de la más nueva a la más vieja."""

    _documento(sesion, documento_id)

    pedidos = (
        sesion.query(TraduccionDocumento)
        .filter(TraduccionDocumento.documento_id == documento_id)
        .order_by(TraduccionDocumento.creada_en.desc())
        .all()
    )

    return [_serializar(p) for p in pedidos]


@router.post("/documentos/{documento_id}/traducciones", status_code=202)
async def pedir_traduccion(
    documento_id: str,
    pedido: PedidoTraduccion,
    sesion: Session = Depends(obtener_sesion),
):
    """Encola la traducción y devuelve enseguida.

    Traducir un documento grande son minutos y varios dólares, así que antes de
    encolar se dice cuántos bloques entran: el usuario tiene que poder ver el
    tamaño de lo que está pidiendo.
    """

    documento = _documento(sesion, documento_id)

    if documento.estado != "completado":
        raise _error(
            "documento_no_listo",
            "El documento todavía se está procesando",
            409,
        )

    bloques = (
        sesion.query(BloqueAlmacenado)
        .filter(BloqueAlmacenado.documento_id == documento_id)
        .all()
    )
    if not bloques:
        raise _error(
            "sin_bloques",
            "El documento no tiene bloques guardados. Hay que volver a subirlo.",
            409,
        )

    seleccion = pedido.seleccion.model_dump()
    elegidos = bloques_a_traducir(bloques, seleccion)

    if not elegidos:
        raise _error(
            "seleccion_vacia",
            "Con esa selección no queda ningún bloque traducible",
            400,
        )

    existente = (
        sesion.query(TraduccionDocumento)
        .filter(
            TraduccionDocumento.documento_id == documento_id,
            TraduccionDocumento.idioma == pedido.idioma,
        )
        .one_or_none()
    )
    if existente is not None and existente.estado in ("en_cola", "traduciendo"):
        raise _error(
            "traduccion_en_curso",
            f"Ya hay una traducción a {pedido.idioma} en curso",
            409,
        )

    # Rehacer una traducción reemplaza la anterior: tener dos versiones del mismo
    # idioma obligaría a elegir cuál exportar, sin ningún criterio para hacerlo.
    if existente is not None:
        sesion.delete(existente)
        sesion.flush()

    nuevo = TraduccionDocumento(
        id=str(uuid4()),
        documento_id=documento_id,
        idioma=pedido.idioma,
        descripcion=pedido.descripcion,
        tono=pedido.tono,
        glosario=pedido.glosario,
        seleccion=seleccion,
        estado="en_cola",
        bloques_totales=len(elegidos),
    )
    sesion.add(nuevo)
    sesion.commit()

    encolar_traduccion(nuevo.id)

    return _serializar(nuevo)


@router.delete("/documentos/{documento_id}/traducciones/{idioma}", status_code=204)
async def borrar_traduccion(
    documento_id: str,
    idioma: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Descarta una traducción con todos sus bloques."""

    _documento(sesion, documento_id)

    pedido = (
        sesion.query(TraduccionDocumento)
        .filter(
            TraduccionDocumento.documento_id == documento_id,
            TraduccionDocumento.idioma == idioma,
        )
        .one_or_none()
    )
    if pedido is None:
        raise _error("traduccion_no_encontrada", "No existe esa traducción", 404)

    sesion.delete(pedido)
    sesion.commit()

    from fastapi import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def mapa_traducido(sesion: Session, documento_id: str, idioma: str) -> dict[str, str]:
    """{bloque_id: texto traducido} para el idioma pedido.

    Lo usa el exportador. Un bloque sin entrada -una fórmula, o uno excluido por
    la selección- se exporta en su idioma original, que es el comportamiento
    correcto: traducir sólo los teoremas debe dejar el resto legible, no vacío.
    """

    pedido = (
        sesion.query(TraduccionDocumento)
        .filter(
            TraduccionDocumento.documento_id == documento_id,
            TraduccionDocumento.idioma == idioma,
        )
        .one_or_none()
    )
    if pedido is None:
        return {}

    filas = (
        sesion.query(TraduccionBloque)
        .filter(TraduccionBloque.traduccion_id == pedido.id)
        .all()
    )

    return {f.bloque_id: (f.contenido_final or f.contenido) for f in filas}
