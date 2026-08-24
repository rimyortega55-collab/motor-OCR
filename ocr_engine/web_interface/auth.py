"""Autenticación por API key para la API del motor.

Sin esto no hay forma de saber quién consume ni de cobrarle: cualquiera con la
URL usaría el motor. Cada request trae su clave en la cabecera `X-API-Key` y el
usuario resuelto queda disponible para atribuir documentos y costos.

Las claves se guardan hasheadas con SHA-256. No se usa un hash lento tipo bcrypt
a propósito: una API key es un secreto aleatorio de 256 bits, no una contraseña
elegida por una persona, así que no hay diccionario que probar y el hash rápido
permite validarla en cada request sin volverse el cuello de botella.
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ocr_engine.persistence import Usuario, get_session

PREFIJO_CLAVE = "moc_"


def generar_api_key() -> tuple[str, str, str]:
    """Devuelve (clave_en_claro, hash, prefijo).

    La clave en claro se muestra una única vez, al crearla: después sólo queda
    el hash, así que ni siquiera el operador de la base puede recuperarla.
    """
    clave = PREFIJO_CLAVE + secrets.token_urlsafe(32)
    return clave, hashear_api_key(clave), clave[: len(PREFIJO_CLAVE) + 8]


def hashear_api_key(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def crear_usuario(
    sesion: Session, nombre: str, email: str | None = None, plan: str = "libre"
) -> tuple[Usuario, str]:
    """Alta de usuario. Devuelve el usuario y su clave en claro (irrecuperable después)."""
    clave, hash_clave, prefijo = generar_api_key()

    usuario = Usuario(
        id=str(uuid4()),
        nombre=nombre,
        email=email,
        api_key_hash=hash_clave,
        api_key_prefijo=prefijo,
        plan=plan,
    )
    sesion.add(usuario)
    sesion.flush()

    return usuario, clave


def obtener_sesion():
    """Dependencia de FastAPI: una sesión de base por request."""
    sesion = get_session()
    try:
        yield sesion
    finally:
        sesion.close()


def usuario_actual(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    sesion: Session = Depends(obtener_sesion),
) -> Usuario:
    """Resuelve el usuario dueño de la API key, o corta el request."""

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta la cabecera X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    usuario = (
        sesion.query(Usuario)
        .filter(Usuario.api_key_hash == hashear_api_key(x_api_key))
        .one_or_none()
    )

    # Mismo mensaje para clave inexistente y clave mal formada: distinguirlos le
    # confirmaría a quien prueba claves cuáles existen.
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta está desactivada",
        )

    return usuario
