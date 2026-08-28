"""Retención del PDF, selección de páginas y exportación a LaTeX."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_retencion_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_DATA_DIR"] = _DIRECTORIO
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
from motor_ocr_api.almacen import guardar_pdf, ruta_absoluta  # noqa: E402
from motor_ocr_api.api import app  # noqa: E402
from motor_ocr_render import BloqueRenderizable, DocumentoRenderizable
from motor_ocr_render.latex import escapar, renderizar, sanear  # noqa: E402
from motor_ocr_api.retencion import purgar_pdfs_vencidos  # noqa: E402
from motor_ocr_api.seleccion import extraer_paginas, interpretar_rango  # noqa: E402


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


def _pdf(paginas: int) -> bytes:
    doc = pymupdf.open()
    for i in range(paginas):
        pagina = doc.new_page()
        pagina.insert_text((72, 100), f"pagina {i + 1}")
    datos = doc.tobytes()
    doc.close()
    return datos


# ============================================================================
# SELECCIÓN DE PÁGINAS
# ============================================================================

@pytest.mark.parametrize("expresion,esperado", [
    ("1", [0]),
    ("1-3", [0, 1, 2]),
    ("1-2, 5", [0, 1, 4]),
    ("3,1", [0, 2]),            # se ordena
    ("1-2, 2-3", [0, 1, 2]),    # se deduplica
    ("", list(range(10))),      # vacío = todo
])
def test_interpretar_rango(expresion, esperado):
    assert interpretar_rango(expresion, 10) == esperado


def test_un_hasta_pasado_del_final_se_recorta():
    """"10-999" es la forma habitual de decir "de la 10 hasta el final"."""
    assert interpretar_rango("8-999", 10) == [7, 8, 9]


@pytest.mark.parametrize("expresion,codigo", [
    ("abc", "rango_invalido"),
    ("5-2", "rango_invalido"),
    ("0", "rango_invalido"),
    ("99", "pagina_inexistente"),
])
def test_rangos_que_se_rechazan(expresion, codigo):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excepcion:
        interpretar_rango(expresion, 10)
    assert excepcion.value.detail["codigo"] == codigo


def test_extraer_paginas_recorta_de_verdad():
    original = _pdf(10)
    recortado = extraer_paginas(original, [0, 1, 2])

    with pymupdf.open(stream=BytesIO(recortado), filetype="pdf") as doc:
        assert len(doc) == 3
        assert "pagina 1" in doc[0].get_text()
        assert "pagina 3" in doc[2].get_text()


def test_pedir_todas_no_reescribe_el_archivo():
    """Sin recorte se devuelven los bytes originales, sin un viaje de ida y vuelta."""
    original = _pdf(4)
    assert extraer_paginas(original, [0, 1, 2, 3]) is original


def test_procesar_solo_algunas_paginas(cliente, monkeypatch):
    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

    respuesta = cliente.post(
        "/api/procesar",
        files={"file": ("libro.pdf", BytesIO(_pdf(20)), "application/pdf")},
        data={"paginas": "3-5"},
    )
    assert respuesta.status_code == 202

    documento_id = respuesta.json()["documento_id"]
    with session_scope() as sesion:
        documento = sesion.get(DocumentoAlmacenado, documento_id)
        assert documento.total_paginas == 3, "debe contar las elegidas, no las del archivo"
        # El mapeo permite que la interfaz muestre el número que el usuario reconoce.
        assert documento.paginas_origen == [2, 3, 4]


def test_procesar_todo_no_guarda_mapeo(cliente, monkeypatch):
    """Sin selección no hay nada que mapear: la numeración ya coincide."""
    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

    documento_id = cliente.post(
        "/api/procesar",
        files={"file": ("todo.pdf", BytesIO(_pdf(5)), "application/pdf")},
    ).json()["documento_id"]

    with session_scope() as sesion:
        assert sesion.get(DocumentoAlmacenado, documento_id).paginas_origen is None


def test_procesar_un_rango_grande_solo_encola_lo_elegido(cliente, monkeypatch):
    """Elegir un rango recorta de verdad, no sólo cuenta distinto."""
    monkeypatch.setattr("motor_ocr_api.api.encolar", lambda *a, **k: None)

    respuesta = cliente.post(
        "/api/procesar",
        files={"file": ("gordo.pdf", BytesIO(_pdf(300)), "application/pdf")},
        data={"paginas": "1-10"},
    )
    assert respuesta.status_code == 202
    documento_id = respuesta.json()["documento_id"]
    with session_scope() as sesion:
        assert sesion.get(DocumentoAlmacenado, documento_id).total_paginas == 10


# ============================================================================
# RETENCIÓN
# ============================================================================

def _documento_con_pdf(dias_de_antiguedad: int) -> tuple[str, Path]:
    documento_id = str(uuid4())
    ruta_relativa = guardar_pdf(documento_id, _pdf(1))

    with session_scope() as sesion:
        sesion.add(DocumentoAlmacenado(
            id=documento_id, titulo="viejo.pdf",
            estado="completado", total_paginas=1, ruta_pdf=ruta_relativa,
            creado_en=datetime.now(timezone.utc) - timedelta(days=dias_de_antiguedad),
        ))

    return documento_id, ruta_absoluta(ruta_relativa)


def test_la_purga_borra_los_pdf_vencidos(cliente):
    viejo_id, ruta_vieja = _documento_con_pdf(dias_de_antiguedad=45)
    nuevo_id, ruta_nueva = _documento_con_pdf(dias_de_antiguedad=1)

    assert ruta_vieja.exists() and ruta_nueva.exists()

    assert purgar_pdfs_vencidos(dias=30) == 1

    assert not ruta_vieja.exists(), "el vencido sigue en disco"
    assert ruta_nueva.exists(), "se borró uno que no estaba vencido"

    with session_scope() as sesion:
        # El documento sobrevive: se pierde la imagen de la página, no el resultado.
        assert sesion.get(DocumentoAlmacenado, viejo_id) is not None
        assert sesion.get(DocumentoAlmacenado, viejo_id).ruta_pdf is None
        assert sesion.get(DocumentoAlmacenado, nuevo_id).ruta_pdf is not None


def test_purga_desactivada_con_cero_dias(cliente):
    _documento_con_pdf(dias_de_antiguedad=999)
    assert purgar_pdfs_vencidos(dias=0) == 0


def test_la_purga_es_idempotente(cliente):
    _documento_con_pdf(dias_de_antiguedad=45)
    assert purgar_pdfs_vencidos(dias=30) == 1
    assert purgar_pdfs_vencidos(dias=30) == 0, "volvió a contar uno ya purgado"


# ============================================================================
# BORRADO
# ============================================================================

def test_borrar_un_documento_borra_su_pdf(cliente):
    """Un borrado que deja el archivo en disco no es un borrado."""
    documento_id, ruta = _documento_con_pdf(dias_de_antiguedad=0)
    assert ruta.exists()

    assert cliente.delete(f"/api/documentos/{documento_id}").status_code == 204

    assert not ruta.exists()
    with session_scope() as sesion:
        assert sesion.get(DocumentoAlmacenado, documento_id) is None


def test_borrar_arrastra_bloques_y_costos(cliente):
    documento_id, _ = _documento_con_pdf(dias_de_antiguedad=0)

    with session_scope() as sesion:
        sesion.add(BloqueAlmacenado(
            id=str(uuid4()), documento_id=documento_id, pagina=0, orden_lectura=0,
            tipo="parrafo", origen_contenido="texto_nativo",
            bbox={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            confianza_layout=0.9, texto_plano="hola",
        ))

    cliente.delete(f"/api/documentos/{documento_id}")

    with session_scope() as sesion:
        assert sesion.query(BloqueAlmacenado).filter(
            BloqueAlmacenado.documento_id == documento_id
        ).count() == 0


def test_borrar_un_documento_inexistente_da_404(cliente):
    assert cliente.delete(f"/api/documentos/{uuid4()}").status_code == 404


# ============================================================================
# EXPORTACIÓN A LATEX
# ============================================================================

def _bloque(tipo, texto) -> BloqueRenderizable:
    return BloqueRenderizable(pagina=0, orden_lectura=0, tipo=tipo, texto=texto)


def _render(bloques) -> str:
    return renderizar(DocumentoRenderizable(titulo="prueba.pdf"), bloques)


def test_escapar_protege_la_prosa():
    assert escapar("100% & _x_") == r"100\% \& \_x\_"


def test_la_prosa_se_escapa_y_la_formula_no():
    """Escapar una fórmula la destruye; no escapar la prosa rompe la compilación."""
    salida = _render([
        _bloque("parrafo", "El 50% de los casos"),
        _bloque("formula_display", r"\frac{x}{2} \leq 1"),
    ])

    assert r"50\%" in salida, "la prosa no se escapó"
    assert r"\frac{x}{2} \leq 1" in salida, "se escapó la fórmula"


def test_el_unicode_del_ocr_no_llega_crudo_al_documento():
    """pdflatex aborta ante cualquiera de estos simbolos; ninguno puede pasar."""
    salida = _render([_bloque(
        "parrafo",
        "la eﬁciencia ‘media’ • x ≥ 1 ⇒ ε > 0",
    )])

    assert "eficiencia" in salida, "la ligadura tipografica sobrevivio"
    assert r"$\geq$" in salida and r"$\Rightarrow$" in salida
    assert r"$\varepsilon$" in salida
    assert not [c for c in salida if ord(c) > 0x17F], "quedo Unicode sin macro"


def test_los_bytes_de_control_se_tiran():
    """El OCR de un escaneo devuelve controles crudos que abortan la compilacion."""
    salida = _render([_bloque("parrafo", "antes\x02despues")])

    assert "antesdespues" in salida
    assert not [c for c in salida if ord(c) < 32 and c not in "\n\t"]


def test_la_formula_se_sanea_sin_perder_el_latex():
    """pix2tex tambien devuelve simbolos crudos, pero su LaTeX debe quedar intacto."""
    assert sanear("\\frac{x}{2} ≤ 1") == "\\frac{x}{2} $\\leq$ 1"


def test_el_verbatim_no_puede_cerrarse_solo():
    """Un \\end{lstlisting} dentro del codigo descarrilaria el resto del documento."""
    salida = _render([_bloque("codigo", r"x = 1  # \end{lstlisting}")])

    assert salida.count(r"\end{lstlisting}") == 1


def test_los_teoremas_van_a_su_entorno():
    salida = _render([_bloque("teorema", "Todo grupo finito")])
    assert r"\begin{theorem}" in salida and r"\end{theorem}" in salida


def test_el_documento_esta_completo():
    salida = _render([_bloque("parrafo", "texto")])
    assert salida.startswith(r"\documentclass")
    assert r"\begin{document}" in salida
    assert salida.rstrip().endswith(r"\end{document}")


def test_el_codigo_no_se_escapa():
    """lstlisting es verbatim: escaparlo rompería el código."""
    salida = _render([_bloque("codigo", "if x % 2 == 0:")])
    assert "if x % 2 == 0:" in salida


def test_exportar_latex_por_la_api(cliente):
    documento_id, _ = _documento_con_pdf(dias_de_antiguedad=0)

    with session_scope() as sesion:
        sesion.add(BloqueAlmacenado(
            id=str(uuid4()), documento_id=documento_id, pagina=0, orden_lectura=0,
            tipo="teorema", origen_contenido="texto_nativo",
            bbox={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
            confianza_layout=0.9, texto_plano="Enunciado del 50%",
        ))

    respuesta = cliente.get(f"/api/documentos/{documento_id}/export?formato=latex")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("application/x-tex")
    assert ".tex" in respuesta.headers["content-disposition"]
    assert r"\begin{theorem}" in respuesta.text
    assert r"50\%" in respuesta.text
