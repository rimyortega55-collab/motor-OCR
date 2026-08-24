"""Clasificación semántica extendida de bloques (teorema/lema/demostración/...).

Se detecta con reglas y regex sobre patrones tipográficos y textuales
reconocibles — negrita + "Teorema 3.2." al inicio, símbolo ∎ al final de una
demostración, numeración consistente. No requiere LLM: ver taxonomía
completa en TipoBloque (ocr_engine/models/block.py) y en
.contexto/03-capas-pipeline.md (Capa 2).
"""

from __future__ import annotations

from ocr_engine.models import TipoBloque


import re


def clasificar_bloque(texto: str, es_negrita_inicio: bool) -> TipoBloque:
    """Clasifica bloques usando reglas y regex sobre patrones tipográficos."""
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

    # Código (pseudocódigo o código real)
    if re.search(r"(def |function |for |while |if |return )", texto_lower):
        if es_negrita_inicio or ":" in texto:
            return TipoBloque.CODIGO

    # Encabezado: texto negrita al inicio + corto
    if es_negrita_inicio and len(texto) < 150 and not any(
        char.isdigit() for char in texto[-20:]
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
