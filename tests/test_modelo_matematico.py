"""Pruebas de la seleccion de checkpoint del modelo matematico (Capa 3).

Lo que se ejercita aca es el andamiaje que permite probar un fine-tuning desde
el panel: listar los `.pth` del directorio, aceptar uno, rechazar cualquier
cosa que apunte afuera, y que la eleccion sobreviva a un reinicio del proceso.
No se carga pix2tex en ningun momento -construir el modelo cuesta segundos y
descargas-, y no hace falta: `configurar_checkpoint` valida y descarta el
modelo cargado, pero no lo reconstruye hasta que llega una formula.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_modelo_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from motor_ocr.reconocimiento.engines import pix2tex_engine  # noqa: E402
from motor_ocr_api.persistencia import (  # noqa: E402
    ConfiguracionModeloMatematico,
    init_db,
    session_scope,
)
from motor_ocr_api.api import app  # noqa: E402
from motor_ocr_api.rutas_admin import (  # noqa: E402
    aplicar_modelo_matematico,
    obtener_o_crear_modelo_matematico,
)


@pytest.fixture(autouse=True)
def base_limpia(tmp_path, monkeypatch):
    init_db()
    with session_scope() as sesion:
        sesion.query(ConfiguracionModeloMatematico).delete()

    # Directorio de checkpoints propio de cada prueba: la maquina de quien corre
    # la suite puede tener `.pth` de verdad en `entrenamiento/checkpoints/`.
    monkeypatch.setattr(pix2tex_engine, "DIRECTORIO_CHECKPOINTS", tmp_path)
    pix2tex_engine.configurar_checkpoint(None)
    yield
    pix2tex_engine.configurar_checkpoint(None)


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def _checkpoint(directorio: Path, nombre: str) -> Path:
    ruta = directorio / nombre
    ruta.write_bytes(b"no son pesos de verdad, nadie los carga en estas pruebas")
    return ruta


def test_por_defecto_usa_los_pesos_preentrenados(cliente):
    cuerpo = cliente.get("/api/admin/modelo-matematico").json()

    assert cuerpo["checkpoint"] is None
    assert cuerpo["checkpoint_en_uso"] is None
    assert cuerpo["disponibles"] == []


def test_lista_los_pth_del_directorio(cliente, tmp_path):
    _checkpoint(tmp_path, "pix2tex_real_e07_step161.pth")
    _checkpoint(tmp_path, "cualquier_cosa.txt")

    cuerpo = cliente.get("/api/admin/modelo-matematico").json()

    assert [c["nombre"] for c in cuerpo["disponibles"]] == ["pix2tex_real_e07_step161.pth"]


def test_elegir_un_checkpoint_lo_aplica_en_caliente(cliente, tmp_path):
    _checkpoint(tmp_path, "afinado.pth")

    respuesta = cliente.put("/api/admin/modelo-matematico", json={"checkpoint": "afinado.pth"})

    assert respuesta.status_code == 200
    assert respuesta.json()["checkpoint_en_uso"] == "afinado.pth"
    assert pix2tex_engine.checkpoint_actual() == "afinado.pth"


def test_volver_a_los_pesos_base(cliente, tmp_path):
    _checkpoint(tmp_path, "afinado.pth")
    cliente.put("/api/admin/modelo-matematico", json={"checkpoint": "afinado.pth"})

    respuesta = cliente.put("/api/admin/modelo-matematico", json={"checkpoint": None})

    assert respuesta.status_code == 200
    assert respuesta.json()["checkpoint"] is None
    assert pix2tex_engine.checkpoint_actual() is None


@pytest.mark.parametrize(
    "nombre",
    [
        "no_existe.pth",
        "../weights.pth",
        "subdirectorio/afinado.pth",
    ],
)
def test_rechaza_lo_que_no_este_en_el_directorio(cliente, nombre):
    """422 y sin tocar el motor: el nombre llega por HTTP y no debe poder
    cargar un .pth de cualquier lado del disco."""
    respuesta = cliente.put("/api/admin/modelo-matematico", json={"checkpoint": nombre})

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"]["codigo"] == "checkpoint_invalido"
    assert pix2tex_engine.checkpoint_actual() is None


def test_la_eleccion_se_reaplica_al_arrancar(cliente, tmp_path):
    _checkpoint(tmp_path, "afinado.pth")
    cliente.put("/api/admin/modelo-matematico", json={"checkpoint": "afinado.pth"})

    # Simula el reinicio del proceso: el engine vuelve a su default y el
    # arranque tiene que devolverlo a lo guardado.
    pix2tex_engine.configurar_checkpoint(None)
    with session_scope() as sesion:
        aplicar_modelo_matematico(obtener_o_crear_modelo_matematico(sesion))

    assert pix2tex_engine.checkpoint_actual() == "afinado.pth"


def test_si_el_pth_guardado_desaparecio_arranca_con_los_pesos_base(cliente, tmp_path):
    ruta = _checkpoint(tmp_path, "afinado.pth")
    cliente.put("/api/admin/modelo-matematico", json={"checkpoint": "afinado.pth"})
    ruta.unlink()

    with session_scope() as sesion:
        aplicar_modelo_matematico(obtener_o_crear_modelo_matematico(sesion))

    assert pix2tex_engine.checkpoint_actual() is None

    # Y el panel lo dice en vez de mostrar el checkpoint muerto como vigente.
    cuerpo = cliente.get("/api/admin/modelo-matematico").json()
    assert cuerpo["checkpoint"] == "afinado.pth"
    assert cuerpo["checkpoint_en_uso"] is None
