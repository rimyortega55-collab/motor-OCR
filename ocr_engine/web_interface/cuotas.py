"""Validación de la subida y cuotas del plan.

Tres controles que faltaban y que en un servicio que cobra por cómputo e IA son
de costo, no de higiene:

- **Tamaño y forma del archivo.** `POST /procesar` aceptaba cualquier cosa de
  cualquier tamaño y la cargaba entera en memoria antes de mirarla. Un archivo de
  varios GB tumba el proceso sin necesidad de explotar nada.
- **Cantidad de páginas.** Un PDF chico puede declarar decenas de miles de
  páginas; el tamaño en disco no acota el trabajo que va a costar procesarlo.
- **Cuota del plan.** Los límites estaban definidos y se mostraban en la pantalla
  de consumo, pero no rechazaban nada: cualquier cuenta del plan libre podía
  procesar sin techo y gastar crédito real.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ocr_engine.persistence import CostoRegistrado, DocumentoAlmacenado, Usuario

# 50 MB cubre con holgura un libro escaneado; por encima de eso conviene que el
# usuario lo parta, no que el servidor se lo aguante en memoria.
MAXIMO_BYTES = 50 * 1024 * 1024
MAXIMO_PAGINAS = 1000


def _error(codigo: str, detalle: str, http: int) -> HTTPException:
    return HTTPException(status_code=http, detail={"codigo": codigo, "detail": detalle})


def validar_archivo(contenido: bytes) -> int:
    """Comprueba que sea un PDF razonable. Devuelve la cantidad de páginas.

    Se valida por los bytes y no por el `content-type` del formulario, que lo
    elige el cliente y por lo tanto no prueba nada.
    """

    if not contenido:
        raise _error("archivo_vacio", "El archivo llegó vacío", status.HTTP_400_BAD_REQUEST)

    if len(contenido) > MAXIMO_BYTES:
        raise _error(
            "archivo_demasiado_grande",
            f"El archivo pesa {len(contenido) / 1024 / 1024:.1f} MB y el máximo es "
            f"{MAXIMO_BYTES // 1024 // 1024} MB",
            status.HTTP_413_CONTENT_TOO_LARGE,
        )

    if not contenido.lstrip()[:5].startswith(b"%PDF-"):
        raise _error(
            "archivo_no_es_pdf",
            "El archivo no es un PDF",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    # Abrirlo acá y no en el worker permite rechazar un PDF ilegible con un error
    # inmediato, en vez de encolar un trabajo que va a morir dos minutos después.
    try:
        import pymupdf

        with pymupdf.open(stream=io.BytesIO(contenido), filetype="pdf") as doc:
            paginas = len(doc)
    except Exception as e:
        raise _error(
            "pdf_ilegible",
            f"No se pudo abrir el PDF: {e}",
            status.HTTP_400_BAD_REQUEST,
        )

    if paginas == 0:
        raise _error("pdf_sin_paginas", "El PDF no tiene páginas", status.HTTP_400_BAD_REQUEST)

    if paginas > MAXIMO_PAGINAS:
        raise _error(
            "demasiadas_paginas",
            f"El PDF tiene {paginas} páginas y el máximo por documento es {MAXIMO_PAGINAS}",
            status.HTTP_413_CONTENT_TOO_LARGE,
        )

    return paginas


def _inicio_del_mes() -> datetime:
    ahora = datetime.now(timezone.utc)
    return ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def consumo_del_mes(sesion: Session, usuario: Usuario) -> tuple[int, float]:
    """Páginas procesadas y gasto en LLM del usuario en el mes en curso."""

    desde = _inicio_del_mes()

    paginas = (
        sesion.query(func.coalesce(func.sum(DocumentoAlmacenado.total_paginas), 0))
        .filter(
            DocumentoAlmacenado.usuario_id == usuario.id,
            DocumentoAlmacenado.creado_en >= desde,
        )
        .scalar()
    ) or 0

    gasto = (
        sesion.query(func.coalesce(func.sum(CostoRegistrado.costo_usd), 0.0))
        .filter(
            CostoRegistrado.usuario_id == usuario.id,
            CostoRegistrado.registrado_en >= desde,
        )
        .scalar()
    ) or 0.0

    return int(paginas), float(gasto)


def exigir_cuota(sesion: Session, usuario: Usuario, paginas_nuevas: int) -> None:
    """Corta con 402 si el documento haría superar la cuota del plan.

    Se cuentan las páginas del documento que está por entrar, no sólo las ya
    consumidas: aceptarlo y recién después notar que se pasó significaría haber
    gastado el cómputo igual.
    """

    from .rutas_consumo import LIMITES_POR_PLAN

    limites = LIMITES_POR_PLAN.get(usuario.plan, LIMITES_POR_PLAN["libre"])
    tope_paginas = limites.get("paginas_mes")
    tope_gasto = limites.get("gasto_llm_mes_usd")

    paginas, gasto = consumo_del_mes(sesion, usuario)

    if tope_paginas is not None and paginas + paginas_nuevas > tope_paginas:
        raise _error(
            "limite_plan_superado",
            f"El plan {usuario.plan} permite {tope_paginas} páginas por mes. "
            f"Llevás {paginas} y este documento suma {paginas_nuevas}.",
            status.HTTP_402_PAYMENT_REQUIRED,
        )

    if tope_gasto is not None and gasto >= tope_gasto:
        raise _error(
            "limite_gasto_superado",
            f"El plan {usuario.plan} permite {tope_gasto} USD de escalación al mes "
            f"y ya llevás {gasto:.4f}.",
            status.HTTP_402_PAYMENT_REQUIRED,
        )
