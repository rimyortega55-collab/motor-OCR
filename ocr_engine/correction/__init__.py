"""Orquestador de Capa 4 (Corrección Determinista)."""

from __future__ import annotations

from ocr_engine.models import (
    Bloque, Documento, OrigenContenido, MicroSegmento, TipoBloque
)
from ocr_engine.models.results import DocumentPostCorrection, BloqueCorregido

from .normalizacion_latex import normalizar_latex
from .reparacion_estructural import reparar_estructura
from .ortografia import corregir_ortografia
from .consistencia_documental import validar_consistencia_documental


def corregir_documento(documento: Documento, bloques: list[Bloque]) -> DocumentPostCorrection:
    """Aplica todas las correcciones deterministas a nivel de documento.

    Flujo:
    1. Corrección micro-segmento: normalización + reparación estructural + ortografía
    2. Validación consistencia documental (referencias cruzadas, numeración)

    Args:
        documento: Documento metadatos
        bloques: Bloques con contenido OCR (de Capa 3)

    Returns:
        DocumentPostCorrection con bloques corregidos + inconsistencias
    """

    bloques_corregidos = []
    bloques_pendientes_escalacion = []

    # Paso 1: Corregir cada bloque individualmente
    for bloque in bloques:
        resultado = _corregir_bloque(bloque)

        bloques_corregidos.append(resultado["bloque_corregido"])

        if resultado["requiere_escalacion"]:
            bloques_pendientes_escalacion.append(bloque.id)

    # Paso 2: Validar consistencia documental
    doc_correccion = validar_consistencia_documental(
        documento, bloques, bloques_corregidos
    )

    # Agregar bloques que requieren escalación de paso 1
    doc_correccion.bloques_pendientes_escalacion.extend(bloques_pendientes_escalacion)

    return doc_correccion


def _corregir_bloque(bloque: Bloque) -> dict:
    """Corrige un bloque individual.

    Aplica en orden:
    1. Normalización LaTeX
    2. Reparación estructural
    3. Corrección ortográfica

    Returns:
        {
            "bloque_corregido": BloqueCorregido,
            "requiere_escalacion": bool
        }
    """

    contenido_original = bloque.contenido.texto_plano or ""

    if not contenido_original.strip():
        return {
            "bloque_corregido": BloqueCorregido(
                id=bloque.id,
                contenido_normalizado="",
                reparaciones_aplicadas=[]
            ),
            "requiere_escalacion": False
        }

    contenido_actual = contenido_original
    todas_reparaciones = []
    requiere_escalacion = False

    # 1. Normalización LaTeX (si es bloque de fórmula)
    if bloque.tipo in (TipoBloque.FORMULA_DISPLAY, TipoBloque.FORMULA_INLINE):
        contenido_actual, repairs_latex = normalizar_latex(contenido_actual)
        todas_reparaciones.extend(repairs_latex)

    # 2. Reparación estructural (si contiene LaTeX)
    if '$' in contenido_actual or '\\' in contenido_actual:
        contenido_actual, repairs_struct, escala_struct = reparar_estructura(contenido_actual)
        todas_reparaciones.extend(repairs_struct)
        requiere_escalacion = requiere_escalacion or escala_struct

    # 3. Corrección ortográfica
    # Seleccionar diccionario según tipo de bloque
    if bloque.tipo == TipoBloque.CODIGO:
        # Código: no corregir ortografía
        pass
    elif bloque.tipo in (TipoBloque.FORMULA_DISPLAY, TipoBloque.FORMULA_INLINE):
        # Fórmulas: usar diccionario técnico
        diccionario = "tecnico_matematico"
        contenido_actual, repairs_ortografia = corregir_ortografia(
            contenido_actual, diccionario
        )
        todas_reparaciones.extend(repairs_ortografia)
    else:
        # Texto normal: usar diccionario general
        diccionario = "general"
        contenido_actual, repairs_ortografia = corregir_ortografia(
            contenido_actual, diccionario
        )
        todas_reparaciones.extend(repairs_ortografia)

    return {
        "bloque_corregido": BloqueCorregido(
            id=bloque.id,
            contenido_normalizado=contenido_actual,
            reparaciones_aplicadas=todas_reparaciones
        ),
        "requiere_escalacion": requiere_escalacion
    }


__all__ = [
    "corregir_documento",
    "normalizar_latex",
    "reparar_estructura",
    "corregir_ortografia",
]
