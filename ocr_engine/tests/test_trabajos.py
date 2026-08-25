"""Pruebas del paso 2: procesamiento asíncrono y progreso por capa.

El pipeline real necesita modelos de OCR pesados, así que la mayoría de las
pruebas lo reemplazan por uno falso: lo que se verifica acá es el andamiaje
—encolado, progreso, estados, trabajos colgados— y no el OCR, que ya tiene sus
propias pruebas por capa.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_trabajos_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from ocr_engine.persistence import (  # noqa: E402
    ApiKey,
    CostoRegistrado,
    DocumentoAlmacenado,
    Sesion,
    Usuario,
    init_db,
    session_scope,
)
from ocr_engine.web_interface import trabajos  # noqa: E402
from ocr_engine.web_interface import limites  # noqa: E402
from ocr_engine.web_interface.api import app  # noqa: E402

PASSWORD = "una-contrasena-larga"
def _pdf_minimo() -> bytes:
    """Un PDF de una página, de verdad.

    Antes acá había una cadena con la cabecera `%PDF-` y nada más, que pasaba
    porque nadie validaba la subida. Desde que `/procesar` abre el archivo para
    contar sus páginas antes de encolar, hace falta uno real. Las pruebas de este
    archivo reemplazan el `Pipeline`, así que el contenido da igual mientras el
    documento sea válido.
    """
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    datos = doc.tobytes()
    doc.close()
    return datos


PDF_MINIMO = _pdf_minimo()


@pytest.fixture(autouse=True)
def base_limpia():
    init_db()
    # El limitador de tasa cuenta por proceso: sin resetearlo, una suite que crea
    # varios usuarios agota la cuota y las pruebas siguientes reciben 429.
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (Sesion, ApiKey, CostoRegistrado, DocumentoAlmacenado, Usuario):
            sesion.query(modelo).delete()
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        c.post(
            "/api/auth/registro",
            json={"nombre": "Rimy", "email": "rimy@example.com", "password": PASSWORD},
        )
        yield c


def _esperar_estado(cliente, documento_id: str, estados: set[str], limite=10.0) -> dict:
    """Sondea hasta que el documento llega a alguno de los estados esperados."""
    fin = time.monotonic() + limite
    cuerpo: dict = {}

    while time.monotonic() < fin:
        cuerpo = cliente.get(f"/api/documentos/{documento_id}/estado").json()
        if cuerpo["estado"] in estados:
            return cuerpo
        time.sleep(0.05)

    pytest.fail(f"El documento quedó en {cuerpo.get('estado')!r}, se esperaba {estados}")


# ============================================================================
# ENCOLADO
# ============================================================================

def test_procesar_responde_202_sin_esperar_al_pipeline(cliente, monkeypatch):
    """El request no debe bloquearse: es la razón de ser del paso 2."""

    arrancado = []

    def _lento(documento_id, contenido, usuario_id):
        arrancado.append(documento_id)

    monkeypatch.setattr("ocr_engine.web_interface.api.encolar", _lento)

    respuesta = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    )

    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "en_cola"
    assert cuerpo["titulo"] == "c7.pdf"
    assert arrancado == [cuerpo["documento_id"]]


def test_procesar_rechaza_archivo_vacio(cliente):
    respuesta = cliente.post(
        "/api/procesar", files={"file": ("vacio.pdf", b"", "application/pdf")}
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "archivo_vacio"


def test_el_documento_aparece_en_la_lista_apenas_se_encola(cliente, monkeypatch):
    monkeypatch.setattr("ocr_engine.web_interface.api.encolar", lambda *a: None)

    cliente.post("/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")})

    listado = cliente.get("/api/documentos").json()
    assert listado["total"] == 1
    assert listado["items"][0]["estado"] == "en_cola"


# ============================================================================
# PROGRESO
# ============================================================================

def test_el_estado_arranca_con_las_cinco_capas_pendientes(cliente, monkeypatch):
    monkeypatch.setattr("ocr_engine.web_interface.api.encolar", lambda *a: None)

    documento_id = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    estado = cliente.get(f"/api/documentos/{documento_id}/estado").json()

    assert estado["estado"] == "en_cola"
    assert [c["capa"] for c in estado["capas"]] == [1, 2, 3, 4, 5]
    assert {c["nombre"] for c in estado["capas"]} == {
        "triage", "segmentacion", "ocr", "correccion", "escalacion",
    }
    assert all(c["estado"] == "pendiente" for c in estado["capas"])


def test_el_progreso_de_cada_capa_llega_a_la_base(cliente, monkeypatch):
    """Un pipeline falso reporta como el real; se verifica que quede persistido."""

    class PipelineFalso:
        def __init__(self, al_progresar=None):
            self.avisar = al_progresar

        def ejecutar(self, ruta_pdf):
            from ocr_engine.models import Documento, Origen

            self.avisar(1, "completada", total_paginas=34, detalle="34 páginas · nativo_digital")
            self.avisar(2, "completada", total_bloques=4812, detalle="4812 bloques · 6 tipos")
            self.avisar(3, "en_curso", hechos=120, total=400, engines={"easyocr": 120})
            self.avisar(3, "completada", hechos=400, total=400, engines={"easyocr": 400},
                        detalle="easyocr: 400")
            self.avisar(4, "completada", detalle="0 inconsistencias")
            self.avisar(5, "omitida", detalle="sin credenciales de Anthropic")

            documento = Documento(
                titulo="c7.pdf", origen=Origen.NATIVO_DIGITAL, idioma_original="es",
                total_paginas=34, version_pipeline="prueba",
            )
            return documento, []

    monkeypatch.setattr("ocr_engine.web_interface.trabajos.Pipeline", PipelineFalso)

    documento_id = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    estado = _esperar_estado(cliente, documento_id, {"completado", "error"})

    assert estado["estado"] == "completado", estado.get("error")
    assert estado["total_paginas"] == 34

    por_capa = {c["capa"]: c for c in estado["capas"]}
    assert por_capa[1]["estado"] == "completada"
    assert "34 páginas" in por_capa[1]["detalle"]
    # El conteo de bloques que ve la interfaz mientras corre sale del aviso de la
    # capa 2; el definitivo lo escribe el worker al final, con los bloques que el
    # pipeline devolvió.
    assert "4812 bloques" in por_capa[2]["detalle"]
    assert por_capa[3]["progreso"] == {"hechos": 400, "total": 400}
    assert por_capa[3]["detalle_engines"] == {"easyocr": 400}
    # La capa 5 se omite sin credenciales, y tiene que decirlo: mostrarla como
    # completada haría creer que el modelo revisó bloques que nunca vio.
    assert por_capa[5]["estado"] == "omitida"


def test_un_pipeline_que_falla_deja_el_documento_en_error(cliente, monkeypatch):
    class PipelineRoto:
        def __init__(self, al_progresar=None):
            pass

        def ejecutar(self, ruta_pdf):
            raise RuntimeError("cannot open broken document")

    monkeypatch.setattr("ocr_engine.web_interface.trabajos.Pipeline", PipelineRoto)

    documento_id = cliente.post(
        "/api/procesar", files={"file": ("roto.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    estado = _esperar_estado(cliente, documento_id, {"error"})

    assert "cannot open broken document" in estado["error"]
    # El documento sigue en la lista: el usuario tiene que poder ver que falló.
    assert cliente.get("/api/documentos").json()["total"] == 1


def test_el_estado_de_otro_usuario_no_se_puede_espiar(cliente, monkeypatch):
    monkeypatch.setattr("ocr_engine.web_interface.api.encolar", lambda *a: None)

    ajeno = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    cliente.cookies.clear()
    cliente.post(
        "/api/auth/registro",
        json={"nombre": "Otro", "email": "otro@example.com", "password": PASSWORD},
    )

    assert cliente.get(f"/api/documentos/{ajeno}/estado").status_code == 404


# ============================================================================
# TRABAJOS COLGADOS
# ============================================================================

def test_un_trabajo_sin_latido_se_cierra_como_error(cliente, monkeypatch):
    """Si el proceso muere, el documento no puede quedar en 'procesando' para siempre."""

    monkeypatch.setattr("ocr_engine.web_interface.api.encolar", lambda *a: None)

    documento_id = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    with session_scope() as sesion:
        documento = sesion.get(DocumentoAlmacenado, documento_id)
        documento.estado = "procesando"
        documento.latido_en = datetime.now(timezone.utc) - timedelta(hours=1)

    assert trabajos.marcar_colgados() == 1

    estado = cliente.get(f"/api/documentos/{documento_id}/estado").json()
    assert estado["estado"] == "error"
    assert "dejó de responder" in estado["error"]


def test_un_trabajo_con_latido_reciente_se_deja_en_paz(cliente, monkeypatch):
    monkeypatch.setattr("ocr_engine.web_interface.api.encolar", lambda *a: None)

    documento_id = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    with session_scope() as sesion:
        documento = sesion.get(DocumentoAlmacenado, documento_id)
        documento.estado = "procesando"
        documento.latido_en = datetime.now(timezone.utc)

    assert trabajos.marcar_colgados() == 0
    assert cliente.get(f"/api/documentos/{documento_id}/estado").json()["estado"] == "procesando"


# ============================================================================
# PIPELINE REAL
# ============================================================================

@pytest.mark.skipif(
    not Path("pruebas/pdfs_de_prueba/c1.pdf").is_file(),
    reason="hace falta un PDF de prueba",
)
def test_pipeline_real_reporta_progreso():
    """El instrumentado del pipeline funciona sobre un PDF de verdad.

    No pasa por la API: sólo verifica que los avisos salen en orden y con los
    datos que la interfaz espera.
    """
    from ocr_engine.pipeline import Pipeline

    avisos: list[tuple] = []

    pipeline = Pipeline(al_progresar=lambda capa, estado, **d: avisos.append((capa, estado, d)))
    documento, bloques = pipeline.ejecutar("pruebas/pdfs_de_prueba/c1.pdf")

    capas_vistas = [(c, e) for c, e, _ in avisos]
    assert (1, "en_curso") in capas_vistas
    assert (1, "completada") in capas_vistas
    assert (2, "completada") in capas_vistas
    assert (4, "completada") in capas_vistas

    # La capa 1 informa cuántas páginas encontró, y coincide con el documento.
    datos_triage = next(d for c, e, d in avisos if c == 1 and e == "completada")
    assert datos_triage["total_paginas"] == documento.total_paginas

    datos_segmentacion = next(d for c, e, d in avisos if c == 2 and e == "completada")
    assert datos_segmentacion["total_bloques"] == len(bloques)


def test_un_callback_que_explota_no_frena_el_procesamiento(monkeypatch):
    """Informar el progreso nunca puede costar el trabajo ya hecho."""
    from ocr_engine.pipeline import Pipeline

    def _explota(*a, **k):
        raise RuntimeError("el reportero falló")

    pipeline = Pipeline(al_progresar=_explota)
    # No hace falta correr el pipeline entero: alcanza con que el aviso se trague
    # la excepción.
    pipeline._avisar(1, "en_curso")
    pipeline._avisar(3, "completada", hechos=1, total=1)
