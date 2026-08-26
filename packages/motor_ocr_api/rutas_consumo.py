"""Consumo y exportación (§9 y §10 del contrato).

El consumo es el de toda la instancia, no de una cuenta: sin usuarios ni
planes, no hay "cuánto gastó tal persona", sólo cuánto gastó el despliegue.

La exportación entrega el documento con `contenido_final` aplicado donde la
revisión humana lo haya dejado: si no lo hiciera, corregir un bloque en la
interfaz no cambiaría nada de lo que se descarga.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from motor_ocr_api.persistencia import (
    BloqueAlmacenado,
    CostoRegistrado,
    DocumentoAlmacenado,
    obtener_sesion,
)

import motor_ocr_render

router = APIRouter(tags=["consumo"])


def _rango(desde: str | None, hasta: str | None) -> tuple[datetime, datetime]:
    """Interpreta el rango pedido; por omisión, los últimos 30 días."""

    hoy = datetime.now(timezone.utc).date()

    try:
        fin = date.fromisoformat(hasta) if hasta else hoy
        inicio = date.fromisoformat(desde) if desde else fin - timedelta(days=29)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"codigo": "fecha_invalida", "detail": "Las fechas van en formato AAAA-MM-DD"},
        )

    if inicio > fin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"codigo": "rango_invalido", "detail": "`desde` es posterior a `hasta`"},
        )

    # `hasta` es inclusivo para quien lo lee, así que el corte va al día siguiente.
    return (
        datetime.combine(inicio, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(fin + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
    )


@router.get("/consumo")
async def obtener_consumo(
    desde: str | None = Query(default=None),
    hasta: str | None = Query(default=None),
    sesion: Session = Depends(obtener_sesion),
):
    """Consumo de la instancia en el rango pedido."""

    inicio, fin = _rango(desde, hasta)

    en_rango = [
        CostoRegistrado.registrado_en >= inicio,
        CostoRegistrado.registrado_en < fin,
    ]

    documentos, paginas = (
        sesion.query(
            func.count(DocumentoAlmacenado.id),
            func.coalesce(func.sum(DocumentoAlmacenado.total_paginas), 0),
        )
        .filter(
            DocumentoAlmacenado.creado_en >= inicio,
            DocumentoAlmacenado.creado_en < fin,
        )
        .one()
    )

    costo, entrada, salida, llamadas = (
        sesion.query(
            func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0),
            func.coalesce(func.sum(CostoRegistrado.tokens_entrada), 0),
            func.coalesce(func.sum(CostoRegistrado.tokens_salida), 0),
            func.count(CostoRegistrado.id),
        )
        .filter(*en_rango)
        .one()
    )

    # La serie se agrupa en la base y no en Python: traer cada llamada para
    # sumarlas acá no escala cuando el rango es de meses.
    dia = func.date(CostoRegistrado.registrado_en)
    filas_serie = (
        sesion.query(dia, CostoRegistrado.tipo_cola, func.sum(CostoRegistrado.costo_usd))
        .filter(*en_rango)
        .group_by(dia, CostoRegistrado.tipo_cola)
        .all()
    )

    serie: dict[str, dict] = {}
    for fecha, cola, monto in filas_serie:
        clave = str(fecha)
        entrada_dia = serie.setdefault(
            clave,
            {"fecha": clave, "micro_segmento_usd": 0.0, "inconsistencia_documental_usd": 0.0},
        )
        campo = f"{cola}_usd"
        if campo in entrada_dia:
            entrada_dia[campo] = round(float(monto or 0.0), 6)

    por_documento = (
        sesion.query(
            CostoRegistrado.documento_id,
            DocumentoAlmacenado.titulo,
            func.count(CostoRegistrado.id),
            func.coalesce(func.sum(CostoRegistrado.tokens_entrada), 0),
            func.coalesce(func.sum(CostoRegistrado.tokens_salida), 0),
            func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0),
        )
        .join(DocumentoAlmacenado, CostoRegistrado.documento_id == DocumentoAlmacenado.id)
        .filter(*en_rango)
        .group_by(CostoRegistrado.documento_id, DocumentoAlmacenado.titulo)
        .order_by(func.sum(CostoRegistrado.costo_usd).desc())
        .all()
    )

    return {
        "desde": inicio.date().isoformat(),
        "hasta": (fin - timedelta(days=1)).date().isoformat(),
        "totales": {
            "documentos": documentos or 0,
            "paginas": paginas or 0,
            "llamadas_llm": llamadas or 0,
            "tokens_entrada": entrada or 0,
            "tokens_salida": salida or 0,
            "costo_llm_usd": round(float(costo or 0.0), 6),
        },
        "serie_diaria": sorted(serie.values(), key=lambda d: d["fecha"]),
        "por_documento": [
            {
                "documento_id": doc_id,
                "titulo": titulo,
                "llamadas": n,
                "tokens_entrada": ent,
                "tokens_salida": sal,
                "costo_usd": round(float(monto or 0.0), 6),
            }
            for doc_id, titulo, n, ent, sal, monto in por_documento
        ],
    }


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
