"""Pruebas de los pasos 4 y 5 del contrato: umbrales, consumo y exportación.

Mismo patrón que el resto: base SQLite temporal por archivo, `DATABASE_URL`
fijada antes de importar nada del motor porque el engine se crea al importar
`persistence.db`.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_umbrales_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

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


def _usuario_id() -> str:
    with session_scope() as sesion:
        return sesion.query(Usuario).one().id


def _documento(usuario_id: str, titulo: str = "doc.pdf") -> str:
    doc_id = str(uuid4())
    with session_scope() as sesion:
        sesion.add(DocumentoAlmacenado(
            id=doc_id, usuario_id=usuario_id, titulo=titulo,
            estado="completado", total_paginas=10, total_bloques=3,
        ))
    return doc_id


# ============================================================================
# UMBRALES
# ============================================================================

def test_umbrales_se_siembran_con_los_del_motor(cliente):
    r = cliente.get("/api/umbrales")
    assert r.status_code == 200

    datos = r.json()
    assert datos["capa3"]["parrafo"] == 0.75
    assert datos["capa4"]["inconsistencia"] == 1.0
    assert "umbral_escalacion_micro_segmento" in datos["globales"]


def test_actualizar_umbrales_es_parcial(cliente):
    """Mandar sólo capa3 no debe borrar capa4."""
    cliente.put("/api/umbrales", json={"capa3": {"parrafo": 0.88}})
    datos = cliente.get("/api/umbrales").json()

    assert datos["capa3"]["parrafo"] == 0.88
    assert datos["capa3"]["tabla"] == 0.70, "se perdieron las claves no enviadas"
    assert datos["capa4"]["inconsistencia"] == 1.0, "se perdió el ámbito no enviado"


@pytest.mark.parametrize("valor", [1.7, -0.1])
def test_umbral_fuera_de_rango_se_rechaza(cliente, valor):
    assert cliente.put("/api/umbrales", json={"capa3": {"parrafo": valor}}).status_code == 422


def test_los_umbrales_son_de_cada_usuario(cliente):
    """El bug que motivó la tabla: un usuario no le cambia los umbrales a otro."""
    cliente.put("/api/umbrales", json={"capa3": {"parrafo": 0.88}})

    with TestClient(app) as otro:
        otro.post("/api/auth/registro", json={
            "nombre": "Otra", "email": "otra@ejemplo.com", "password": PASSWORD,
        })
        assert otro.get("/api/umbrales").json()["capa3"]["parrafo"] == 0.75

    assert cliente.get("/api/umbrales").json()["capa3"]["parrafo"] == 0.88


def test_recomendaciones_salen_de_la_base_y_no_de_la_cache(cliente):
    """El auto-ajuste debe ver decisiones de sesiones anteriores.

    `GestorDecisiones._decisiones_cache` es un diccionario de módulo que se vacía
    al reiniciar; leyendo de la tabla, una decisión insertada por fuera del
    proceso también cuenta.
    """
    doc_id = _documento(_usuario_id())

    with session_scope() as sesion:
        for _ in range(4):
            sesion.add(DecisionAlmacenada(
                documento_id=doc_id, bloque_id=str(uuid4()), pagina=0,
                tipo_bloque="parrafo", decision="rechazar",
                confianza_engine=0.9, confianza_usuario=0.3,
            ))

    datos = cliente.get("/api/umbrales/recomendaciones").json()

    assert datos["decisiones_analizadas"] == 4
    assert datos["recomendaciones"], "no se calculó ninguna recomendación"
    propuesta = datos["recomendaciones"][0]
    assert propuesta["clave"] == "parrafo"
    assert propuesta["propuesto"] > propuesta["actual"], "con 100 % de rechazos debe subir"


def test_recomendaciones_no_aplican_nada(cliente):
    """Calcular y aplicar están separados: la pantalla propone antes de decidir."""
    doc_id = _documento(_usuario_id())
    with session_scope() as sesion:
        for _ in range(4):
            sesion.add(DecisionAlmacenada(
                documento_id=doc_id, bloque_id=str(uuid4()), pagina=0,
                tipo_bloque="parrafo", decision="rechazar",
                confianza_engine=0.9, confianza_usuario=0.3,
            ))

    antes = cliente.get("/api/umbrales").json()["capa3"]["parrafo"]
    cliente.get("/api/umbrales/recomendaciones")
    assert cliente.get("/api/umbrales").json()["capa3"]["parrafo"] == antes


def test_aplicar_no_inventa_una_validacion(cliente):
    """`validacion` viaja en null mientras validar_cambios devuelva valores fijos."""
    datos = cliente.post("/api/umbrales/aplicar", json={}).json()
    assert datos["validacion"] is None


def test_las_decisiones_sin_tipo_no_entran(cliente):
    """Agruparlas bajo "" armaría un cubo que no representa a ningún tipo."""
    doc_id = _documento(_usuario_id())
    with session_scope() as sesion:
        sesion.add(DecisionAlmacenada(
            documento_id=doc_id, bloque_id=str(uuid4()), pagina=0,
            tipo_bloque="", decision="rechazar",
            confianza_engine=0.9, confianza_usuario=0.3,
        ))

    assert cliente.get("/api/umbrales/recomendaciones").json()["decisiones_analizadas"] == 0


# ============================================================================
# CONSUMO
# ============================================================================

def test_consumo_desglosa_por_dia_y_por_documento(cliente):
    usuario_id = _usuario_id()
    doc_id = _documento(usuario_id, "c7.pdf")

    with session_scope() as sesion:
        for cola, costo in (("micro_segmento", 0.01), ("inconsistencia_documental", 0.02)):
            sesion.add(CostoRegistrado(
                usuario_id=usuario_id, documento_id=doc_id, tipo_cola=cola,
                modelo="claude-opus-5", tokens_entrada=100, tokens_salida=50,
                costo_usd=costo, registrado_en=datetime.now(timezone.utc),
            ))

    datos = cliente.get("/api/consumo").json()

    assert datos["totales"]["llamadas_llm"] == 2
    assert datos["totales"]["costo_llm_usd"] == pytest.approx(0.03)
    assert datos["limites"]["paginas_mes"] == 200

    assert len(datos["serie_diaria"]) == 1
    dia = datos["serie_diaria"][0]
    assert dia["micro_segmento_usd"] == pytest.approx(0.01)
    assert dia["inconsistencia_documental_usd"] == pytest.approx(0.02)

    assert datos["por_documento"][0]["titulo"] == "c7.pdf"
    assert datos["por_documento"][0]["llamadas"] == 2


def test_consumo_rechaza_un_rango_al_reves(cliente):
    r = cliente.get("/api/consumo?desde=2026-09-01&hasta=2026-08-01")
    assert r.status_code == 400
    assert r.json()["detail"]["codigo"] == "rango_invalido"


def test_consumo_no_mezcla_usuarios(cliente):
    usuario_id = _usuario_id()
    doc_id = _documento(usuario_id)

    with session_scope() as sesion:
        ajeno = Usuario(id=str(uuid4()), nombre="Ajeno", email="ajeno@ejemplo.com")
        sesion.add(ajeno)
        sesion.flush()
        sesion.add(CostoRegistrado(
            usuario_id=ajeno.id, documento_id=doc_id, tipo_cola="micro_segmento",
            modelo="claude-opus-5", tokens_entrada=999, tokens_salida=999,
            costo_usd=9.99, registrado_en=datetime.now(timezone.utc),
        ))

    assert cliente.get("/api/consumo").json()["totales"]["costo_llm_usd"] == 0.0


# ============================================================================
# EXPORTACIÓN
# ============================================================================

def _con_bloques(usuario_id: str) -> str:
    doc_id = _documento(usuario_id, "mate.pdf")
    with session_scope() as sesion:
        sesion.add_all([
            BloqueAlmacenado(
                id=str(uuid4()), documento_id=doc_id, pagina=0, orden_lectura=0,
                tipo="encabezado", origen_contenido="texto_nativo",
                bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                confianza_layout=0.9, confianza_global=0.95,
                texto_plano="Capitulo 1", estado_revision="no_requiere",
            ),
            BloqueAlmacenado(
                id=str(uuid4()), documento_id=doc_id, pagina=0, orden_lectura=1,
                tipo="parrafo", origen_contenido="requiere_ocr",
                bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.4},
                confianza_layout=0.8, confianza_global=0.5,
                texto_plano="el motor leyo mal",
                contenido_final="la persona lo corrigio",
                estado_revision="resuelto",
            ),
        ])
    return doc_id


@pytest.mark.parametrize("formato", ["graphify", "markdown", "ipynb"])
def test_exportar_aplica_la_correccion_humana(cliente, formato):
    """Si la exportación ignorara `contenido_final`, revisar no serviría de nada."""
    doc_id = _con_bloques(_usuario_id())

    r = cliente.get(f"/api/documentos/{doc_id}/export?formato={formato}")
    assert r.status_code == 200

    cuerpo = r.text
    assert "la persona lo corrigio" in cuerpo
    assert "el motor leyo mal" not in cuerpo


def test_exportar_graphify_marca_lo_revisado(cliente):
    """Quien indexe esto necesita distinguir lo verificado de lo que sólo pasó por el motor."""
    doc_id = _con_bloques(_usuario_id())

    bloques = json.loads(cliente.get(f"/api/documentos/{doc_id}/export?formato=graphify").text)["bloques"]

    assert [b["revisado_por_humano"] for b in bloques] == [False, True]


def test_exportar_respeta_el_orden_de_lectura(cliente):
    doc_id = _con_bloques(_usuario_id())
    texto = cliente.get(f"/api/documentos/{doc_id}/export?formato=markdown").text
    assert texto.index("Capitulo 1") < texto.index("la persona lo corrigio")


def test_exportar_formato_desconocido(cliente):
    doc_id = _con_bloques(_usuario_id())
    r = cliente.get(f"/api/documentos/{doc_id}/export?formato=pdf")
    assert r.status_code == 400
    assert r.json()["detail"]["codigo"] == "formato_desconocido"


def test_exportar_documento_ajeno_da_404(cliente):
    ajeno_id = str(uuid4())

    # El alta va en su propia transacción y se cierra antes de seguir: anidar dos
    # `session_scope` de escritura bloquea el archivo SQLite.
    with session_scope() as sesion:
        sesion.add(Usuario(id=ajeno_id, nombre="Ajeno", email="ajeno2@ejemplo.com"))

    doc_id = _con_bloques(ajeno_id)

    assert cliente.get(f"/api/documentos/{doc_id}/export").status_code == 404


def test_exportar_sin_bloques_explica_por_que(cliente):
    """Los documentos anteriores a la tabla `bloques` hay que volver a subirlos."""
    doc_id = _documento(_usuario_id())
    r = cliente.get(f"/api/documentos/{doc_id}/export")
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "sin_bloques"


# ============================================================================
# LÍMITE DE TASA
# ============================================================================

def test_el_registro_tiene_tope(cliente):
    """Sin tope, crear cuentas en masa sale gratis y cada una gasta crédito real."""
    limites.limpiar()

    with TestClient(app) as c:
        codigos = [
            c.post("/api/auth/registro", json={
                "nombre": f"U{i}", "email": f"u{i}@ejemplo.com", "password": PASSWORD,
            }).status_code
            for i in range(7)
        ]

    assert 429 in codigos, "el registro sigue abierto sin límite"
    assert codigos.index(429) >= 5, "cortó antes de la cuota configurada"


def test_el_login_tiene_tope(cliente):
    limites.limpiar()

    with TestClient(app) as c:
        codigos = [
            c.post("/api/auth/login", json={
                "email": "rimy@ejemplo.com", "password": "incorrecta",
            }).status_code
            for i in range(12)
        ]

    assert 429 in codigos, "se puede probar contraseñas sin tope"


def test_el_429_dice_cuanto_esperar(cliente):
    limites.limpiar()

    with TestClient(app) as c:
        for i in range(12):
            r = c.post("/api/auth/login", json={
                "email": "rimy@ejemplo.com", "password": "incorrecta",
            })
            if r.status_code == 429:
                assert "Retry-After" in r.headers
                assert r.json()["detail"]["codigo"] == "demasiados_intentos"
                return

    pytest.fail("nunca se alcanzó el límite")
