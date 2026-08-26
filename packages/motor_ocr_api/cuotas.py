"""Validación de la subida.

Dos controles que faltaban y que son de robustez, no de higiene:

- **Tamaño y forma del archivo.** `POST /procesar` aceptaba cualquier cosa de
  cualquier tamaño y la cargaba entera en memoria antes de mirarla. Un archivo de
  varios GB tumba el proceso sin necesidad de explotar nada.
- **Cantidad de páginas.** Un PDF chico puede declarar decenas de miles de
  páginas; el tamaño en disco no acota el trabajo que va a costar procesarlo.

No hay cuotas por plan: sin cuentas, no hay "plan" del que derivar un tope. El
único límite de tasa que queda es el de IP en `limites.py`.
"""

from __future__ import annotations

import io

from fastapi import HTTPException, status

# 50 MB cubre con holgura un libro escaneado; por encima de eso conviene que se
# parta el archivo, no que el servidor se lo aguante en memoria.
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
