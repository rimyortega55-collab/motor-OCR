"""Capa 4 (corrección determinista): arreglar lo arreglable sin inventar nada.

Esta capa no necesita PDF ni modelos: son funciones puras sobre cadenas de
LaTeX y sobre listas de bloques ya construidas. El `skip` que tenía este
archivo decía "pendiente: agregar fixtures PDF", pero era un diagnóstico
equivocado -no hay ningún PDF involucrado acá- y mantuvo la capa sin una sola
prueba ejecutada.

La línea que separa a esta capa de la 5 es la que más importa: lo que se puede
reparar contando llaves se repara acá y en silencio; lo que es ambiguo se
marca para escalar y **no se rellena**. Un test que aceptara contenido
inventado estaría premiando exactamente el fallo que la capa existe para
evitar.
"""

from __future__ import annotations

import uuid

import pytest

from motor_ocr.correccion import corregir_documento
from motor_ocr.correccion.normalizacion_latex import normalizar_latex
from motor_ocr.correccion.reparacion_estructural import reparar_estructura
from motor_ocr.modelos import Bloque, Documento, Origen, OrigenContenido, TipoBloque
from motor_ocr.modelos.block import Contenido, Layout, Provenance


# ============================================================================
# HELPERS
# ============================================================================

_DOCUMENTO_ID = uuid.uuid4()


def _bloque(texto: str, tipo: TipoBloque = TipoBloque.PARRAFO, pagina: int = 0,
            orden: int = 0) -> Bloque:
    return Bloque(
        documento_id=_DOCUMENTO_ID,
        pagina=pagina,
        tipo=tipo,
        layout=Layout(orden_lectura=orden, confianza_layout=1.0),
        origen_contenido=OrigenContenido.TEXTO_NATIVO,
        contenido=Contenido(texto_plano=texto),
        provenance=Provenance(creado_por_capa="prueba"),
    )


def _documento(paginas: int = 1) -> Documento:
    return Documento(
        documento_id=_DOCUMENTO_ID,
        titulo="documento de prueba",
        origen=Origen.NATIVO_DIGITAL,
        idioma_original="es",
        total_paginas=paginas,
        version_pipeline="prueba",
    )


# ============================================================================
# NORMALIZACIÓN DE LATEX EQUIVALENTE
# ============================================================================

@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (r"\dfrac{a}{b}", r"\frac{a}{b}"),
        (r"\tfrac{a}{b}", r"\frac{a}{b}"),
        (r"\varnothing", r"\emptyset"),
        (r"x \vert y", r"x | y"),
        (r"\Vert v \Vert", r"\| v \|"),
        (r"\limit_{n}", r"\lim_{n}"),
    ],
)
def test_normaliza_latex_equivalente(entrada, esperado):
    """Los alias del mapa de equivalencias se estandarizan.

    Vale la pena que estos casos sean explícitos y no un solo test genérico:
    el mapa estuvo inerte porque sus claves llevaban doble backslash y encima
    pasaban por `re.escape`, con lo cual exigían dos backslashes literales que
    en LaTeX real no aparecen nunca. Nada fallaba; simplemente no normalizaba.
    """
    resultado, reparaciones = normalizar_latex(entrada)
    assert resultado == esperado
    assert reparaciones, "una normalización que cambia el texto tiene que reportarse"


@pytest.mark.parametrize("entrada", [r"\vertical", r"\liminf_{n} a_n", r"\frac{a}{b}"])
def test_no_normaliza_dentro_de_un_comando_mas_largo(entrada):
    """`\\vert` no puede pisar el prefijo de `\\vertical`, ni `\\limit` el de `\\liminf`."""
    resultado, reparaciones = normalizar_latex(entrada)
    assert resultado == entrada
    assert reparaciones == []


