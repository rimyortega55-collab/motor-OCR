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

from motor_ocr_api.persistencia import (  # noqa: E402
    CostoRegistrado,
    DocumentoAlmacenado,
    init_db,
    session_scope,
)
from motor_ocr_api import trabajos  # noqa: E402
from motor_ocr_api import limites  # noqa: E402
from motor_ocr_api.api import app  # noqa: E402

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
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (CostoRegistrado, DocumentoAlmacenado):
            sesion.query(modelo).delete()
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as c:
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

    def _lento(documento_id, contenido, **_opciones):
        arrancado.append(documento_id)

    monkeypatch.setattr("motor_ocr_api.api.encolar", _lento)

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
    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

    cliente.post("/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")})

    listado = cliente.get("/api/documentos").json()
    assert listado["total"] == 1
    assert listado["items"][0]["estado"] == "en_cola"


# ============================================================================
# PROGRESO
# ============================================================================

def test_el_estado_arranca_con_las_cinco_capas_pendientes(cliente, monkeypatch):
    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

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

        def ejecutar(self, ruta_pdf, **_opciones):
            from motor_ocr.modelos import Documento, Origen

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

    monkeypatch.setattr("motor_ocr_api.trabajos.Pipeline", PipelineFalso)

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

        def ejecutar(self, ruta_pdf, **_opciones):
            raise RuntimeError("cannot open broken document")

    monkeypatch.setattr("motor_ocr_api.trabajos.Pipeline", PipelineRoto)

    documento_id = cliente.post(
        "/api/procesar", files={"file": ("roto.pdf", PDF_MINIMO, "application/pdf")}
    ).json()["documento_id"]

    estado = _esperar_estado(cliente, documento_id, {"error"})

    assert "cannot open broken document" in estado["error"]
    # El documento sigue en la lista: el usuario tiene que poder ver que falló.
    assert cliente.get("/api/documentos").json()["total"] == 1


# ============================================================================
# TRABAJOS COLGADOS
# ============================================================================

def test_un_trabajo_sin_latido_se_cierra_como_error(cliente, monkeypatch):
    """Si el proceso muere, el documento no puede quedar en 'procesando' para siempre."""

    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

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
    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

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
    from motor_ocr.pipeline import Pipeline

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
    from motor_ocr.pipeline import Pipeline

    def _explota(*a, **k):
        raise RuntimeError("el reportero falló")

    pipeline = Pipeline(al_progresar=_explota)
    # No hace falta correr el pipeline entero: alcanza con que el aviso se trague
    # la excepción.
    pipeline._avisar(1, "en_curso")
    pipeline._avisar(3, "completada", hechos=1, total=1)


# ============================================================================
# MODO DEL MOTOR
# ============================================================================
#
# El modo cambia el resultado del documento, así que tiene que viajar entero
# desde el formulario hasta el worker y quedar guardado: sin eso, no habría
# forma de explicar por qué dos documentos de la misma instancia salieron
# distintos.

@pytest.fixture
def modo_encolado(monkeypatch):
    """Captura con qué modo se encoló, sin correr el pipeline."""
    capturado: dict = {}

    def _encolar(documento_id, contenido, **opciones):
        capturado["modo"] = opciones.get("modo")

    monkeypatch.setattr("motor_ocr_api.api.encolar", _encolar)
    return capturado


def test_sin_elegir_modo_se_procesa_en_hibrido(cliente, modo_encolado):
    """El default no puede cambiar: es el motor que ya usaban los documentos."""
    respuesta = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    )

    assert respuesta.status_code == 202
    assert respuesta.json()["modo_motor"] == "hibrido"
    assert modo_encolado["modo"].value == "hibrido"


def test_el_modo_solo_ia_llega_al_worker_y_queda_guardado(cliente, modo_encolado):
    respuesta = cliente.post(
        "/api/procesar",
        files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")},
        data={"modo_motor": "solo_ia"},
    )

    assert respuesta.status_code == 202
    documento_id = respuesta.json()["documento_id"]
    assert modo_encolado["modo"].value == "solo_ia"

    estado = cliente.get(f"/api/documentos/{documento_id}/estado").json()
    assert estado["modo_motor"] == "solo_ia"

    listado = cliente.get("/api/documentos").json()
    assert listado["items"][0]["modo_motor"] == "solo_ia"


