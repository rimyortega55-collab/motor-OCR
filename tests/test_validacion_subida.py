"""Pruebas de la validación de subida.

Son controles de robustez, no de higiene: sin ellos un archivo cualquiera de
varios GB tumba el proceso, y cualquier cosa que no sea un PDF se encola igual.
"""

from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_cuotas_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from motor_ocr_api.persistencia import (  # noqa: E402
    BloqueAlmacenado,
    CostoRegistrado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    UmbralesGlobales,
    init_db,
    session_scope,
)
from motor_ocr_api import limites  # noqa: E402
from motor_ocr_api.api import app  # noqa: E402
from motor_ocr_api.cuotas import MAXIMO_BYTES, validar_archivo  # noqa: E402


@pytest.fixture(autouse=True)
def base_limpia():
    init_db()
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (
            CostoRegistrado, DecisionAlmacenada, BloqueAlmacenado,
            DocumentoAlmacenado, UmbralesGlobales,
        ):
            sesion.query(modelo).delete()
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as c:
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
    """Validar antes de crear la fila evita basura en el listado."""
    _subir(cliente, b"no es un pdf")
    assert cliente.get("/api/documentos").json()["items"] == []