def test_lo_que_ya_esta_normalizado_no_reporta_reparaciones():
    """Un alias que se mapea a sí mismo sería una reparación fantasma.

    Reportar que se normalizó algo que no se tocó no es inofensivo: infla el
    registro de reparaciones que el operador revisa y le hace perder tiempo en
    bloques donde no pasó nada.
    """
    resultado, reparaciones = normalizar_latex(r"\emptyset \cdot \times")
    assert resultado == r"\emptyset \cdot \times"
    assert reparaciones == []


def test_colapsa_espaciado_fino_repetido():
    resultado, reparaciones = normalizar_latex(r"a\,\,\,b")
    assert resultado == r"a\,b"
    assert len(reparaciones) == 1


def test_quita_delimitadores_elasticos_de_contenido_corto():
    resultado, _ = normalizar_latex(r"\left( x + y \right)")
    assert resultado == "( x + y )"


def test_conserva_delimitadores_elasticos_cuando_el_contenido_es_largo():
    """Una fracción alta sí necesita `\\left`/`\\right`: ahí no se toca."""
    entrada = r"\left( \frac{a+b+c+d+e+f+g+h}{x+y+z+w+q+r+s} \right)"
    resultado, _ = normalizar_latex(entrada)
    assert resultado == entrada


def test_normaliza_espaciado_de_indices():
    resultado, _ = normalizar_latex("x^ 2 + y_ 1")
    assert resultado == "x^2 + y_1"


def test_una_cadena_vacia_no_rompe_nada():
    assert normalizar_latex("") == ("", [])
    assert normalizar_latex("   ") == ("   ", [])


# ============================================================================
# REPARACIÓN ESTRUCTURAL
# ============================================================================

def test_repara_llaves_desbalanceadas():
    """Falta un cierre: se infiere contando profundidad y se cierra al final."""
    resultado, reparaciones, escala = reparar_estructura(r"\frac{a}{b")
    assert resultado == r"\frac{a}{b}"
    assert reparaciones
    assert escala is False, "un desbalance simple se resuelve sin gastar un LLM"


def test_un_cierre_de_mas_es_ambiguo_y_se_escala():
    """Sobra un `}`: dónde iba el `{` que falta no se puede saber contando.

    La capa igual devuelve algo balanceado, pero marca el bloque para
    escalación en vez de dar la reparación por buena. Es la distinción entre
    reparar y adivinar.
    """
    _, _, escala = reparar_estructura(r"\frac{a}{b}}")
    assert escala is True


def test_cierra_un_entorno_sin_end():
    resultado, reparaciones, _ = reparar_estructura(r"\begin{align} x = 1")
    assert r"\end{align}" in resultado
    assert reparaciones


def test_lo_que_ya_esta_balanceado_se_deja_intacto():
    entrada = r"\frac{a}{b}"
    resultado, reparaciones, escala = reparar_estructura(entrada)
    assert resultado == entrada
    assert reparaciones == []
    assert escala is False


# ============================================================================
# CONSISTENCIA DOCUMENTAL
# ============================================================================

def test_detecta_numeracion_faltante():
    """Del Teorema 3.2 al 3.4 sin 3.3: hay un salto y hay que decirlo."""
    bloques = [
        _bloque("Teorema 3.2. Toda sucesion acotada tiene subsucesion convergente.",
                TipoBloque.TEOREMA, orden=0),
        _bloque("Teorema 3.4. El limite de una sucesion convergente es unico.",
                TipoBloque.TEOREMA, orden=1),
    ]
    resultado = corregir_documento(_documento(), bloques)

    tipos = [i.tipo for i in resultado.inconsistencias_detectadas]
    assert "salto_numeracion" in tipos


def test_una_numeracion_contigua_no_reporta_nada():
    bloques = [
        _bloque("Teorema 3.2. Enunciado primero.", TipoBloque.TEOREMA, orden=0),
        _bloque("Teorema 3.3. Enunciado segundo.", TipoBloque.TEOREMA, orden=1),
    ]
    resultado = corregir_documento(_documento(), bloques)

    tipos = [i.tipo for i in resultado.inconsistencias_detectadas]
    assert "salto_numeracion" not in tipos


