"""Acceso a la instancia: sin cuentas, una clave única opcional.

El proyecto es open source y de un solo operador: no hay usuarios, planes ni
API keys por cuenta. Lo único que existe es una clave de acceso opcional
(`MOTOR_OCR_CLAVE_ACCESO`) para no dejar la instancia completamente abierta
cuando se expone en red; sin esa variable, la API no pide nada, como
corresponde a correrla en una notebook.

La clave se compara con `hmac.compare_digest` y, si coincide, se abre una
cookie HttpOnly con un token generado una vez por proceso: no hace falta base
de datos para esto, y reiniciar el proceso invalida todo lo abierto, que es
aceptable para una sola instancia sin cuentas que preservar.
"""

from __future__ import annotations

import hmac
import os
import secrets

from fastapi import Cookie, HTTPException, status

COOKIE_ACCESO = "motor_ocr_acceso"

# Token de proceso: se genera una vez al importar el módulo y es lo que viaja
# en la cookie tras una clave correcta. No es un secreto por cuenta -no hay
# cuentas- sino la prueba de que, en este proceso, alguien tecleó la clave
# correcta.
_TOKEN_PROCESO = secrets.token_urlsafe(32)


def clave_configurada() -> str | None:
    """La clave de acceso, si el operador definió una. `None` = instancia abierta."""
    return os.environ.get("MOTOR_OCR_CLAVE_ACCESO") or None


def cookie_segura() -> bool:
    """`Secure` en la cookie salvo que se apague explícitamente.

    Los navegadores tratan `http://localhost` como contexto seguro, así que el
    valor por defecto no estorba en desarrollo. Se apaga con
    MOTOR_OCR_COOKIE_SEGURA=0 para servir por HTTP en una red interna.
    """
    return os.environ.get("MOTOR_OCR_COOKIE_SEGURA", "1") not in ("0", "false", "False")


def clave_valida(clave: str) -> bool:
    esperada = clave_configurada()
    return esperada is not None and hmac.compare_digest(clave, esperada)


def token_de_acceso() -> str:
    return _TOKEN_PROCESO


def exigir_acceso(
    motor_ocr_acceso: str | None = Cookie(default=None, alias=COOKIE_ACCESO),
) -> None:
    """Dependencia de FastAPI: corta con 401 si la instancia pide clave y no hay cookie válida.

    Sin `MOTOR_OCR_CLAVE_ACCESO` configurada, esto no hace nada: es el caso de
    uso local, de un solo operador, sin nada que exponer.
    """
    if clave_configurada() is None:
        return

    if motor_ocr_acceso is None or not hmac.compare_digest(motor_ocr_acceso, _TOKEN_PROCESO):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "codigo": "acceso_requerido",
                "detail": "Esta instancia requiere clave de acceso",
            },
        )
