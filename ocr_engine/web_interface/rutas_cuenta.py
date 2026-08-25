"""Endpoints de sesión y de API keys (pasos 1 del contrato con el frontend).

La sesión vive en una cookie HttpOnly y las claves de API pasan a ser
administrables desde la interfaz, en vez de sólo por el CLI de
`gestion_usuarios`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ocr_engine.persistence import ApiKey, Usuario

from .limites import exigir_limite

from .auth import (
    COOKIE_SESION,
    DIAS_SESION,
    cerrar_sesion,
    cookie_segura,
    crear_api_key,
    crear_sesion,
    gastar_tiempo_de_verificacion,
    crear_usuario,
    obtener_sesion,
    purgar_sesiones_vencidas,
    usuario_actual,
    usuario_de_sesion,
    verificar_password,
)

router = APIRouter(tags=["cuenta"])

# Debajo de esto no se acepta una contraseña. El largo es la única defensa que
# sirve de verdad contra fuerza bruta offline si algún día se filtra la base.
LARGO_MINIMO_PASSWORD = 12


# ============================================================================
# MODELOS
# ============================================================================

class UsuarioPublico(BaseModel):
    id: str
    nombre: str
    email: str | None
    plan: str
    creado_en: str | None


class AltaUsuario(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=LARGO_MINIMO_PASSWORD, max_length=256)


class Credenciales(BaseModel):
    email: EmailStr
    password: str


class RespuestaAlta(BaseModel):
    usuario: UsuarioPublico
    api_key: str


class RespuestaSesion(BaseModel):
    usuario: UsuarioPublico


class AltaApiKey(BaseModel):
    nombre: str = Field(default="", max_length=120)


class ApiKeyPublica(BaseModel):
    id: str
    nombre: str
    prefijo: str
    creada_en: str | None
    ultimo_uso_en: str | None
    revocada_en: str | None


class ApiKeyCreada(ApiKeyPublica):
    api_key: str


# ============================================================================
# AUXILIARES
# ============================================================================

def _iso(momento: datetime | None) -> str | None:
    if momento is None:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.isoformat()


def _publico(usuario: Usuario) -> UsuarioPublico:
    return UsuarioPublico(
        id=usuario.id,
        nombre=usuario.nombre,
        email=usuario.email,
        plan=usuario.plan,
        creado_en=_iso(usuario.creado_en),
    )


def _api_key_publica(clave: ApiKey) -> ApiKeyPublica:
    return ApiKeyPublica(
        id=clave.id,
        nombre=clave.nombre,
        prefijo=clave.prefijo,
        creada_en=_iso(clave.creada_en),
        ultimo_uso_en=_iso(clave.ultimo_uso_en),
        revocada_en=_iso(clave.revocada_en),
    )


def _plantar_cookie(respuesta: Response, token: str) -> None:
    respuesta.set_cookie(
        key=COOKIE_SESION,
        value=token,
        max_age=DIAS_SESION * 24 * 3600,
        httponly=True,           # inaccesible desde JavaScript: un XSS no se la lleva
        secure=cookie_segura(),
        samesite="lax",          # corta el CSRF de navegación cruzada
        path="/",
    )


def _error(codigo: str, detalle: str, http: int) -> HTTPException:
    """Cuerpo de error uniforme, para que el frontend ramifique por `codigo`."""
    return HTTPException(status_code=http, detail={"codigo": codigo, "detail": detalle})


# ============================================================================
# SESIÓN
# ============================================================================

@router.post("/auth/registro", status_code=status.HTTP_201_CREATED)
async def registrar(
    alta: AltaUsuario,
    respuesta: Response,
    request: Request,
    sesion: Session = Depends(obtener_sesion),
) -> RespuestaAlta:
    """Crea la cuenta, abre sesión y devuelve la primera API key.

    La clave se devuelve acá y nunca más: en la base sólo queda su hash.
    """

    # Antes que nada: sin tope, crear cuentas en masa sale gratis y cada una
    # puede gastar credito de Anthropic, que es plata real del despliegue.
    exigir_limite(request, "registro")

    existente = sesion.query(Usuario).filter(Usuario.email == alta.email).one_or_none()
    if existente is not None:
        raise _error(
            "email_ya_registrado",
            "Ya hay una cuenta con ese email",
            status.HTTP_409_CONFLICT,
        )

    usuario, clave = crear_usuario(
        sesion, nombre=alta.nombre, email=alta.email, password=alta.password
    )
    _, token = crear_sesion(sesion, usuario)
    sesion.commit()

    _plantar_cookie(respuesta, token)
    return RespuestaAlta(usuario=_publico(usuario), api_key=clave)


@router.post("/auth/login")
async def login(
    credenciales: Credenciales,
    respuesta: Response,
    request: Request,
    sesion: Session = Depends(obtener_sesion),
) -> RespuestaSesion:
    """Abre sesión de navegador."""

    exigir_limite(request, "login")

    usuario = (
        sesion.query(Usuario).filter(Usuario.email == credenciales.email).one_or_none()
    )

    # Mismo error para email inexistente, contraseña incorrecta y cuenta sin
    # contraseña: distinguirlos le confirmaría a quien prueba qué emails existen.
    # El señuelo iguala también el tiempo, que era lo que filtraba la diferencia
    # aunque el mensaje fuera idéntico.
    if usuario is None:
        gastar_tiempo_de_verificacion()

    if usuario is None or not verificar_password(credenciales.password, usuario.password_hash):
        raise _error(
            "credenciales_invalidas",
            "Email o contraseña incorrectos",
            status.HTTP_401_UNAUTHORIZED,
        )

    if not usuario.activo:
        raise _error(
            "cuenta_desactivada", "La cuenta está desactivada", status.HTTP_403_FORBIDDEN
        )

    purgar_sesiones_vencidas(sesion)
    _, token = crear_sesion(sesion, usuario)
    sesion.commit()

    _plantar_cookie(respuesta, token)
    return RespuestaSesion(usuario=_publico(usuario))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    respuesta: Response,
    motor_ocr_sesion: str | None = Cookie(default=None, alias=COOKIE_SESION),
    sesion: Session = Depends(obtener_sesion),
) -> None:
    """Cierra la sesión. Idempotente: sin cookie válida igual responde 204."""

    cerrar_sesion(sesion, motor_ocr_sesion)
    sesion.commit()

    # FastAPI arrastra las cabeceras de la Response inyectada a la respuesta
    # final, así que alcanza con marcar el borrado de la cookie acá.
    respuesta.delete_cookie(key=COOKIE_SESION, path="/")


@router.get("/auth/yo")
async def yo(usuario: Usuario = Depends(usuario_actual)) -> UsuarioPublico:
    """Quién soy. El SPA lo llama al montar para decidir si mostrar el login."""
    return _publico(usuario)


# ============================================================================
# API KEYS
# ============================================================================

@router.get("/api-keys")
async def listar_api_keys(
    usuario: Usuario = Depends(usuario_de_sesion),
    sesion: Session = Depends(obtener_sesion),
) -> list[ApiKeyPublica]:
    """Claves del usuario, incluidas las revocadas, de la más nueva a la más vieja."""

    claves = (
        sesion.query(ApiKey)
        .filter(ApiKey.usuario_id == usuario.id)
        .order_by(ApiKey.creada_en.desc())
        .all()
    )
    return [_api_key_publica(c) for c in claves]


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def crear_clave(
    alta: AltaApiKey,
    usuario: Usuario = Depends(usuario_de_sesion),
    sesion: Session = Depends(obtener_sesion),
) -> ApiKeyCreada:
    """Emite una clave nueva. Es la única respuesta donde viaja en claro."""

    registro, clave = crear_api_key(sesion, usuario, nombre=alta.nombre)
    sesion.commit()

    return ApiKeyCreada(**_api_key_publica(registro).model_dump(), api_key=clave)


@router.delete("/api-keys/{clave_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revocar_clave(
    clave_id: str,
    usuario: Usuario = Depends(usuario_de_sesion),
    sesion: Session = Depends(obtener_sesion),
) -> Response:
    """Revoca una clave. Se marca en vez de borrarse, para conservar el rastro."""

    clave = (
        sesion.query(ApiKey)
        .filter(ApiKey.id == clave_id, ApiKey.usuario_id == usuario.id)
        .one_or_none()
    )

    # 404 y no 403 para una clave ajena: no se confirma que ese id exista.
    if clave is None:
        raise _error("clave_no_encontrada", "No existe esa clave", status.HTTP_404_NOT_FOUND)

    if clave.revocada_en is None:
        clave.revocada_en = datetime.now(timezone.utc)
        sesion.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