def test_el_cambio_de_capitulo_no_es_un_salto():
    """Del Teorema 3.7 al 4.1 no falta nada: cambió el capítulo.

    Sólo se comparan elementos que comparten prefijo. Sin esa condición, todo
    documento con más de un capítulo llenaría la cola de escalación de saltos
    que no existen.
    """
    bloques = [
        _bloque("Teorema 3.7. Ultimo del capitulo tres.", TipoBloque.TEOREMA, orden=0),
        _bloque("Teorema 4.1. Primero del capitulo cuatro.", TipoBloque.TEOREMA, orden=1),
    ]
    resultado = corregir_documento(_documento(), bloques)

    tipos = [i.tipo for i in resultado.inconsistencias_detectadas]
    assert "salto_numeracion" not in tipos


def test_la_numeracion_de_dos_digitos_es_contigua():
    """Del 3.9 al 3.10 no hay hueco, aunque como decimal 3.10 < 3.9.

    Este es el caso que delata que la numeración no es un número decimal: con
    la representación anterior, "3.10" valía 4.0 y colisionaba con "Teorema 4".
    """
    bloques = [
        _bloque("Teorema 3.9. Noveno del capitulo.", TipoBloque.TEOREMA, orden=0),
        _bloque("Teorema 3.10. Decimo del capitulo.", TipoBloque.TEOREMA, orden=1),
    ]
    resultado = corregir_documento(_documento(), bloques)

    tipos = [i.tipo for i in resultado.inconsistencias_detectadas]
    assert "salto_numeracion" not in tipos


def test_la_inconsistencia_no_se_rellena_sola():
    """Detectar un salto no autoriza a fabricar el teorema que falta.

    Es la regla de producto de la capa: las inconsistencias se derivan a la
    cola de escalación de capa 5, no se resuelven inventando contenido. El
    documento tiene que salir con los mismos dos bloques que entraron.
    """
    bloques = [
        _bloque("Teorema 3.2. Enunciado primero.", TipoBloque.TEOREMA, orden=0),
        _bloque("Teorema 3.4. Enunciado segundo.", TipoBloque.TEOREMA, orden=1),
    ]
    resultado = corregir_documento(_documento(), bloques)

    assert len(resultado.bloques_corregidos) == 2
    assert resultado.inconsistencias_detectadas


# ============================================================================
# ORQUESTACIÓN
# ============================================================================

def test_un_bloque_vacio_no_genera_reparaciones():
    resultado = corregir_documento(_documento(), [_bloque("")])
    assert resultado.bloques_corregidos[0].contenido_normalizado == ""
    assert resultado.bloques_corregidos[0].reparaciones_aplicadas == []


def test_una_formula_pasa_por_la_normalizacion_latex():
    """El tipo del bloque es lo que decide si se normaliza LaTeX o no."""
    bloque = _bloque(r"\dfrac{a}{b}", TipoBloque.FORMULA_DISPLAY)
    resultado = corregir_documento(_documento(), [bloque])

    assert resultado.bloques_corregidos[0].contenido_normalizado == r"\frac{a}{b}"


def test_un_bloque_de_codigo_no_se_corrige_ortograficamente():
    """El código no es prosa: corregirle la ortografía lo rompe."""
    fuente = "def calcular_suma(xs): return sum(xs)"
    resultado = corregir_documento(_documento(), [_bloque(fuente, TipoBloque.CODIGO)])

    assert resultado.bloques_corregidos[0].contenido_normalizado == fuente


def test_un_bloque_ambiguo_queda_pendiente_de_escalacion():
    bloque = _bloque(r"\frac{a}{b}}", TipoBloque.FORMULA_DISPLAY)
    resultado = corregir_documento(_documento(), [bloque])

    assert bloque.id in resultado.bloques_pendientes_escalacion


def test_un_documento_sin_bloques_no_revienta():
    resultado = corregir_documento(_documento(), [])
    assert resultado.bloques_corregidos == []
    assert resultado.inconsistencias_detectadas == []
