"""Pruebas de la validación de subida y de las cuotas del plan.

Son controles de costo, no de higiene: sin ellos una cuenta del plan libre
procesa sin techo, y un archivo cualquiera de varios GB tumba el proceso.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_cuotas_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ocr_engine.persistence import (  # noqa: E402
    ApiKey,
    BloqueAlmacenado,
    CostoRegistrado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    Sesion,
    UmbralesUsuario,
    Usuario,
    init_db,
    session_scope,
)
from ocr_engine.web_interface import limites  # noqa: E402
from ocr_engine.web_interface.api import app  # noqa: E402
from ocr_engine.web_interface.cuotas import MAXIMO_BYTES, validar_archivo  # noqa: E402

PASSWORD = "una-contrasena-larga"


@pytest.fixture(autouse=True)
def base_limpia():
    init_db()
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (
            CostoRegistrado, DecisionAlmacenada, BloqueAlmacenado,
            DocumentoAlmacenado, UmbralesUsuario, Sesion, ApiKey, Usuario,
        ):
            sesion.query(modelo).delete()
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        c.post("/api/auth/registro", json={
            "nombre": "Rimy", "email": "rimy@ejemplo.com", "password": PASSWORD,
        })
        yield c


def _pdf(paginas: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(paginas):
        doc.new_page()
    datos = doc.tobytes()
    doc.close()
    return datos


def _subir(cliente, contenido: bytes, nombre: str = "prueba.pdf"):
    return cliente.post(
        "/api/procesar",
        files={"file": (nombre, BytesIO(contenido), "application/pdf")},
    )


# ============================================================================
# VALIDACIÓN DEL ARCHIVO
# ============================================================================

def test_un_pdf_valido_pasa():
    assert validar_archivo(_pdf(3)) == 3


def test_se_rechaza_lo_que_no_es_pdf(cliente):
    """Se mira el contenido y no el content-type, que lo elige el cliente."""
    r = _subir(cliente, b"esto no es un pdf, es texto plano")
    assert r.status_code == 415
    assert r.json()["detail"]["codigo"] == "archivo_no_es_pdf"


def test_se_rechaza_un_archivo_gigante(cliente):
    """Sin tope, `await file.read()` carga varios GB en memoria y tumba el proceso."""
    enorme = b"%PDF-1.4\n" + b"0" * (MAXIMO_BYTES + 1)
    r = _subir(cliente, enorme)
    assert r.status_code == 413
    assert r.json()["detail"]["codigo"] == "archivo_demasiado_grande"


def test_se_rechaza_el_archivo_vacio(cliente):
    r = _subir(cliente, b"")
    assert r.status_code == 400
    assert r.json()["detail"]["codigo"] == "archivo_vacio"


def test_se_rechaza_un_pdf_corrupto(cliente):
    """Con la cabecera correcta pero el cuerpo roto: no llega a encolarse."""
    r = _subir(cliente, b"%PDF-1.4\nbasura que no es un pdf valido\n")
    assert r.status_code == 400
    assert r.json()["detail"]["codigo"] in ("pdf_ilegible", "pdf_sin_paginas")


def test_un_archivo_rechazado_no_deja_documento(cliente):
    """Validar antes de crear la fila evita basura en el listado del usuario."""
    _subir(cliente, b"no es un pdf")
    assert cliente.get("/api/documentos").json()["items"] == []


# ============================================================================
# CUOTA DEL PLAN
# ============================================================================

def _gastar_paginas(usuario_id: str, paginas: int) -> None:
    with session_scope() as sesion:
        sesion.add(DocumentoAlmacenado(
            id=str(uuid4()), usuario_id=usuario_id, titulo="previo.pdf",
            estado="completado", total_paginas=paginas,
            creado_en=datetime.now(timezone.utc),
        ))


def _usuario_id() -> str:
    with session_scope() as sesion:
        return sesion.query(Usuario).one().id


def test_la_cuota_del_plan_rechaza_con_402(cliente):
    """El plan libre son 200 páginas al mes y hasta ahora no cortaba nada."""
    _gastar_paginas(_usuario_id(), 199)

    r = _subir(cliente, _pdf(5))

    assert r.status_code == 402
    assert r.json()["detail"]["codigo"] == "limite_plan_superado"


def test_la_cuota_cuenta_el_documento_que_entra(cliente):
    """Aceptarlo y notar después que se pasó significaría gastar el cómputo igual."""
    _gastar_paginas(_usuario_id(), 198)

    assert _subir(cliente, _pdf(1)).status_code == 202, "1 página entra en 200"
    assert _subir(cliente, _pdf(5)).status_code == 402, "5 más se pasan del tope"


def test_el_gasto_en_llm_tambien_corta(cliente):
    usuario_id = _usuario_id()
    doc_id = str(uuid4())

    with session_scope() as sesion:
        sesion.add(DocumentoAlmacenado(
            id=doc_id, usuario_id=usuario_id, titulo="caro.pdf",
            estado="completado", total_paginas=1,
        ))

    with session_scope() as sesion:
        sesion.add(CostoRegistrado(
            usuario_id=usuario_id, documento_id=doc_id, tipo_cola="micro_segmento",
            modelo="claude-opus-5", tokens_entrada=1, tokens_salida=1,
            costo_usd=2.5, registrado_en=datetime.now(timezone.utc),
        ))

    r = _subir(cliente, _pdf(1))
    assert r.status_code == 402
    assert r.json()["detail"]["codigo"] == "limite_gasto_superado"


def test_un_plan_sin_tope_no_corta(cliente):
    with session_scope() as sesion:
        sesion.query(Usuario).one().plan = "ilimitado"

    _gastar_paginas(_usuario_id(), 100_000)

    assert _subir(cliente, _pdf(1)).status_code == 202


def test_la_cuota_es_por_usuario(cliente):
    """El consumo de otra cuenta no debe agotar la mía."""
    with session_scope() as sesion:
        ajeno_id = str(uuid4())
        sesion.add(Usuario(id=ajeno_id, nombre="Ajeno", email="ajeno@ejemplo.com"))

    _gastar_paginas(ajeno_id, 500)

    assert _subir(cliente, _pdf(1)).status_code == 202
