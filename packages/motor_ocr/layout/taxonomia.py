"""Clasificación semántica extendida de bloques (teorema/lema/demostración/...).

Se detecta con reglas y regex sobre patrones tipográficos y textuales
reconocibles — negrita + "Teorema 3.2." al inicio, símbolo ∎ al final de una
demostración, numeración consistente. No requiere LLM: ver taxonomía
completa en TipoBloque (motor_ocr/models/block.py) y en
.contexto/03-capas-pipeline.md (Capa 2).
"""

from __future__ import annotations

from motor_ocr.modelos import TipoBloque


import re

# Palabras clave que abren una línea de código. En minúscula y ancladas al
# principio: "If" abriendo una oración en prosa no cuenta.
_INICIO_CODIGO = re.compile(
    r"^\s*(def |class |function |for |while |if |elif |else:|return |import |"
    r"from |print\(|#include|<\?|\{)"
)

# A partir de cuántas veces el cuerpo del texto corrido un bloque se lee como
# título aunque no vaya en negrita.
_ESCALA_TITULO = 1.15

# Un folio suelto ("14", "xvii") no es un encabezado por más que esté en una
# línea corta y destacada.
_SOLO_NUMERACION = re.compile(r"[\d ivxlcdmIVXLCDM.,)(-]+")


def clasificar_bloque(
    texto: str,
    es_negrita_inicio: bool,
    *,
    escala_fuente: float = 1.0,
    filas: int = 1,
) -> TipoBloque:
    """Clasifica bloques usando reglas y regex sobre patrones tipográficos.

    `escala_fuente` es el cuerpo del bloque dividido por el cuerpo del texto
    corrido de la página, y `filas` cuántos renglones ocupa. Son las dos
    señales que distinguen un título de un párrafo cuando la negrita no
    alcanza: un capítulo se compone más grande aunque no vaya en negrita, y un
    párrafo largo no es un título por más que empiece con una palabra en
    negrita. Los llamadores que no las tienen (camino escaneado) usan los
    valores neutros y la clasificación se comporta como antes.
    """
    if not texto.strip():
        return TipoBloque.RUIDO

    texto_lower = texto.lower().strip()

    # Patrones para detección de estructuras matemáticas
    if re.match(r"^(teorema|theorem)\s+\d+", texto_lower):
        return TipoBloque.TEOREMA
    if re.match(r"^(lema|lemma)\s+\d+", texto_lower):
        return TipoBloque.LEMA
    if re.match(r"^(proposici[óo]n|proposition)\s+\d+", texto_lower):
        return TipoBloque.PROPOSICION
    if re.match(r"^(definici[óo]n|definition)\s+\d+", texto_lower):
        return TipoBloque.DEFINICION
    if re.match(r"^(corolario|corollary)\s+\d+", texto_lower):
        return TipoBloque.COROLARIO

    # Demostración: "Proof.", "Prueba.", "Demostración." o termina con ∎
    if re.match(r"^(proof|prueba|demostraci[óo]n)\s*[.:]", texto_lower):
        return TipoBloque.DEMOSTRACION
    if "∎" in texto or r"\qed" in texto:
        return TipoBloque.DEMOSTRACION

    # Notas al pie
    if re.match(r"^(nota|note)\s*\d*\s*[.:]", texto_lower):
        return TipoBloque.NOTA_PIE

    # Listas
    if re.match(r"^(\s*[-•*]|\s*\d+[.)]\s+)", texto):
        return TipoBloque.LISTA

    # Código (pseudocódigo o código real). La palabra clave tiene que abrir el
    # bloque: buscarla en cualquier posición marcaba como código a cualquier
    # párrafo en prosa que contuviera " for " o " if ", y la exportación lo
    # envolvía en ``` en medio de un texto corrido.
    if re.match(_INICIO_CODIGO, texto):
        if es_negrita_inicio or texto.rstrip().endswith(":") or "\n" in texto:
            return TipoBloque.CODIGO

    # Encabezado: corto, en negrita o con un cuerpo mayor que el del texto
    # corrido. Antes se descartaba cualquier texto con un dígito entre sus
    # últimos 20 caracteres —una defensa contra las entradas de índice, que
    # terminan en el número de página— pero eso rechazaba de paso a "Chapter 1"
    # y a toda sección numerada como "1.1 Grammar", que son justamente los
    # encabezados que un libro tiene. Las entradas de índice se reconocen ahora
    # por sus puntos guía, antes de llegar acá.
    if (
        (es_negrita_inicio or escala_fuente >= _ESCALA_TITULO)
        and len(texto) < 150
        and filas <= 2
        and not _SOLO_NUMERACION.fullmatch(texto)
    ):
        return TipoBloque.ENCABEZADO

    # Fórmula display: empieza/termina con $$ o \[ \]
    if (
        re.match(r"^\s*(\$\$|\\\\[\[])", texto)
        or re.search(r"(\$\$|\\\\[\]])\s*$", texto)
    ):
        return TipoBloque.FORMULA_DISPLAY

    # Fórmula inline: texto principalmente simbólico
    if re.search(r"[α-ωΑ-Ω∫∑∏∂∇∞∀∃∈∉⊂⊃∪∩]", texto):
        if len(texto) < 200:
            return TipoBloque.FORMULA_INLINE

    # Párrafo es el default para bloques de texto
    return TipoBloque.PARRAFO
