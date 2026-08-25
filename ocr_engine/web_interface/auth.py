"""Autenticación: sesión de navegador y API key.

Dos credenciales que resuelven al mismo `Usuario`:

- **Navegador**: cookie `motor_ocr_sesion`, HttpOnly. Es lo que usa el SPA. La
  API key no se guarda en `localStorage` a propósito: es un secreto de larga
  vida y cualquier XSS se la lleva, mientras que una sesión se revoca y expira.
- **Máquinas**: cabecera `X-API-Key`, como antes.

Los dos secretos se guardan hasheados, pero con algoritmos distintos y por
razones distintas:

- La API key es un secreto aleatorio de 256 bits. No hay diccionario que probar,
  así que SHA-256 alcanza y permite validarla en cada request sin volverse el
  cuello de botella.
- La contraseña la elige una persona, así que sí es atacable por diccionario y
  necesita un hash lento. Se usa `hashlib.scrypt`, que viene en la biblioteca
  estándar: evita sumar una dependencia con extensiones en C que compilar.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ocr_engine.persistence import ApiKey, Sesion, Usuario, get_session

PREFIJO_CLAVE = "moc_"
COOKIE_SESION = "motor_ocr_sesion"
DIAS_SESION = 14

# scrypt con los parámetros que recomienda la documentación de Python para uso
# interactivo: ~16 MB de memoria y decenas de milisegundos por verificación.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32

# Escribir `ultimo_uso_en` en cada request serializaría la base con SQLite. Con
# granularidad de un minuto el dato sigue sirviendo para "último uso hace 3 h" y
# el 99 % de los requests no escribe nada.
_GRANULARIDAD_USO = timedelta(minutes=1)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(momento: datetime | None) -> datetime | None:
    """SQLite devuelve datetimes sin tzinfo; compararlos con uno aware explota."""
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def cookie_segura() -> bool:
    """`Secure` en la cookie salvo que se apague explícitamente.

    Los navegadores tratan `http://localhost` como contexto seguro, así que el
    valor por defecto no estorba en desarrollo. Se apaga con
    MOTOR_OCR_COOKIE_SEGURA=0 para servir por HTTP en una red interna.
    """
    return os.environ.get("MOTOR_OCR_COOKIE_SEGURA", "1") not in ("0", "false", "False")


# ============================================================================
# CONTRASEÑAS
# ============================================================================

def hashear_password(password: str) -> str:
    """Devuelve `scrypt$n$r$p$salt_hex$hash_hex`.

    Los parámetros viajan con el hash para poder subirlos más adelante sin
    invalidar las contraseñas ya guardadas.
    """
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(
        password.encode("utf-8"), salt=sal,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_LEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sal.hex()}${derivada.hex()}"


def verificar_password(password: str, almacenado: str | None) -> bool:
    if not almacenado:
        return False

    try:
        algoritmo, n, r, p, sal_hex, hash_hex = almacenado.split("$")
        if algoritmo != "scrypt":
            return False
        derivada = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(sal_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2,
        )
    except (ValueError, TypeError):
        return False

    # compare_digest y no `==`: comparar byte a byte filtra por tiempo cuántos
    # caracteres del hash acertó quien prueba.
    return hmac.compare_digest(derivada.hex(), hash_hex)


# ============================================================================
# API KEYS
# ============================================================================

def generar_api_key() -> tuple[str, str, str]:
    """Devuelve (clave_en_claro, hash, prefijo).

    La clave en claro se muestra una única vez, al crearla: después sólo queda
    el hash, así que ni siquiera el operador de la base puede recuperarla.
    """
    clave = PREFIJO_CLAVE + secrets.token_urlsafe(32)
    return clave, hashear_api_key(clave), clave[: len(PREFIJO_CLAVE) + 8]


def hashear_api_key(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def crear_api_key(sesion: Session, usuario: Usuario, nombre: str = "") -> tuple[ApiKey, str]:
    """Alta de una clave. Devuelve la fila y la clave en claro (irrecuperable)."""
    clave, clave_hash, prefijo = generar_api_key()

    registro = ApiKey(
        id=str(uuid4()),
        usuario_id=usuario.id,
        nombre=nombre or "sin nombre",
        clave_hash=clave_hash,
        prefijo=prefijo,
    )
    sesion.add(registro)
    sesion.flush()

    return registro, clave


# ============================================================================
# USUARIOS
# ============================================================================

def crear_usuario(
    sesion: Session,
    nombre: str,
    email: str | None = None,
    plan: str = "libre",
    password: str | None = None,
) -> tuple[Usuario, str]:
    """Alta de usuario con su primera API key.

    Devuelve el usuario y la clave en claro. `password` es opcional: un usuario
    creado por CLI para consumir sólo la API no necesita entrar por el navegador.
    """
    usuario = Usuario(
        id=str(uuid4()),
        nombre=nombre,
        email=email,
        password_hash=hashear_password(password) if password else None,
        plan=plan,
    )
    sesion.add(usuario)
    sesion.flush()

    _, clave = crear_api_key(sesion, usuario, nombre="clave inicial")
    return usuario, clave


# ============================================================================
# SESIONES
# ============================================================================

def crear_sesion(sesion: Session, usuario: Usuario) -> tuple[Sesion, str]:
    """Abre una sesión. Devuelve la fila y el token que va en la cookie."""
    token = secrets.token_urlsafe(32)

    registro = Sesion(
        id=str(uuid4()),
        usuario_id=usuario.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expira_en=_ahora() + timedelta(days=DIAS_SESION),
    )
    sesion.add(registro)
    sesion.flush()

    return registro, token


def cerrar_sesion(sesion: Session, token: str | None) -> bool:
    """Borra la sesión del token. Devuelve si borro alguna."""
    if not token:
        return False

    registro = (
        sesion.query(Sesion)
        .filter(Sesion.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest())
        .one_or_none()
    )
    if registro is None:
        return False

    sesion.delete(registro)
    return True


def purgar_sesiones_vencidas(sesion: Session) -> int:
    """Borra las sesiones expiradas. Se llama al abrir una nueva."""
    vencidas = (
        sesion.query(Sesion).filter(Sesion.expira_en < _ahora()).delete(synchronize_session=False)
    )
    return vencidas or 0


# ============================================================================
# RESOLUCIÓN DEL USUARIO
# ============================================================================

def obtener_sesion():
    """Dependencia de FastAPI: una sesión de base por request."""
    sesion = get_session()
    try:
        yield sesion
    finally:
        sesion.close()


_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={
        "codigo": "sin_autenticacion",
        "detail": "Falta autenticación: cookie de sesión o cabecera X-API-Key",
    },
    headers={"WWW-Authenticate": "ApiKey"},
)


def _usuario_de_cookie(sesion: Session, token: str | None) -> Usuario | None:
    if not token:
        return None

    registro = (
        sesion.query(Sesion)
        .filter(Sesion.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest())
        .one_or_none()
    )
    if registro is None:
        return None

    if _con_tz(registro.expira_en) < _ahora():
        sesion.delete(registro)
        sesion.commit()
        return None

    _marcar_uso(sesion, registro)
    return registro.usuario


def _usuario_de_api_key(sesion: Session, clave: str | None) -> Usuario | None:
    if not clave:
        return None

    registro = (
        sesion.query(ApiKey)
        .filter(ApiKey.clave_hash == hashear_api_key(clave))
        .one_or_none()
    )
    # Mismo tratamiento para clave inexistente, mal formada y revocada: no hay
    # nada en la respuesta que le confirme a quien prueba claves cuáles existen.
    if registro is None or registro.revocada_en is not None:
        return None

    _marcar_uso(sesion, registro)
    return registro.usuario


def _marcar_uso(sesion: Session, registro) -> None:
    ahora = _ahora()
    ultimo = _con_tz(registro.ultimo_uso_en)

    if ultimo is not None and ahora - ultimo < _GRANULARIDAD_USO:
        return

    registro.ultimo_uso_en = ahora
    sesion.commit()


def usuario_actual(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    motor_ocr_sesion: str | None = Cookie(default=None, alias=COOKIE_SESION),
    sesion: Session = Depends(obtener_sesion),
) -> Usuario:
    """Resuelve el usuario por cookie de sesión o por API key, o corta el request."""

    # La cookie primero: es la credencial del navegador, que es de donde vienen
    # casi todos los requests, y evita el hash de la clave cuando ya hay sesión.
    usuario = _usuario_de_cookie(sesion, motor_ocr_sesion) or _usuario_de_api_key(
        sesion, x_api_key
    )

    if usuario is None:
        raise _NO_AUTENTICADO

    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"codigo": "cuenta_desactivada", "detail": "La cuenta está desactivada"},
        )

    return usuario


def usuario_de_sesion(
    motor_ocr_sesion: str | None = Cookie(default=None, alias=COOKIE_SESION),
    sesion: Session = Depends(obtener_sesion),
) -> Usuario:
    """Como `usuario_actual` pero sólo por cookie.

    Lo usan los endpoints de cuenta: crear o revocar una API key con una API key
    dejaría que una clave filtrada se perpetúe emitiendo claves nuevas.
    """
    usuario = _usuario_de_cookie(sesion, motor_ocr_sesion)

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "codigo": "requiere_sesion",
                "detail": "Esta operación necesita una sesión iniciada en el navegador",
            },
        )

    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"codigo": "cuenta_desactivada", "detail": "La cuenta está desactivada"},
        )

    return usuario
