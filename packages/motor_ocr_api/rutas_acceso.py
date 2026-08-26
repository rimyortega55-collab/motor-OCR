"""Endpoints de acceso: desbloquear la instancia con la clave única, si hay una.

Reemplaza a `/auth/registro`, `/auth/login` y `/api-keys`: sin cuentas no hay
nada que registrar ni ninguna clave que administrar por cuenta, sólo una clave
de instancia opcional que se compara contra la vigente (panel o entorno, ver
`acceso.clave_configurada`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .acceso import (
    COOKIE_ACCESO,
    clave_configurada,
    clave_valida,
    cookie_segura,
    token_de_acceso,
)
from .limites import exigir_limite
from .persistencia import obtener_sesion

router = APIRouter(tags=["acceso"])


class Clave(BaseModel):
    clave: str = Field(min_length=1, max_length=500)


def _estado(request: Request, sesion: Session) -> dict:
    requiere = clave_configurada(sesion) is not None
    if not requiere:
        return {"requiere_clave": False, "desbloqueado": True}

    cookie = request.cookies.get(COOKIE_ACCESO)
    return {"requiere_clave": True, "desbloqueado": cookie == token_de_acceso()}


@router.get("/acceso")
async def estado_acceso(request: Request, sesion: Session = Depends(obtener_sesion)) -> dict:
    """Si la instancia pide clave, y si este navegador ya la desbloqueó.

    El frontend lo llama al montar para decidir si mostrar la pantalla de
    clave o ir directo a la herramienta.
    """
    return _estado(request, sesion)


@router.post("/acceso")
async def desbloquear(
    pedido: Clave,
    respuesta: Response,
    request: Request,
    sesion: Session = Depends(obtener_sesion),
) -> dict:
    """Abre la instancia con la clave. Sin clave configurada, no hace falta llamarlo."""

    exigir_limite(request, "acceso")

    if clave_configurada(sesion) is None:
        return {"requiere_clave": False, "desbloqueado": True}

    if not clave_valida(pedido.clave, sesion):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"codigo": "clave_incorrecta", "detail": "Clave incorrecta"},
        )

    respuesta.set_cookie(
        key=COOKIE_ACCESO,
        value=token_de_acceso(),
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=cookie_segura(),
        samesite="lax",
        path="/",
    )
    return {"requiere_clave": True, "desbloqueado": True}


@router.post("/salir", status_code=status.HTTP_204_NO_CONTENT)
async def salir(respuesta: Response) -> None:
    """Cierra el acceso en este navegador. Idempotente."""
    respuesta.delete_cookie(key=COOKIE_ACCESO, path="/")