def test_un_modo_inexistente_se_rechaza_antes_de_encolar(cliente, modo_encolado):
    """Mejor un 400 al subir que un documento que muere en el worker después."""
    respuesta = cliente.post(
        "/api/procesar",
        files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")},
        data={"modo_motor": "magia"},
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "modo_motor_invalido"
    assert modo_encolado == {}
    assert cliente.get("/api/documentos").json()["total"] == 0


# ============================================================================
# MODO DEL MOTOR
# ============================================================================
#
# El modo cambia el resultado del documento, así que se valida al subirlo (un
# valor mal escrito tiene que fallar antes de encolar, no media hora después
# adentro del worker) y se guarda por documento, para poder explicar después
# por qué dos documentos de la misma instancia salieron distintos.

def _capturar_modo(monkeypatch) -> list:
    """Reemplaza `encolar` y devuelve la lista donde va anotando el modo."""
    modos = []

    def _encolar(documento_id, contenido, **opciones):
        modos.append(opciones.get("modo"))

    monkeypatch.setattr("motor_ocr_api.api.encolar", _encolar)
    return modos


def test_sin_elegir_modo_el_documento_se_procesa_en_hibrido(cliente, monkeypatch):
    """El default no puede cambiar: es el motor tal como venía funcionando."""
    modos = _capturar_modo(monkeypatch)

    respuesta = cliente.post(
        "/api/procesar", files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")}
    )

    assert respuesta.status_code == 202
    assert respuesta.json()["modo_motor"] == "hibrido"
    assert [m.value for m in modos] == ["hibrido"]


def test_el_modo_solo_ia_llega_al_worker_y_queda_guardado(cliente, monkeypatch):
    modos = _capturar_modo(monkeypatch)

    respuesta = cliente.post(
        "/api/procesar",
        files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")},
        data={"modo_motor": "solo_ia"},
    )

    assert respuesta.status_code == 202
    documento_id = respuesta.json()["documento_id"]
    assert [m.value for m in modos] == ["solo_ia"]

    # Guardado, no sólo en tránsito: la interfaz lo muestra al revisar el
    # documento mucho después de que el worker terminó.
    assert cliente.get(f"/api/documentos/{documento_id}/estado").json()["modo_motor"] == "solo_ia"
    assert cliente.get("/api/documentos").json()["items"][0]["modo_motor"] == "solo_ia"


def test_un_modo_desconocido_se_rechaza_antes_de_encolar(cliente, monkeypatch):
    modos = _capturar_modo(monkeypatch)

    respuesta = cliente.post(
        "/api/procesar",
        files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")},
        data={"modo_motor": "magia"},
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "modo_motor_invalido"
    assert modos == []
    # Y no queda un documento fantasma en la lista.
    assert cliente.get("/api/documentos").json()["total"] == 0


def test_el_modo_elegido_llega_al_pipeline(cliente, monkeypatch):
    """La cadena entera: formulario -> worker -> `Pipeline.ejecutar`."""
    recibido = {}

    class PipelineFalso:
        def __init__(self, al_progresar=None):
            pass

        def ejecutar(self, ruta_pdf, **opciones):
            from motor_ocr.modelos import Documento, Origen

            recibido["modo"] = opciones.get("modo")
            return (
                Documento(
                    titulo="c7.pdf", origen=Origen.NATIVO_DIGITAL, idioma_original="es",
                    total_paginas=1, version_pipeline="prueba",
                ),
                [],
            )

    monkeypatch.setattr("motor_ocr_api.trabajos.Pipeline", PipelineFalso)

    documento_id = cliente.post(
        "/api/procesar",
        files={"file": ("c7.pdf", PDF_MINIMO, "application/pdf")},
        data={"modo_motor": "solo_ia"},
    ).json()["documento_id"]

    _esperar_estado(cliente, documento_id, {"completado", "error"})

    assert recibido["modo"].value == "solo_ia"
