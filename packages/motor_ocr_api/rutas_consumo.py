"""Exportación (§10 del contrato).

La exportación entrega el documento con `contenido_final` aplicado donde la
revisión humana lo haya dejado: si no lo hiciera, corregir un bloque en la
interfaz no cambiaría nada de lo que se descarga.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from motor_ocr_api.persistencia import (
    BloqueAlmacenado,
    DocumentoAlmacenado,
    obtener_sesion,
)

import motor_ocr_render

router = APIRouter(tags=["exportacion"])


# ============================================================================
# EXPORTACIÓN
# ============================================================================

def _documento(sesion: Session, documento_id: str) -> DocumentoAlmacenado:
    documento = sesion.get(DocumentoAlmacenado, documento_id)
    if documento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"codigo": "documento_no_encontrado", "detail": "No existe ese documento"},
        )
    return documento


def _bloques_ordenados(sesion: Session, documento_id: str) -> list[BloqueAlmacenado]:
    return (
        sesion.query(BloqueAlmacenado)
        .filter(BloqueAlmacenado.documento_id == documento_id)
        .order_by(BloqueAlmacenado.pagina, BloqueAlmacenado.orden_lectura)
        .all()
    )


def _adjunto(nombre: str) -> str:
    """Cabecera Content-Disposition que tolera acentos en el nombre.

    Las cabeceras HTTP se codifican en latin-1, así que un título con "ñ" o el
    sufijo del idioma rompían la respuesta con UnicodeDecodeError antes de
    llegar al navegador. Se manda el nombre dos veces, como pide la RFC 5987:
    una versión ASCII para clientes viejos y la real en `filename*`.
    """
    from urllib.parse import quote

    ascii_seguro = nombre.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return (
        f'attachment; filename="{ascii_seguro}"; '
        f"filename*=UTF-8''{quote(nombre, safe='')}"
    )


@router.get("/documentos/{documento_id}/export")
async def exportar(
    documento_id: str,
    formato: str = Query(default="graphify"),
    idioma: str | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
):
    """Descarga el documento con las correcciones humanas aplicadas.

    Con `idioma`, entrega la traducción a ese idioma. Es acá y no antes donde la
    traducción tiene sentido: el contenido ya está corregido, se paga sólo si
    alguien la pide, y de un mismo procesamiento salen todos los idiomas.
    """

    if formato not in motor_ocr_render.FORMATOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "codigo": "formato_desconocido",
                "detail": f"Formatos válidos: {', '.join(motor_ocr_render.FORMATOS)}",
            },
        )

    documento = _documento(sesion, documento_id)
    bloques = _bloques_ordenados(sesion, documento_id)

    if not bloques:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": "sin_bloques",
                "detail": (
                    "El documento no tiene bloques guardados. Los procesados antes "
                    "de que existiera la tabla `bloques` hay que volver a subirlos."
                ),
            },
        )

    if idioma:
        from .rutas_traduccion import mapa_traducido

        traducciones = mapa_traducido(sesion, documento_id, idioma)
        if not traducciones:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "codigo": "sin_traduccion",
                    "detail": f"No hay una traducción a {idioma} para este documento",
                },
            )

        # Se sustituye el contenido en memoria, sin tocar la base: el bloque
        # conserva su texto original y la traducción es una vista sobre él.
        for bloque in bloques:
            traducido = traducciones.get(bloque.id)
            if traducido:
                bloque.contenido_final = traducido

    salida = motor_ocr_render.FORMATOS[formato]
    cuerpo = salida.renderizar(
        motor_ocr_render.DocumentoRenderizable(
            titulo=documento.titulo,
            id=documento.id,
            total_paginas=documento.total_paginas,
        ),
        [motor_ocr_render.desde_almacenado(b) for b in bloques],
    )
    tipo_mime, extension = salida.mime, salida.extension

    base = documento.titulo.rsplit(".", 1)[0] or "documento"
    if idioma:
        base = f"{base}.{idioma}"
    # Se transmite en vez de devolverlo entero: un documento de 30 000 bloques
    # son varios megabytes de texto que no conviene armar en memoria dos veces.
    return StreamingResponse(
        io.BytesIO(cuerpo.encode("utf-8")),
        media_type=tipo_mime,
        headers={"Content-Disposition": _adjunto(f"{base}.{extension}")},
    )
