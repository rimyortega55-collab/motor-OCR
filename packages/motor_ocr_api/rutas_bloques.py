"""Bloques y páginas de un documento: lo que alimenta el visor de revisión.

Hasta el paso 3, `GET /documentos/{id}` sólo devolvía un resumen con conteos, así
que la revisión bloque a bloque no tenía de dónde leer y la Capa 6 seguía siendo
una CLI. Acá están las dos piezas que faltaban: los bloques con su contenido y su
bbox, y la imagen de la página para dibujar el overlay encima.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from motor_ocr_api.persistencia import BloqueAlmacenado, DocumentoAlmacenado, obtener_sesion

from . import almacen

router = APIRouter(tags=["bloques"])

LIMITE_MAXIMO = 200


def _error(codigo: str, detalle: str, http: int) -> HTTPException:
    return HTTPException(status_code=http, detail={"codigo": codigo, "detail": detalle})


def _documento(sesion: Session, documento_id: str) -> DocumentoAlmacenado:
    documento = sesion.get(DocumentoAlmacenado, documento_id)
    if documento is None:
        raise _error("no_encontrado", "Documento no encontrado", 404)
    return documento


def _cifrar_cursor(pagina: int, orden: int) -> str:
    return base64.urlsafe_b64encode(f"{pagina}:{orden}".encode()).decode("ascii")


def _descifrar_cursor(cursor: str) -> tuple[int, int]:
    try:
        pagina, orden = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        return int(pagina), int(orden)
    except (ValueError, TypeError, binascii.Error):
        raise _error("cursor_invalido", "El cursor no es válido", 400)


def _serializar(bloque: BloqueAlmacenado, incluir: set[str]) -> dict:
    cuerpo = {
        "id": bloque.id,
        "pagina": bloque.pagina,
        "orden_lectura": bloque.orden_lectura,
        "tipo": bloque.tipo,
        "origen_contenido": bloque.origen_contenido,
        "bbox": bloque.bbox,
        "confianza_layout": bloque.confianza_layout,
        "confianza_global": bloque.confianza_global,
        "texto_plano": bloque.texto_plano,
        "latex": bloque.latex,
        "contenido_final": bloque.contenido_final,
        "estado_revision": bloque.estado_revision,
    }

    # Por defecto no viajan: son pesados y la tabla de bloques no los necesita.
    # El visor los pide sólo para el bloque que está mostrando.
    if "micro_segmentos" in incluir:
        cuerpo["micro_segmentos"] = bloque.micro_segmentos or []
    if "escalacion" in incluir:
        cuerpo["escalacion"] = bloque.escalacion

    return cuerpo


@router.get("/documentos/{documento_id}/bloques")
async def listar_bloques(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
    pagina: int | None = None,
    tipo: list[str] | None = Query(default=None),
    confianza_max: float | None = None,
    estado_revision: str | None = None,
    orden: str = "lectura",
    limite: int = 100,
    cursor: str | None = None,
    incluir: str | None = None,
):
    """Bloques del documento, filtrables y paginados.

    La cola de revisión no es un endpoint aparte: es este mismo con
    `?estado_revision=pendiente&orden=confianza`. Uno separado duplicaría todos
    los filtros para devolver las mismas filas.
    """

    documento = _documento(sesion, documento_id)
    limite = max(1, min(limite, LIMITE_MAXIMO))
    campos = {c.strip() for c in (incluir or "").split(",") if c.strip()}

    consulta = sesion.query(BloqueAlmacenado).filter(
        BloqueAlmacenado.documento_id == documento.id
    )

    if pagina is not None:
        consulta = consulta.filter(BloqueAlmacenado.pagina == pagina)
    if tipo:
        consulta = consulta.filter(BloqueAlmacenado.tipo.in_(tipo))
    if estado_revision:
        consulta = consulta.filter(BloqueAlmacenado.estado_revision == estado_revision)
    if confianza_max is not None:
        consulta = consulta.filter(BloqueAlmacenado.confianza_global <= confianza_max)

    total = consulta.count()

    if orden == "confianza":
        # Para revisar, lo peor primero: es donde el tiempo de una persona rinde.
        # Los bloques sin confianza (texto nativo) van al final.
        consulta = consulta.order_by(
            BloqueAlmacenado.confianza_global.is_(None),
            BloqueAlmacenado.confianza_global.asc(),
            BloqueAlmacenado.pagina,
            BloqueAlmacenado.orden_lectura,
        )
        if cursor:
            raise _error(
                "cursor_no_soportado",
                "El orden por confianza no admite cursor; usá limite y filtros",
                400,
            )
        bloques = consulta.limit(limite).all()
        siguiente = None
    else:
        consulta = consulta.order_by(BloqueAlmacenado.pagina, BloqueAlmacenado.orden_lectura)
        if cursor:
            pagina_corte, orden_corte = _descifrar_cursor(cursor)
            # Keyset sobre (pagina, orden_lectura): con 30 000 bloques, OFFSET
            # obliga a la base a recorrer todo lo salteado en cada página.
            consulta = consulta.filter(
                (BloqueAlmacenado.pagina > pagina_corte)
                | (
                    (BloqueAlmacenado.pagina == pagina_corte)
                    & (BloqueAlmacenado.orden_lectura > orden_corte)
                )
            )

        bloques = consulta.limit(limite + 1).all()
        hay_mas = len(bloques) > limite
        bloques = bloques[:limite]
        siguiente = (
            _cifrar_cursor(bloques[-1].pagina, bloques[-1].orden_lectura)
            if hay_mas and bloques
            else None
        )

    return {
        "items": [_serializar(b, campos) for b in bloques],
        "siguiente_cursor": siguiente,
        "total": total,
    }


@router.get("/documentos/{documento_id}/bloques/{bloque_id}")
async def obtener_bloque(
    documento_id: str,
    bloque_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Un bloque con todo: micro-segmentos y resultado del modelo incluidos."""

    documento = _documento(sesion, documento_id)

    bloque = (
        sesion.query(BloqueAlmacenado)
        .filter(
            BloqueAlmacenado.id == bloque_id,
            BloqueAlmacenado.documento_id == documento.id,
        )
        .one_or_none()
    )
    if bloque is None:
        raise _error("no_encontrado", "Bloque no encontrado", 404)

    return _serializar(bloque, {"micro_segmentos", "escalacion"})


