"""Consumo y exportación (§9 y §10 del contrato).

El consumo amplía los totales que ya existían con la serie diaria y el desglose
por documento y por cola, que es lo que necesita la pantalla para explicar de
dónde salió el gasto en vez de mostrar un único número.

La exportación entrega el documento con `contenido_final` aplicado donde la
revisión humana lo dejó: si no lo hiciera, corregir un bloque en la interfaz no
cambiaría nada de lo que el usuario se lleva.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ocr_engine.persistence import (
    BloqueAlmacenado,
    CostoRegistrado,
    DocumentoAlmacenado,
    Usuario,
)

from .auth import obtener_sesion, usuario_actual

router = APIRouter(tags=["consumo"])


# Los planes son hoy sólo el string `usuarios.plan`. Se definen acá para poder
# mostrar la barra de consumo; el rechazo con 402 al superarlos todavía no está
# conectado, así que la interfaz debe mostrarlos como referencia y no como tope
# efectivo.
LIMITES_POR_PLAN = {
    "libre": {"paginas_mes": 200, "gasto_llm_mes_usd": 2.0},
    "pro": {"paginas_mes": 5000, "gasto_llm_mes_usd": 50.0},
    "ilimitado": {"paginas_mes": None, "gasto_llm_mes_usd": None},
}


def _limites(plan: str) -> dict:
    return LIMITES_POR_PLAN.get(plan, LIMITES_POR_PLAN["libre"])


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
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Consumo del usuario en el rango pedido. Es la base para facturar."""

    inicio, fin = _rango(desde, hasta)

    en_rango = [
        CostoRegistrado.usuario_id == usuario.id,
        CostoRegistrado.registrado_en >= inicio,
        CostoRegistrado.registrado_en < fin,
    ]

    documentos, paginas = (
        sesion.query(
            func.count(DocumentoAlmacenado.id),
            func.coalesce(func.sum(DocumentoAlmacenado.total_paginas), 0),
        )
        .filter(
            DocumentoAlmacenado.usuario_id == usuario.id,
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
        "usuario": usuario.nombre,
        "plan": usuario.plan,
        "desde": inicio.date().isoformat(),
        "hasta": (fin - timedelta(days=1)).date().isoformat(),
        "limites": _limites(usuario.plan),
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

def _documento_del_usuario(
    sesion: Session, usuario: Usuario, documento_id: str
) -> DocumentoAlmacenado:
    documento = (
        sesion.query(DocumentoAlmacenado)
        .filter(
            DocumentoAlmacenado.id == documento_id,
            DocumentoAlmacenado.usuario_id == usuario.id,
        )
        .one_or_none()
    )
    if documento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"codigo": "documento_no_encontrado", "detail": "No existe ese documento"},
        )
    return documento


def _contenido(bloque: BloqueAlmacenado) -> str:
    """Lo que vale para exportar, en orden de prioridad.

    `contenido_final` primero: si la revisión humana corrigió un bloque y la
    exportación siguiera entregando el texto del motor, revisar no serviría de
    nada. Después el LaTeX, que es más fiel que el texto plano para fórmulas.
    """
    return bloque.contenido_final or bloque.latex or bloque.texto_plano or ""


def _bloques_ordenados(sesion: Session, documento_id: str) -> list[BloqueAlmacenado]:
    return (
        sesion.query(BloqueAlmacenado)
        .filter(BloqueAlmacenado.documento_id == documento_id)
        .order_by(BloqueAlmacenado.pagina, BloqueAlmacenado.orden_lectura)
        .all()
    )


# Tipos que en Markdown llevan encabezado, y con qué nivel.
_NIVEL_ENCABEZADO = {"encabezado": "##", "titulo": "#"}


def _a_markdown(documento: DocumentoAlmacenado, bloques: list[BloqueAlmacenado]) -> str:
    partes = [f"# {documento.titulo}", ""]
    pagina_actual = None

    for bloque in bloques:
        texto = _contenido(bloque).strip()
        if not texto:
            continue

        if bloque.pagina != pagina_actual:
            pagina_actual = bloque.pagina
            partes.append(f"<!-- página {pagina_actual + 1} -->")
            partes.append("")

        prefijo = _NIVEL_ENCABEZADO.get(bloque.tipo)
        if prefijo:
            partes.append(f"{prefijo} {texto}")
        elif bloque.tipo == "formula_display":
            partes.append(f"$$\n{texto}\n$$")
        elif bloque.tipo == "codigo":
            partes.append(f"```\n{texto}\n```")
        else:
            partes.append(texto)
        partes.append("")

    return "\n".join(partes)


def _a_ipynb(documento: DocumentoAlmacenado, bloques: list[BloqueAlmacenado]) -> str:
    celdas = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [f"# {documento.titulo}"],
        }
    ]

    for bloque in bloques:
        texto = _contenido(bloque).strip()
        if not texto:
            continue

        if bloque.tipo == "codigo":
            celdas.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": texto.splitlines(keepends=True),
            })
        else:
            fuente = f"$$\n{texto}\n$$" if bloque.tipo == "formula_display" else texto
            celdas.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": fuente.splitlines(keepends=True),
            })

    cuaderno = {
        "cells": celdas,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(cuaderno, ensure_ascii=False, indent=1)


def _a_graphify(documento: DocumentoAlmacenado, bloques: list[BloqueAlmacenado]) -> str:
    salida = {
        "documento_id": documento.id,
        "titulo": documento.titulo,
        "total_paginas": documento.total_paginas,
        "total_bloques": len(bloques),
        "bloques": [
            {
                "id": b.id,
                "pagina": b.pagina,
                "orden_lectura": b.orden_lectura,
                "tipo": b.tipo,
                "origen_contenido": b.origen_contenido,
                "bbox": b.bbox,
                "confianza_global": b.confianza_global,
                "contenido": _contenido(b),
                # Se declara si lo revisó una persona: quien indexe esto necesita
                # poder distinguir lo verificado de lo que sólo pasó por el motor.
                "revisado_por_humano": b.estado_revision == "resuelto",
            }
            for b in bloques
        ],
    }
    return json.dumps(salida, ensure_ascii=False, indent=2)


_FORMATOS = {
    "graphify": (_a_graphify, "application/json", "json"),
    "markdown": (_a_markdown, "text/markdown; charset=utf-8", "md"),
    "ipynb": (_a_ipynb, "application/x-ipynb+json", "ipynb"),
}


@router.get("/documentos/{documento_id}/export")
async def exportar(
    documento_id: str,
    formato: str = Query(default="graphify"),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
):
    """Descarga el documento con las correcciones humanas aplicadas."""

    if formato not in _FORMATOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "codigo": "formato_desconocido",
                "detail": f"Formatos válidos: {', '.join(_FORMATOS)}",
            },
        )

    documento = _documento_del_usuario(sesion, usuario, documento_id)
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

    render, tipo_mime, extension = _FORMATOS[formato]
    cuerpo = render(documento, bloques)

    base = documento.titulo.rsplit(".", 1)[0] or "documento"
    # Se transmite en vez de devolverlo entero: un documento de 30 000 bloques
    # son varios megabytes de texto que no conviene armar en memoria dos veces.
    return StreamingResponse(
        io.BytesIO(cuerpo.encode("utf-8")),
        media_type=tipo_mime,
        headers={"Content-Disposition": f'attachment; filename="{base}.{extension}"'},
    )
