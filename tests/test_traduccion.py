"""Traducción con contexto: qué se traduce, qué no, y cómo se exporta.

No se llama al modelo: se reemplaza `traducir_lote` por una función que devuelve
lo que le pasan con un prefijo. Lo que se prueba acá es el contrato alrededor de
la traducción —qué bloques entran, cómo viaja el contexto, qué exporta— y eso no
necesita gastar en llamadas reales ni depender de que haya crédito.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_traduccion_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_DATA_DIR"] = _DIRECTORIO
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from motor_ocr_api.persistencia import (  # noqa: E402
    BloqueAlmacenado,
    CostoRegistrado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    TraduccionBloque,
    TraduccionDocumento,
    UmbralesGlobales,
    init_db,
    session_scope,
)
from motor_ocr.traduccion import ContextoTraduccion, bloques_a_traducir, extraer_terminos  # noqa: E402
from motor_ocr_api import limites, trabajos_traduccion  # noqa: E402
from motor_ocr_api.api import app  # noqa: E402


@pytest.fixture(autouse=True)
def base_limpia():
    init_db()
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (
            TraduccionBloque, TraduccionDocumento, CostoRegistrado, DecisionAlmacenada,
            BloqueAlmacenado, DocumentoAlmacenado, UmbralesGlobales,
        ):
            sesion.query(modelo).delete()
    yield


@pytest.fixture
def traductor_falso(monkeypatch):
    """Reemplaza la llamada al modelo. Devuelve (llamadas registradas)."""
    llamadas = []

    def falso(fragmentos, contexto, modelo=None):
        llamadas.append({"fragmentos": fragmentos, "contexto": contexto})
        traducciones = {ident: f"[es] {texto}" for ident, texto in fragmentos}
        return traducciones, 0.001 * len(fragmentos), 100, 120

    monkeypatch.setattr(trabajos_traduccion, "traducir_lote", falso)
    return llamadas


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


class _Bloque:
    """Bloque mínimo con lo que mira el filtro."""

    def __init__(self, tipo="parrafo", pagina=0, texto="hola", contenido_final=None):
        self.id = str(uuid4())
        self.tipo = tipo
        self.pagina = pagina
        self.texto_plano = texto
        self.contenido_final = contenido_final


def _documento(cliente, bloques: list[tuple[str, int, str]]) -> str:
    """Crea un documento completado con los bloques dados (tipo, pagina, texto)."""
    documento_id = str(uuid4())
    with session_scope() as sesion:
        sesion.add(DocumentoAlmacenado(
            id=documento_id, titulo="paper.pdf",
            estado="completado", total_paginas=3, total_bloques=len(bloques),
        ))

    with session_scope() as sesion:
        for orden, (tipo, pagina, texto) in enumerate(bloques):
            sesion.add(BloqueAlmacenado(
                id=str(uuid4()), documento_id=documento_id, pagina=pagina,
                orden_lectura=orden, tipo=tipo, origen_contenido="texto_nativo",
                bbox={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                confianza_layout=0.9, texto_plano=texto,
            ))

    return documento_id


# ============================================================================
# QUÉ SE TRADUCE
# ============================================================================

def test_las_formulas_y_el_codigo_no_se_traducen():
    """Traducir una fórmula la destruye y traducir código lo vuelve inejecutable."""
    bloques = [
        _Bloque("parrafo"),
        _Bloque("formula_display"),
        _Bloque("formula_inline"),
        _Bloque("codigo"),
        _Bloque("teorema"),
    ]
    elegidos = bloques_a_traducir(bloques)
    assert [b.tipo for b in elegidos] == ["parrafo", "teorema"]


def test_se_puede_traducir_solo_algunas_paginas():
    bloques = [_Bloque(pagina=p) for p in range(5)]
    elegidos = bloques_a_traducir(bloques, {"paginas": [1, 3]})
    assert [b.pagina for b in elegidos] == [1, 3]


def test_se_puede_traducir_solo_ciertos_tipos():
    """Traducir los enunciados y dejar las demostraciones es un caso real."""
    bloques = [_Bloque("teorema"), _Bloque("demostracion"), _Bloque("parrafo")]
    elegidos = bloques_a_traducir(bloques, {"tipos": ["teorema"]})
    assert [b.tipo for b in elegidos] == ["teorema"]


def test_se_traduce_la_correccion_humana_y_no_el_texto_del_motor():
    bloques = [_Bloque(texto="lo que leyo el motor", contenido_final="lo que corrigio la persona")]
    assert trabajos_traduccion.contenido_de(bloques[0]) == "lo que corrigio la persona"


def test_los_bloques_vacios_no_entran():
    """Mandar un bloque vacío al modelo es pagar por nada."""
    assert bloques_a_traducir([_Bloque(texto="   ")]) == []


# ============================================================================
# CONTEXTO
# ============================================================================

def test_el_contexto_viaja_completo_en_las_instrucciones():
    contexto = ContextoTraduccion(
        idioma="español",
        descripcion="Libro de álgebra de posgrado",
        tono="accesible",
        glosario={"ring": "anillo"},
    )
    texto = contexto.instrucciones()

    assert "español" in texto
    assert "Libro de álgebra de posgrado" in texto
    assert "didáctico" in texto, "el tono no llegó"
    assert "ring → anillo" in texto, "el glosario no llegó"


def test_el_glosario_va_como_regla_y_no_como_sugerencia():
    """Es lo único que garantiza el mismo término en todo el documento."""
    texto = ContextoTraduccion(idioma="es", glosario={"eigenvalue": "autovalor"}).instrucciones()
    assert "exactamente" in texto.lower()


def test_sin_glosario_no_se_arma_la_seccion():
    assert "→" not in ContextoTraduccion(idioma="es").instrucciones()


# ============================================================================
# GLOSARIO
# ============================================================================

def test_el_glosario_propone_los_terminos_frecuentes():
    bloques = [_Bloque(texto="eigenvalue " * 5 + "ring " * 4 + "raro")]
    terminos = extraer_terminos(bloques, lambda b: b.texto_plano)
    propuestos = [t["termino"] for t in terminos]

    assert "eigenvalue" in propuestos
    assert "ring" in propuestos
    assert "raro" not in propuestos, "un término con una aparición no genera inconsistencia"


def test_el_glosario_ignora_el_codigo():
    """Un identificador repetido en código no es un término del documento."""
    bloques = [_Bloque("codigo", texto="variable " * 10)]
    assert extraer_terminos(bloques, lambda b: b.texto_plano) == []


def test_el_glosario_ignora_las_palabras_vacias():
    bloques = [_Bloque(texto="the of and the of and the of and")]
    assert extraer_terminos(bloques, lambda b: b.texto_plano) == []


# ============================================================================
# EL PEDIDO POR LA API
# ============================================================================

def test_pedir_una_traduccion_la_encola_y_la_completa(cliente, traductor_falso):
    documento_id = _documento(cliente, [
        ("parrafo", 0, "A theory begins with axioms"),
        ("formula_display", 0, "x = y"),
        ("teorema", 1, "Every finite group"),
    ])

    respuesta = cliente.post(f"/api/documentos/{documento_id}/traducciones", json={
        "idioma": "español",
        "descripcion": "Libro de álgebra",
        "glosario": {"axioms": "axiomas"},
    })

    assert respuesta.status_code == 202
    assert respuesta.json()["bloques_totales"] == 2, "la fórmula no debe contarse"

    # El worker corre en un hilo; con el traductor falso termina enseguida.
    for _ in range(50):
        estado = cliente.get(f"/api/documentos/{documento_id}/traducciones").json()[0]
        if estado["estado"] in ("completada", "error"):
            break
        import time
        time.sleep(0.1)

    assert estado["estado"] == "completada"
    assert estado["bloques_traducidos"] == 2
    assert estado["costo_usd"] > 0

    # El contexto llegó al traductor.
    assert traductor_falso[0]["contexto"].glosario == {"axioms": "axiomas"}
    assert traductor_falso[0]["contexto"].descripcion == "Libro de álgebra"


def test_no_se_traduce_un_documento_a_medio_procesar(cliente):
    documento_id = str(uuid4())
    with session_scope() as sesion:
        sesion.add(DocumentoAlmacenado(
            id=documento_id, titulo="a medias.pdf",
            estado="procesando", total_paginas=1,
        ))

    respuesta = cliente.post(f"/api/documentos/{documento_id}/traducciones",
                             json={"idioma": "español"})
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["codigo"] == "documento_no_listo"


def test_una_seleccion_que_no_deja_nada_se_rechaza(cliente):
    documento_id = _documento(cliente, [("formula_display", 0, "x = y")])

    respuesta = cliente.post(f"/api/documentos/{documento_id}/traducciones", json={
        "idioma": "español", "seleccion": {"tipos": ["parrafo"]},
    })
    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "seleccion_vacia"


def test_no_se_traduce_un_documento_inexistente(cliente):
    respuesta = cliente.post(f"/api/documentos/{uuid4()}/traducciones",
                             json={"idioma": "español"})
    assert respuesta.status_code == 404


# ============================================================================
# EXPORTACIÓN TRADUCIDA
# ============================================================================

def _traducir_y_esperar(cliente, documento_id, **extra):
    cliente.post(f"/api/documentos/{documento_id}/traducciones",
                 json={"idioma": "español", **extra})
    import time
    for _ in range(50):
        estado = cliente.get(f"/api/documentos/{documento_id}/traducciones").json()[0]
        if estado["estado"] in ("completada", "error"):
            return estado
        time.sleep(0.1)
    return estado


def test_exportar_en_el_idioma_pedido(cliente, traductor_falso):
    documento_id = _documento(cliente, [("parrafo", 0, "A theory begins")])
    _traducir_y_esperar(cliente, documento_id)

    respuesta = cliente.get(
        f"/api/documentos/{documento_id}/export?formato=markdown&idioma=español"
    )

    assert respuesta.status_code == 200
    assert "[es] A theory begins" in respuesta.text

    # El nombre viaja percent-encoded en `filename*`, no literal: las cabeceras
    # HTTP son latin-1 y la "ñ" no entra.
    disposicion = respuesta.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposicion
    assert "espa%C3%B1ol" in disposicion


def test_lo_no_traducido_se_exporta_en_su_idioma(cliente, traductor_falso):
    """Traducir sólo los teoremas debe dejar el resto legible, no vacío."""
    documento_id = _documento(cliente, [
        ("teorema", 0, "Every finite group"),
        ("parrafo", 0, "This paragraph stays"),
    ])
    _traducir_y_esperar(cliente, documento_id, seleccion={"tipos": ["teorema"]})

    texto = cliente.get(
        f"/api/documentos/{documento_id}/export?formato=markdown&idioma=español"
    ).text

    assert "[es] Every finite group" in texto
    assert "This paragraph stays" in texto, "el bloque excluido se perdió"


def test_exportar_un_idioma_que_no_se_tradujo(cliente):
    documento_id = _documento(cliente, [("parrafo", 0, "hola")])
    respuesta = cliente.get(
        f"/api/documentos/{documento_id}/export?formato=markdown&idioma=aleman"
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["codigo"] == "sin_traduccion"


def test_la_traduccion_no_pisa_el_texto_original(cliente, traductor_falso):
    """Es una vista sobre el bloque, no un reemplazo: el original sigue exportable."""
    documento_id = _documento(cliente, [("parrafo", 0, "A theory begins")])
    _traducir_y_esperar(cliente, documento_id)

    original = cliente.get(f"/api/documentos/{documento_id}/export?formato=markdown").text
    assert "A theory begins" in original
    assert "[es]" not in original


def test_rehacer_una_traduccion_reemplaza_la_anterior(cliente, traductor_falso):
    documento_id = _documento(cliente, [("parrafo", 0, "texto")])
    _traducir_y_esperar(cliente, documento_id)
    _traducir_y_esperar(cliente, documento_id, descripcion="otra descripcion")

    pedidos = cliente.get(f"/api/documentos/{documento_id}/traducciones").json()
    assert len(pedidos) == 1, "quedaron dos versiones del mismo idioma"
    assert pedidos[0]["descripcion"] == "otra descripcion"


def test_borrar_una_traduccion(cliente, traductor_falso):
    documento_id = _documento(cliente, [("parrafo", 0, "texto")])
    _traducir_y_esperar(cliente, documento_id)

    assert cliente.delete(
        f"/api/documentos/{documento_id}/traducciones/español"
    ).status_code == 204
    assert cliente.get(f"/api/documentos/{documento_id}/traducciones").json() == []


def test_el_costo_de_traducir_se_atribuye(cliente, traductor_falso):
    """Se registra lote a lote: un trabajo cortado deja lo gastado atribuido."""
    documento_id = _documento(cliente, [("parrafo", 0, f"texto {i}") for i in range(5)])
    _traducir_y_esperar(cliente, documento_id)

    with session_scope() as sesion:
        registros = (
            sesion.query(CostoRegistrado)
            .filter(CostoRegistrado.documento_id == documento_id)
            .all()
        )
        assert registros
        assert sum(r.costo_usd for r in registros) > 0
