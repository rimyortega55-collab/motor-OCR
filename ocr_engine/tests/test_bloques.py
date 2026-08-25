"""Pruebas del paso 3: bloques persistidos, imagen de página y decisiones.

Es el paso que desbloquea el visor de revisión, así que lo que se verifica acá es
que los bloques se guarden con el bbox normalizado, que se puedan filtrar y
paginar, que la página se pueda renderizar, y que una decisión humana efectivamente
modifique el bloque en vez de quedar sólo registrada.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_bloques_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_DATA_DIR"] = _DIRECTORIO
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from ocr_engine.persistence import (  # noqa: E402
    ApiKey,
    BloqueAlmacenado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    Sesion,
    Usuario,
    init_db,
    session_scope,
)
from ocr_engine.segmentation.bbox import desnormalizar_bbox, normalizar_bbox  # noqa: E402
from ocr_engine.web_interface import almacen  # noqa: E402
from ocr_engine.web_interface import limites  # noqa: E402
from ocr_engine.web_interface.api import app  # noqa: E402

PASSWORD = "una-contrasena-larga"
PDF_PRUEBA = Path("pruebas/pdfs_de_prueba/c1.pdf")


@pytest.fixture(autouse=True)
def base_limpia():
    init_db()
    # El limitador de tasa cuenta por proceso: sin resetearlo, una suite que crea
    # varios usuarios agota la cuota y las pruebas siguientes reciben 429.
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (Sesion, ApiKey, DecisionAlmacenada, BloqueAlmacenado,
                       DocumentoAlmacenado, Usuario):
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


@pytest.fixture
def documento(cliente):
    """Documento con bloques sembrados a mano, sin correr el pipeline."""

    usuario_id = cliente.get("/api/auth/yo").json()["id"]
    documento_id = str(uuid4())

    with session_scope() as sesion:
        sesion.add(
            DocumentoAlmacenado(
                id=documento_id,
                usuario_id=usuario_id,
                titulo="c7.pdf",
                estado="completado",
                total_paginas=3,
                total_bloques=6,
                necesita_revision=True,
            )
        )

        siembra = [
            # (pagina, orden, tipo, confianza, estado)
            (0, 0, "encabezado", 0.98, "no_requiere"),
            (0, 1, "parrafo", 0.94, "no_requiere"),
            (0, 2, "formula_display", 0.54, "pendiente"),
            (1, 0, "parrafo", 0.68, "pendiente"),
            (1, 1, "tabla", 0.59, "pendiente"),
            (2, 0, "parrafo", None, "no_requiere"),
        ]

        for pagina, orden, tipo, confianza, estado in siembra:
            sesion.add(
                BloqueAlmacenado(
                    id=str(uuid4()),
                    documento_id=documento_id,
                    pagina=pagina,
                    orden_lectura=orden,
                    tipo=tipo,
                    origen_contenido="requiere_ocr",
                    bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
                    confianza_layout=0.9,
                    confianza_global=confianza,
                    texto_plano=f"texto de {tipo} p{pagina}",
                    micro_segmentos=[
                        {
                            "tipo": "texto",
                            "contenido": "algo",
                            "engine_usado": "easyocr",
                            "confianza_engine": confianza or 0.0,
                            "confianza_estructural": confianza or 0.0,
                        }
                    ],
                    escalacion=(
                        {
                            "requirio_escalacion": True,
                            "contenido_llm": "corregido por el modelo",
                            "confianza_llm": 0.91,
                            "razon_escalacion": "índice inferior ilegible",
                            "requiere_revision_humana": True,
                        }
                        if tipo == "formula_display"
                        else None
                    ),
                    estado_revision=estado,
                )
            )

    return documento_id


# ============================================================================
# BBOX NORMALIZADO
# ============================================================================

def test_normalizar_y_desnormalizar_son_inversas():
    caja_puntos = (595.0, 842.0)   # A4 en puntos
    caja_pixeles = (1654, 2339)    # la misma A4 a 200 dpi

    bbox_en_puntos = (100.0, 200.0, 400.0, 260.0)
    normalizado = normalizar_bbox(bbox_en_puntos, caja_puntos)

    assert all(0.0 <= v <= 1.0 for v in normalizado)

    # El mismo bbox, llevado a píxeles de un render a otra densidad, cae en la
    # misma región relativa. Es lo que hacía falta para que el overlay del visor
    # no dependiera de qué capa produjo el bloque.
    x0, y0, x1, y1 = desnormalizar_bbox(normalizado, caja_pixeles)
    assert abs(x0 / caja_pixeles[0] - bbox_en_puntos[0] / caja_puntos[0]) < 0.01
    assert abs(y1 / caja_pixeles[1] - bbox_en_puntos[3] / caja_puntos[1]) < 0.01


def test_normalizar_acota_lo_que_se_sale_de_la_pagina():
    """docTR devuelve de vez en cuando cajas apenas fuera del borde."""
    assert normalizar_bbox((-10.0, -5.0, 700.0, 900.0), (595.0, 842.0)) == (0.0, 0.0, 1.0, 1.0)


def test_una_pagina_sin_dimensiones_no_rompe_la_segmentacion():
    assert normalizar_bbox((10.0, 10.0, 20.0, 20.0), (0.0, 0.0)) == (0.0, 0.0, 0.0, 0.0)


# ============================================================================
# LISTADO DE BLOQUES
# ============================================================================

def test_lista_los_bloques_en_orden_de_lectura(cliente, documento):
    cuerpo = cliente.get(f"/api/documentos/{documento}/bloques").json()

    assert cuerpo["total"] == 6
    orden = [(b["pagina"], b["orden_lectura"]) for b in cuerpo["items"]]
    assert orden == sorted(orden)
    assert cuerpo["items"][0]["tipo"] == "encabezado"


def test_los_campos_pesados_no_viajan_salvo_que_se_pidan(cliente, documento):
    liviano = cliente.get(f"/api/documentos/{documento}/bloques").json()["items"][0]
    assert "micro_segmentos" not in liviano
    assert "escalacion" not in liviano

    completo = cliente.get(
        f"/api/documentos/{documento}/bloques",
        params={"incluir": "micro_segmentos,escalacion"},
    ).json()["items"][0]
    assert "micro_segmentos" in completo
    assert "escalacion" in completo


def test_filtros_por_pagina_tipo_y_confianza(cliente, documento):
    ruta = f"/api/documentos/{documento}/bloques"

    assert cliente.get(ruta, params={"pagina": 0}).json()["total"] == 3
    assert cliente.get(ruta, params={"tipo": ["tabla"]}).json()["total"] == 1
    assert cliente.get(ruta, params={"confianza_max": 0.7}).json()["total"] == 3


def test_la_cola_de_revision_es_este_endpoint_con_filtros(cliente, documento):
    """No hay endpoint aparte: la cola son los pendientes ordenados por confianza."""

    cola = cliente.get(
        f"/api/documentos/{documento}/bloques",
        params={"estado_revision": "pendiente", "orden": "confianza"},
    ).json()

    assert cola["total"] == 3
    confianzas = [b["confianza_global"] for b in cola["items"]]
    assert confianzas == sorted(confianzas), "lo peor primero: es donde rinde revisar"
    assert confianzas[0] == 0.54


def test_el_cursor_recorre_todos_los_bloques_sin_repetir(cliente, documento):
    vistos, cursor = [], None

    for _ in range(10):
        params = {"limite": 2}
        if cursor:
            params["cursor"] = cursor
        cuerpo = cliente.get(f"/api/documentos/{documento}/bloques", params=params).json()
        vistos.extend(b["id"] for b in cuerpo["items"])
        cursor = cuerpo["siguiente_cursor"]
        if cursor is None:
            break

    assert len(vistos) == 6
    assert len(set(vistos)) == 6


def test_un_bloque_trae_todo_incluida_la_correccion_del_modelo(cliente, documento):
    formula = cliente.get(
        f"/api/documentos/{documento}/bloques", params={"tipo": ["formula_display"]}
    ).json()["items"][0]

    detalle = cliente.get(f"/api/documentos/{documento}/bloques/{formula['id']}").json()

    assert detalle["escalacion"]["contenido_llm"] == "corregido por el modelo"
    assert detalle["escalacion"]["confianza_llm"] == 0.91
    assert detalle["micro_segmentos"][0]["engine_usado"] == "easyocr"


def test_no_se_ven_los_bloques_de_otro_usuario(cliente, documento):
    cliente.cookies.clear()
    cliente.post(
        "/api/auth/registro",
        json={"nombre": "Otro", "email": "otro@example.com", "password": PASSWORD},
    )

    assert cliente.get(f"/api/documentos/{documento}/bloques").status_code == 404


# ============================================================================
# PÁGINAS
# ============================================================================

def test_sin_pdf_guardado_lo_dice_en_vez_de_romper(cliente, documento):
    """Los documentos procesados antes del paso 3 no conservan el PDF."""

    respuesta = cliente.get(f"/api/documentos/{documento}/paginas")
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["codigo"] == "pdf_no_disponible"


@pytest.mark.skipif(not PDF_PRUEBA.is_file(), reason="hace falta un PDF de prueba")
def test_dimensiones_e_imagen_de_pagina(cliente, documento):
    with session_scope() as sesion:
        registro = sesion.get(DocumentoAlmacenado, documento)
        registro.ruta_pdf = almacen.guardar_pdf(documento, PDF_PRUEBA.read_bytes())

    paginas = cliente.get(f"/api/documentos/{documento}/paginas").json()
    assert paginas["total_paginas"] > 0

    primera = paginas["paginas"][0]
    assert primera["ancho_px"] > 0 and primera["alto_px"] > 0
    # El conteo de bloques por página viene de la tabla, no del PDF.
    assert primera["bloques"] == 3

    imagen = cliente.get(f"/api/documentos/{documento}/paginas/0")
    assert imagen.status_code == 200
    assert imagen.headers["content-type"] == "image/png"
    assert imagen.headers["cache-control"].startswith("private")

    # Reescalado: el visor no necesita el render completo.
    chica = cliente.get(f"/api/documentos/{documento}/paginas/0", params={"ancho": 400})
    assert chica.status_code == 200
    assert len(chica.content) < len(imagen.content)

    assert cliente.get(f"/api/documentos/{documento}/paginas/999").status_code == 404


# ============================================================================
# DECISIONES
# ============================================================================

def _pendientes(cliente, documento):
    return cliente.get(
        f"/api/documentos/{documento}/bloques",
        params={"estado_revision": "pendiente", "orden": "confianza"},
    ).json()


def test_una_decision_escribe_el_bloque_y_devuelve_el_siguiente(cliente, documento):
    cola = _pendientes(cliente, documento)
    primero = cola["items"][0]

    respuesta = cliente.post(
        f"/api/revision/{documento}/decision",
        json={
            "bloque_id": primero["id"],
            "decision": "editar",
            "contenido_final": "\\\\sum_{n=0}^{\\\\infty} a_n",
            "confianza_usuario": 0.9,
            "comentarios": "el índice inferior era un 0",
        },
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["pendientes"] == 2
    assert cuerpo["siguiente_bloque_id"] is not None
    assert cuerpo["siguiente_bloque_id"] != primero["id"]

    # El bloque quedó resuelto y con el contenido corregido: antes la decisión
    # se registraba pero el bloque no cambiaba, así que la exportación seguía
    # entregando el texto sin corregir.
    detalle = cliente.get(f"/api/documentos/{documento}/bloques/{primero['id']}").json()
    assert detalle["estado_revision"] == "resuelto"
    assert detalle["contenido_final"] == "\\\\sum_{n=0}^{\\\\infty} a_n"


def test_el_servidor_completa_el_tipo_de_bloque_de_la_decision(cliente, documento):
    """Sin `tipo_bloque` el auto-ajuste de umbrales no puede agrupar nada."""

    primero = _pendientes(cliente, documento)["items"][0]

    cliente.post(
        f"/api/revision/{documento}/decision",
        json={
            "bloque_id": primero["id"],
            "decision": "aceptar",
            "contenido_final": "texto",
            "confianza_usuario": 0.8,
        },
    )

    with session_scope() as sesion:
        decision = sesion.query(DecisionAlmacenada).one()
        assert decision.tipo_bloque == "formula_display"
        assert decision.pagina == 0
        assert decision.confianza_engine == pytest.approx(0.54)
        assert decision.contenido_original == "texto de formula_display p0"


def test_escalar_no_da_el_bloque_por_resuelto(cliente, documento):
    primero = _pendientes(cliente, documento)["items"][0]

    cliente.post(
        f"/api/revision/{documento}/decision",
        json={
            "bloque_id": primero["id"],
            "decision": "escalar",
            "contenido_final": "",
            "confianza_usuario": 0.2,
        },
    )

    detalle = cliente.get(f"/api/documentos/{documento}/bloques/{primero['id']}").json()
    assert detalle["estado_revision"] == "pendiente"


def test_al_vaciar_la_cola_el_documento_deja_de_necesitar_revision(cliente, documento):
    for bloque in _pendientes(cliente, documento)["items"]:
        respuesta = cliente.post(
            f"/api/revision/{documento}/decision",
            json={
                "bloque_id": bloque["id"],
                "decision": "aceptar",
                "contenido_final": bloque["texto_plano"],
                "confianza_usuario": 0.9,
            },
        ).json()

    assert respuesta["pendientes"] == 0
    assert respuesta["siguiente_bloque_id"] is None
    assert cliente.get(f"/api/documentos/{documento}").json()["necesita_revision"] is False


def test_no_se_puede_decidir_sobre_un_bloque_de_otro_documento(cliente, documento):
    respuesta = cliente.post(
        f"/api/revision/{documento}/decision",
        json={
            "bloque_id": str(uuid4()),
            "decision": "aceptar",
            "contenido_final": "x",
            "confianza_usuario": 0.9,
        },
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"]["codigo"] == "bloque_no_pertenece_al_documento"