@router.get("/documentos/{documento_id}/paginas")
async def listar_paginas(
    documento_id: str,
    sesion: Session = Depends(obtener_sesion),
):
    """Tamaño en píxeles de cada página y cuántos bloques tiene.

    El frontend necesita las dimensiones para desnormalizar los bbox y reservar
    el espacio de la imagen antes de que cargue, sin saltos de layout.
    """

    documento = _documento(sesion, documento_id)
    ruta = almacen.ruta_absoluta(documento.ruta_pdf)

    if ruta is None:
        raise _error(
            "pdf_no_disponible",
            "El PDF original no está guardado. Los documentos procesados antes "
            "del paso 3 no lo conservan: hay que volver a subirlos.",
            409,
        )

    conteos = dict(
        sesion.query(BloqueAlmacenado.pagina, func.count(BloqueAlmacenado.id))
        .filter(BloqueAlmacenado.documento_id == documento.id)
        .group_by(BloqueAlmacenado.pagina)
        .all()
    )

    paginas = almacen.dimensiones(ruta)
    for entrada in paginas:
        entrada["bloques"] = conteos.get(entrada["pagina"], 0)

    return {"total_paginas": len(paginas), "paginas": paginas}


@router.get("/documentos/{documento_id}/paginas/{numero}")
async def imagen_pagina(
    documento_id: str,
    numero: int,
    sesion: Session = Depends(obtener_sesion),
    ancho: int | None = None,
):
    """PNG de una página, para dibujarle el overlay de bloques encima.

    Se sirve la página completa y no el recorte del bloque: así una misma imagen
    —y una misma entrada de caché— sirve para todos los bloques de esa página.
    """

    documento = _documento(sesion, documento_id)
    ruta = almacen.ruta_absoluta(documento.ruta_pdf)

    if ruta is None:
        raise _error("pdf_no_disponible", "El PDF original no está guardado", 409)

    imagen = almacen.renderizar_pagina(documento.id, ruta, numero, ancho)
    if imagen is None:
        raise _error("no_encontrado", "Esa página no existe en el documento", 404)

    return FileResponse(
        imagen,
        media_type="image/png",
        headers={
            # Privado: la imagen es de un documento propio de esta instancia,
            # no la puede cachear un proxy compartido.
            "Cache-Control": "private, max-age=86400",
            "ETag": f'"{documento.id}:{numero}:{ancho or almacen.DPI_VISOR}"',
        },
    )
