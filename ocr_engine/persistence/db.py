"""Motor de base de datos y manejo de sesiones."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos persistidos."""


def _url_por_defecto() -> str:
    """SQLite en un directorio configurable, para no escribir en el cwd.

    Escribir en el directorio actual es lo que hacía que los datos se perdieran
    en cada despliegue: el proceso arranca en otro lado y el archivo anterior
    queda en una capa de contenedor ya descartada.
    """
    directorio = Path(os.environ.get("MOTOR_OCR_DATA_DIR", "datos"))
    directorio.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{directorio / 'motor_ocr.db'}"


DATABASE_URL = os.environ.get("DATABASE_URL") or _url_por_defecto()

# check_same_thread sólo aplica a SQLite: FastAPI atiende en varios hilos.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Crea las tablas que falten. Idempotente."""
    from . import models  # noqa: F401  (registra los modelos en la metadata)

    Base.metadata.create_all(engine)


def get_session() -> Session:
    """Sesión suelta, para usar como dependencia de FastAPI."""
    return SessionLocal()


@contextmanager
def session_scope():
    """Sesión transaccional: confirma al salir, revierte si algo falla."""
    sesion = SessionLocal()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()
