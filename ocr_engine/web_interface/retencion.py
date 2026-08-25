"""Política de retención del PDF original y de las páginas renderizadas.

El PDF se conserva para poder renderizar sus páginas a demanda en el visor de
revisión, pero hasta ahora nadie lo borraba nunca: el directorio de datos crecía
sin techo y el archivo de un usuario quedaba guardado para siempre, sin que
existiera manera de eliminarlo ni siquiera pidiéndolo.

Son dos problemas distintos y se resuelven distinto:

- **Espacio.** El PDF sólo hace falta mientras alguien vaya a mirar sus páginas.
  Pasado un plazo se borra el archivo y se conservan los bloques, que son el
  resultado y pesan mucho menos. El documento queda legible y exportable; lo
  único que se pierde es la imagen de la página.
- **Privacidad.** El usuario tiene que poder borrar un documento suyo, y borrar
  la cuenta tiene que llevarse los archivos. Un borrado que deja los PDF en
  disco no es un borrado.

El caché de páginas renderizadas se trata aparte: es derivado y reconstruible,
así que se puede tirar antes y con menos ceremonia que el original.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ocr_engine.persistence import DocumentoAlmacenado, session_scope

from .almacen import borrar_cache, borrar_pdf

# Días que se conserva el PDF original. Pasado el plazo el documento sigue
# existiendo con sus bloques; deja de poder mostrarse la imagen de la página.
DIAS_RETENCION_PDF = int(os.environ.get("MOTOR_OCR_DIAS_RETENCION_PDF", "30"))


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(momento: datetime | None) -> datetime | None:
    """SQLite devuelve datetimes sin tzinfo; compararlos con uno aware explota."""
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def purgar_pdfs_vencidos(dias: int | None = None) -> int:
    """Borra los PDF que pasaron el plazo. Devuelve cuántos.

    Se llama al arrancar la API, igual que `marcar_colgados`. Es suficiente
    mientras haya una instancia; con varias conviene un trabajo programado para
    que no lo corran todas a la vez.
    """

    plazo = DIAS_RETENCION_PDF if dias is None else dias
    if plazo <= 0:  # 0 o negativo desactiva la purga
        return 0

    corte = _ahora() - timedelta(days=plazo)
    borrados = 0

    with session_scope() as sesion:
        documentos = sesion.scalars(
            select(DocumentoAlmacenado).where(DocumentoAlmacenado.ruta_pdf.is_not(None))
        ).all()

        for documento in documentos:
            creado = _con_tz(documento.creado_en)
            if creado is None or creado > corte:
                continue

            borrar_pdf(documento.ruta_pdf)
            borrar_cache(documento.id)
            # Se limpia la referencia para que el visor sepa que ya no está y
            # devuelva el 409 que explica por qué, en vez de un 500 al abrir.
            documento.ruta_pdf = None
            borrados += 1

    return borrados


def borrar_documento(sesion, documento: DocumentoAlmacenado) -> None:
    """Borra un documento con todo lo suyo: archivos incluidos.

    Los bloques, costos y decisiones se van por el ON DELETE CASCADE de sus
    claves foráneas; los archivos hay que borrarlos a mano porque viven fuera de
    la base.
    """

    borrar_pdf(documento.ruta_pdf)
    borrar_cache(documento.id)
    sesion.delete(documento)


def borrar_documentos_de_usuario(sesion, usuario_id: str) -> int:
    """Borra todos los documentos de un usuario, con sus archivos.

    Va acá y no en el borrado de la cuenta a secas porque el cascade de la base
    se lleva las filas pero no los PDF: la cuenta desaparecería y los archivos
    seguirían en disco.
    """

    documentos = sesion.scalars(
        select(DocumentoAlmacenado).where(DocumentoAlmacenado.usuario_id == usuario_id)
    ).all()

    for documento in documentos:
        borrar_documento(sesion, documento)

    return len(documentos)
