"""Acceso a la instancia: sin cuentas, una clave única opcional.

El proyecto es open source y de un solo operador: no hay usuarios, planes ni
API keys por cuenta. Lo único que existe es una clave de acceso opcional
(`MOTOR_OCR_CLAVE_ACCESO`) para no dejar la instancia completamente abierta
cuando se expone en red; sin esa variable, la API no pide nada, como
corresponde a correrla en una notebook.

La clave puede venir del entorno o, desde que existe el panel de
administración, de una fila en la base (`ClaveAccesoInstancia`) que el
operador rota o revoca en caliente. La fila manda apenas se rota una vez; sin
fila, se sigue leyendo la variable de entorno, así que una instancia que nunca
tocó el panel se sigue comportando exactamente igual que antes.

La clave se compara con `hmac.compare_digest` y, si coincide, se abre una
cookie HttpOnly con un token generado una vez por proceso: no hace falta base
de datos para esto, y regenerar ese token —al reiniciar el proceso o al rotar
o revocar la clave desde el panel— invalida todo lo abierto, que es aceptable
para una sola instancia sin cuentas que preservar.
"""

from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .persistencia import ClaveAccesoInstancia
from .persistencia.db import obtener_sesion

COOKIE_ACCESO = "motor_ocr_acceso"

# Token de proceso: se genera al importar el módulo y es lo que viaja en la
# cookie tras una clave correcta. No es un secreto por cuenta -no hay
# cuentas- sino la prueba de que, en este proceso, alguien tecleó la clave
# correcta. Rotarlo (al reiniciar, o a pedido desde el panel) es lo que cierra
# de verdad las sesiones ya abiertas, sin tocar la clave configurada.
_token_proceso = secrets.token_urlsafe(32)


def _fila_clave(sesion: Session) -> ClaveAccesoInstancia | None:
    return sesion.get(ClaveAccesoInstancia, "global")


def clave_configurada(sesion: Session | None = None) -> str | None:
    """La clave de acceso vigente, si hay una. `None` = instancia abierta.

    Si el panel rotó una clave alguna vez, esa fila de la base manda. Si
    nunca se tocó el panel (o `sesion` no viaja, como en el arranque del
    proceso), se sigue leyendo `MOTOR_OCR_CLAVE_ACCESO` del entorno.
    """
    if sesion is not None:
        fila = _fila_clave(sesion)
        if fila is not None and fila.clave:
            return fila.clave
    return os.environ.get("MOTOR_OCR_CLAVE_ACCESO") or None


def origen_clave(sesion: Session) -> str | None:
    """De dónde sale la clave vigente: "panel", "entorno", o `None` si no hay."""
    fila = _fila_clave(sesion)
    if fila is not None and fila.clave:
        return "panel"
    if os.environ.get("MOTOR_OCR_CLAVE_ACCESO"):
        return "entorno"
    return None


def rotada_en(sesion: Session) -> datetime | None:
    fila = _fila_clave(sesion)
    return fila.rotada_en if fila is not None else None


def cookie_segura() -> bool:
    """`Secure` en la cookie salvo que se apague explícitamente.

    Los navegadores tratan `http://localhost` como contexto seguro, así que el
    valor por defecto no estorba en desarrollo. Se apaga con
    MOTOR_OCR_COOKIE_SEGURA=0 para servir por HTTP en una red interna.
    """
    return os.environ.get("MOTOR_OCR_COOKIE_SEGURA", "1") not in ("0", "false", "False")


def clave_valida(clave: str, sesion: Session) -> bool:
    esperada = clave_configurada(sesion)
    return esperada is not None and hmac.compare_digest(clave, esperada)


def token_de_acceso() -> str:
    return _token_proceso


def _regenerar_token_proceso() -> None:
    global _token_proceso
    _token_proceso = secrets.token_urlsafe(32)


def rotar_clave(sesion: Session) -> str:
    """Genera una clave nueva, la guarda y cierra las sesiones ya abiertas.

    La clave sale de `secrets.token_urlsafe`, igual que el token de proceso:
    no se acepta una clave elegida a mano porque el punto de rotar es no
    depender de que el operador piense una clave fuerte. Se devuelve en claro
    una única vez, en la respuesta de este llamado — después de esto no vuelve
    a mostrarse, igual que un token de proveedor.
    """
    nueva = secrets.token_urlsafe(24)
    fila = _fila_clave(sesion)
    if fila is None:
        fila = ClaveAccesoInstancia(id="global")
        sesion.add(fila)
    fila.clave = nueva
    fila.rotada_en = datetime.now(timezone.utc)
    sesion.commit()

    _regenerar_token_proceso()
    return nueva


def revocar_clave(sesion: Session) -> None:
    """Borra la clave guardada en el panel y cierra las sesiones ya abiertas.

    Sin fila con clave en la base, `clave_configurada` vuelve a mirar el
    entorno: si `MOTOR_OCR_CLAVE_ACCESO` sigue seteada ahí, la instancia sigue
    pidiendo esa clave; si no, queda abierta.
    """
    fila = _fila_clave(sesion)
    if fila is not None:
        fila.clave = None
        fila.rotada_en = datetime.now(timezone.utc)
        sesion.commit()

    _regenerar_token_proceso()


def exigir_acceso(
    motor_ocr_acceso: str | None = Cookie(default=None, alias=COOKIE_ACCESO),
    sesion: Session = Depends(obtener_sesion),
) -> None:
    """Dependencia de FastAPI: corta con 401 si la instancia pide clave y no hay cookie válida.

    Sin clave configurada (ni por panel ni por entorno), esto no hace nada: es
    el caso de uso local, de un solo operador, sin nada que exponer.
    """
    if clave_configurada(sesion) is None:
        return

    if motor_ocr_acceso is None or not hmac.compare_digest(motor_ocr_acceso, _token_proceso):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "codigo": "acceso_requerido",
                "detail": "Esta instancia requiere clave de acceso",
            },
        )
