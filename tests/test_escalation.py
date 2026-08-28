"""Capa 5 (escalación a LLM): a quién se le pregunta, cuánto cuesta y qué no se inventa.

Ninguna prueba de este archivo habla con un proveedor: el cliente LLM se
sustituye por un doble. No es sólo por costo y determinismo, es que la capa
existe para decidir *cuándo* preguntar, y esa decisión se puede verificar
entera sin que haya un modelo del otro lado.

Las tres propiedades que importan, en orden:

1. Sólo se escala lo que está por debajo del umbral. Escalar de más convierte
   un motor determinista en una factura.
2. El tope de gasto se respeta, y lo que queda sin escalar por falta de
   presupuesto se marca para revisión humana en vez de darse por bueno.
3. Una inconsistencia documental **no se rellena**: se deriva. Un salto de
   numeración se informa, nunca se completa con un teorema fabricado.

El `skip` que tenía este archivo decía "pendiente: agregar fixtures PDF"; la
capa no recibe PDF, recibe bloques ya reconocidos.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from motor_ocr import escalacion
from motor_ocr.escalacion import cola_inconsistencias, cola_micro_segmentos
from motor_ocr.escalacion.cola_micro_segmentos import limpiar_cola, obtener_estadisticas_cola
from motor_ocr.modelos import (
    Bloque, Documento, EngineOcr, EscalationResult, Inconsistencia, Origen,
    OrigenContenido, TipoBloque,
)
from motor_ocr.modelos.block import Contenido, Layout, MicroSegmento, Ocr, Provenance
from motor_ocr.modelos.document import Costo
from motor_ocr.modelos.results import DocumentPostCorrection


_DOCUMENTO_ID = uuid.uuid4()


# ============================================================================
# HELPERS
# ============================================================================

def _micro(confianza: float, contenido: str = "x2", tipo: str = "formula") -> MicroSegmento:
    return MicroSegmento(
        tipo=tipo,
        contenido=contenido,
        engine_usado=EngineOcr.PIX2TEX,
        confianza_engine=confianza,
        confianza_estructural=confianza,
    )


def _bloque(pagina: int, micro_segmentos: list[MicroSegmento], texto: str = "contexto") -> Bloque:
    return Bloque(
        documento_id=_DOCUMENTO_ID,
        pagina=pagina,
        tipo=TipoBloque.PARRAFO,
        layout=Layout(bbox=(0.1, 0.1, 0.9, 0.4), orden_lectura=0, confianza_layout=0.9),
        origen_contenido=OrigenContenido.REQUIERE_OCR,
        contenido=Contenido(texto_plano=texto),
        ocr=Ocr(micro_segmentos=micro_segmentos, confianza_global=0.5),
        provenance=Provenance(creado_por_capa="prueba"),
    )


def _documento(paginas: int = 2) -> Documento:
    return Documento(
        documento_id=_DOCUMENTO_ID,
        titulo="documento de prueba",
        origen=Origen.NATIVO_DIGITAL,
        idioma_original="es",
        total_paginas=paginas,
        version_pipeline="prueba",
    )


def _paginas(nums: list[int]) -> dict:
    return {n: np.full((400, 300, 3), 220, dtype=np.uint8) for n in nums}


def _sin_correcciones() -> DocumentPostCorrection:
    return DocumentPostCorrection(
        bloques_corregidos=[], inconsistencias_detectadas=[], bloques_pendientes_escalacion=[]
    )


@pytest.fixture(autouse=True)
def cola_limpia():
    """La cola de micro-segmentos es un diccionario a nivel de módulo.

    Es estado compartido entre llamadas: lo que una prueba deja encolado lo ve
    la siguiente. Se limpia antes y después para que el orden de ejecución no
    cambie el resultado.
    """
    limpiar_cola()
    yield
    limpiar_cola()


@pytest.fixture
def llm(monkeypatch):
    """Doble del cliente LLM que cuenta llamadas y devuelve algo verosímil."""
    llamadas = {"micro": 0, "inconsistencia": 0, "recibidos": []}

    def _micro_segmento(imagen_recorte=None, contexto_texto="", resultado_engine="",
                        tipo_segmento="", **kwargs):
        llamadas["micro"] += 1
        llamadas["recibidos"].append(resultado_engine)
        return EscalationResult(
            cola_origen="micro_segmento",
            contenido_final=r"x^{2}",
            confianza_llm=0.95,
            requiere_revision_humana=False,
            costo=Costo(tokens_entrada=100, tokens_salida=20, modelo_usado=["modelo-de-prueba"]),
            razon_escalacion="confianza baja del engine",
        )

    def _inconsistencia(indice_estructural=None, fragmentos_contexto=None, **kwargs):
        llamadas["inconsistencia"] += 1
        return EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final="Falta el Teorema 3.3 en el documento original.",
            confianza_llm=0.9,
            requiere_revision_humana=False,
            costo=Costo(tokens_entrada=200, tokens_salida=50, modelo_usado=["modelo-de-prueba"]),
            razon_escalacion="salto de numeracion",
        )

    monkeypatch.setattr(cola_micro_segmentos, "llamar_llm_micro_segmento", _micro_segmento)
    monkeypatch.setattr(cola_inconsistencias, "llamar_llm_inconsistencia", _inconsistencia)
    return llamadas


# ============================================================================
# QUÉ SE ESCALA Y QUÉ NO
# ============================================================================

def test_solo_se_escala_lo_que_esta_bajo_el_umbral(llm):
    """Un micro-segmento con confianza alta no se le pregunta a nadie.

    Es la propiedad que mantiene barato al motor: el LLM es el último recurso,
    no el camino habitual.
    """
    bloques = [_bloque(0, [_micro(0.95), _micro(0.30)])]
    escalacion.procesar_escalaciones(
        _documento(), bloques, _sin_correcciones(), _paginas([0])
    )

    assert llm["micro"] == 1, "solo el segmento de confianza 0.30 debia escalarse"
    assert llm["recibidos"] == ["x2"]


def test_un_documento_sin_dudas_no_gasta_nada(llm):
    bloques = [_bloque(0, [_micro(0.99)]), _bloque(1, [_micro(0.88)])]
    resultado = escalacion.procesar_escalaciones(
        _documento(), bloques, _sin_correcciones(), _paginas([0, 1])
    )

    assert llm["micro"] == 0
    assert resultado["escalaciones_micro_segmentos"] == []


def test_sin_imagen_de_pagina_no_se_escala(llm):
    """El LLM necesita ver el recorte: sin píxeles, preguntar es preguntar a ciegas."""
    bloques = [_bloque(0, [_micro(0.10)])]
    escalacion.procesar_escalaciones(_documento(), bloques, _sin_correcciones(), {})

    assert llm["micro"] == 0


# ============================================================================
# BATCHEO POR PÁGINA
# ============================================================================

def test_batchea_micro_segmentos_por_pagina(llm):
    """Los micro-segmentos se agrupan por página y la página se resuelve entera.

    La unidad de agrupación es la página, no el bloque: cortar por bloque
    dejaría segmentos de una misma línea resueltos y otros no.

    Nota sobre lo que esta prueba **no** afirma: la cola agrupa por página pero
    después recorre los elementos y llama al modelo una vez por micro-segmento,
    así que el ahorro de una llamada por página que promete el diseño todavía
    no está implementado. Se afirma lo que hoy se cumple -un resultado por
    micro-segmento, atribuido a su bloque y a su índice- para que el día que se
    implemente el batcheo real la prueba siga siendo válida.
    """
    bloques = [
        _bloque(0, [_micro(0.20, "a1"), _micro(0.25, "a2")]),
        _bloque(1, [_micro(0.30, "b1")]),
    ]
    resultado = escalacion.procesar_escalaciones(
        _documento(), bloques, _sin_correcciones(), _paginas([0, 1])
    )

    escalados = resultado["escalaciones_micro_segmentos"]
    assert len(escalados) == 3
    assert {str(e.bloque_id) for e in escalados} == {str(b.id) for b in bloques}
    assert sorted(llm["recibidos"]) == ["a1", "a2", "b1"]


def test_la_cola_queda_vacia_despues_de_resolver(llm):
    """Si la cola no se drena, el documento siguiente paga por este."""
    bloques = [_bloque(0, [_micro(0.20)])]
    escalacion.procesar_escalaciones(
        _documento(), bloques, _sin_correcciones(), _paginas([0])
    )

    assert obtener_estadisticas_cola()["total_micro_segmentos"] == 0


def test_el_resultado_del_llm_vuelve_al_bloque(llm):
    """Sin esto el modelo se paga y su respuesta se pierde al terminar el pipeline."""
    bloque = _bloque(0, [_micro(0.20)])
    escalacion.procesar_escalaciones(
        _documento(), [bloque], _sin_correcciones(), _paginas([0])
    )

    # `bloque.escalacion` existe siempre con sus campos en blanco, así que
    # comprobar que no es None no probaria nada: lo que hay que verificar es
    # que el contenido que devolvio el modelo quedo escrito.
    assert bloque.escalacion.requirio_escalacion is True
    assert bloque.escalacion.contenido_llm == r"x^{2}"
    assert bloque.escalacion.razon_escalacion == "confianza baja del engine"


# ============================================================================
# TOPE DE GASTO
# ============================================================================

def test_el_tope_de_gasto_manda_lo_no_escalado_a_revision_humana(llm, monkeypatch):
    """Quedarse sin presupuesto no puede significar dar por bueno lo dudoso.

    El corte se comprueba entre páginas y no dentro de una: cortar a mitad de
    página dejaría segmentos de la misma línea unos resueltos y otros no.
    """
    from motor_ocr.config.settings import settings
    monkeypatch.setattr(settings, "tope_gasto_documento_usd", 1e-9)

    bloques = [_bloque(0, [_micro(0.20)]), _bloque(1, [_micro(0.20)])]
    resultado = escalacion.procesar_escalaciones(
        _documento(), bloques, _sin_correcciones(), _paginas([0, 1])
    )

    assert resultado["bloques_requieren_revision_humana"], (
        "lo que no se pudo escalar por presupuesto tiene que quedar señalado"
    )


# ============================================================================
# COLA 2: INCONSISTENCIAS DOCUMENTALES
# ============================================================================

def test_no_inventa_contenido_en_inconsistencia_documental(llm):
    """Un salto de numeración se informa; el teorema faltante no se fabrica.

    El resultado de la escalación es un análisis, no un bloque nuevo: el
    documento sale con exactamente los mismos bloques con los que entró.
    """
    bloques = [_bloque(0, [_micro(0.99)])]
    correccion = DocumentPostCorrection(
        bloques_corregidos=[],
        inconsistencias_detectadas=[
            Inconsistencia(
                tipo="salto_numeracion",
                detalle="Salto en numeracion de teorema: 3.2 → 3.4",
                ubicacion_pagina=0,
            )
        ],
        bloques_pendientes_escalacion=[],
    )

    resultado = escalacion.procesar_escalaciones(
        _documento(), bloques, correccion, _paginas([0])
    )

    assert len(bloques) == 1, "la escalacion no puede agregar bloques al documento"
    assert len(resultado["escalaciones_inconsistencias"]) == 1


def test_las_inconsistencias_van_en_una_sola_llamada(llm):
    """Esta cola sí batchea de verdad: varias inconsistencias, una consulta."""
    inconsistencias = [
        Inconsistencia(tipo="salto_numeracion", detalle="3.2 → 3.4", ubicacion_pagina=0),
        Inconsistencia(tipo="referencia_sin_resolver", detalle="Lema 2.1", ubicacion_pagina=1),
    ]
    correccion = DocumentPostCorrection(
        bloques_corregidos=[], inconsistencias_detectadas=inconsistencias,
        bloques_pendientes_escalacion=[],
    )

    escalacion.procesar_escalaciones(_documento(), [_bloque(0, [])], correccion, {})

    assert llm["inconsistencia"] == 1


def test_sin_inconsistencias_no_se_consulta_la_cola_dos(llm):
    escalacion.procesar_escalaciones(
        _documento(), [_bloque(0, [])], _sin_correcciones(), {}
    )

    assert llm["inconsistencia"] == 0


# ============================================================================
# PRIORIDAD ENTRE COLAS
# ============================================================================

def test_prioridad_cola_micro_segmentos_sobre_inconsistencias(llm):
    """Los micro-segmentos se resuelven antes que las inconsistencias.

    El orden no es cosmético: una inconsistencia de numeración puede depender
    de un número que todavía está mal leído. Resolver primero el OCR evita
    escalar una inconsistencia que era, en realidad, un error de lectura.
    """
    orden: list[str] = []

    original_micro = cola_micro_segmentos.llamar_llm_micro_segmento
    original_incons = cola_inconsistencias.llamar_llm_inconsistencia

    def _micro_espia(*a, **k):
        orden.append("micro")
        return original_micro(*a, **k)

    def _incons_espia(*a, **k):
        orden.append("inconsistencia")
        return original_incons(*a, **k)

    cola_micro_segmentos.llamar_llm_micro_segmento = _micro_espia
    cola_inconsistencias.llamar_llm_inconsistencia = _incons_espia
    try:
        correccion = DocumentPostCorrection(
            bloques_corregidos=[],
            inconsistencias_detectadas=[
                Inconsistencia(tipo="salto_numeracion", detalle="3.2 → 3.4", ubicacion_pagina=0)
            ],
            bloques_pendientes_escalacion=[],
        )
        escalacion.procesar_escalaciones(
            _documento(), [_bloque(0, [_micro(0.20)])], correccion, _paginas([0])
        )
    finally:
        cola_micro_segmentos.llamar_llm_micro_segmento = original_micro
        cola_inconsistencias.llamar_llm_inconsistencia = original_incons

    assert orden == ["micro", "inconsistencia"]
