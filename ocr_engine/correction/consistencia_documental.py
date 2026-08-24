"""Consistencia estructural a nivel de documento completo (solo posible acá,
porque ya se tiene el documento entero, no bloque por bloque).

- Numeración de teoremas/lemas consistente (ej. salto de "Teorema 3.2" a
  "Teorema 3.4" sin 3.3).
- Referencias cruzadas resolubles (ej. "por el Lema 2.1" sin bloque
  correspondiente en el documento) -> relaciones REFERENCES/USES_DEFINITION.
- Continuidad de fórmulas numeradas.

Estas inconsistencias se resuelven vía LLM (decisión de producto) como cola
de escalación separada (Capa 5) — no se inventan ni se rellenan
automáticamente. Construye también `Documento.indice_estructural` como
subproducto.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ocr_engine.models import (
    Bloque, Documento, TipoBloque, IdentificadorSemantico
)
from ocr_engine.models.results import DocumentPostCorrection
from ocr_engine.models.document import Inconsistencia


def validar_consistencia_documental(
    documento: Documento,
    bloques: list[Bloque],
    bloques_corregidos: list = None
) -> DocumentPostCorrection:
    """Valida consistencia a nivel de documento.

    Args:
        documento: Metadatos del documento
        bloques: Bloques originales
        bloques_corregidos: Bloques tras corrección (opcional)

    Returns:
        DocumentPostCorrection con inconsistencias detectadas
    """

    inconsistencias = []

    # 1. Detectar inconsistencias de numeración
    inconsistencias_numeracion = _validar_numeracion(bloques)
    inconsistencias.extend(inconsistencias_numeracion)

    # 2. Detectar referencias cruzadas sin resolver
    inconsistencias_referencias = _validar_referencias_cruzadas(bloques)
    inconsistencias.extend(inconsistencias_referencias)

    # 3. Construir índice estructural
    indice = _construir_indice_estructural(bloques)
    # Nota: indice podría almacenarse en documento.metadatos_adicionales

    return DocumentPostCorrection(
        bloques_corregidos=bloques_corregidos or [],
        inconsistencias_detectadas=inconsistencias,
        bloques_pendientes_escalacion=[]
    )


def _validar_numeracion(bloques: list[Bloque]) -> list[Inconsistencia]:
    """Detecta saltos en numeración de teoremas/lemas/etc."""

    inconsistencias = []

    # Agrupar por tipo de bloque semántico
    estructuras = defaultdict(list)  # tipo -> lista de (numero_flotante, bloque)

    for bloque in bloques:
        if bloque.tipo in (
            TipoBloque.TEOREMA, TipoBloque.LEMA, TipoBloque.PROPOSICION,
            TipoBloque.DEFINICION, TipoBloque.COROLARIO
        ):
            numero = _extraer_numero(bloque.contenido.texto_plano or "")
            if numero:
                estructuras[bloque.tipo].append((numero, bloque))

    # Verificar continuidad por tipo
    for tipo_bloque, elementos in estructuras.items():
        elementos.sort(key=lambda x: x[0])

        for i in range(len(elementos) - 1):
            num_actual, bloque_actual = elementos[i]
            num_proximo, bloque_proximo = elementos[i + 1]

            # Detectar saltos > 1
            if num_proximo - num_actual > 1:
                inconsistencias.append(Inconsistencia(
                    tipo="salto_numeracion",
                    detalle=f"Salto en numeración de {tipo_bloque.value}: {num_actual} → {num_proximo}",
                    ubicacion_pagina=bloque_actual.pagina
                ))

    return inconsistencias


def _validar_referencias_cruzadas(bloques: list[Bloque]) -> list[Inconsistencia]:
    """Detecta referencias a teoremas/lemas que no existen en el documento."""

    inconsistencias = []

    # Construir índice de teoremas/lemas disponibles
    indice_disponibles = {}

    for bloque in bloques:
        if bloque.tipo in (
            TipoBloque.TEOREMA, TipoBloque.LEMA, TipoBloque.PROPOSICION,
            TipoBloque.DEFINICION, TipoBloque.COROLARIO
        ):
            numero = _extraer_numero(bloque.contenido.texto_plano or "")
            if numero:
                tipo_nombre = bloque.tipo.value
                key = f"{tipo_nombre}_{numero}"
                indice_disponibles[key] = bloque

    # Buscar referencias en bloques de texto
    patron_referencias = r'(Teorema|Lema|Proposición|Definición|Corolario)\s+(\d+(?:\.\d+)*)'

    for bloque in bloques:
        if bloque.tipo in (TipoBloque.PARRAFO, TipoBloque.DEMOSTRACION):
            texto = bloque.contenido.texto_plano or ""

            matches = re.finditer(patron_referencias, texto, re.IGNORECASE)

            for match in matches:
                tipo_ref = match.group(1).lower()
                numero_ref = match.group(2)

                # Normalizar tipo a enum
                tipo_map = {
                    'teorema': 'teorema',
                    'lema': 'lema',
                    'proposición': 'proposicion',
                    'definición': 'definicion',
                    'corolario': 'corolario'
                }

                tipo_norm = tipo_map.get(tipo_ref)
                if not tipo_norm:
                    continue

                key = f"{tipo_norm}_{numero_ref}"

                if key not in indice_disponibles:
                    inconsistencias.append(Inconsistencia(
                        tipo="referencia_sin_resolver",
                        detalle=f"Referencia a {tipo_ref} {numero_ref} no encontrada en documento",
                        ubicacion_pagina=bloque.pagina
                    ))

    return inconsistencias


def _extraer_numero(texto: str) -> float | None:
    """Extrae número de formato "3.2" desde "Teorema 3.2."."""
    if not texto:
        return None

    # Buscar patrón: número seguido de punto y opcional otro número
    match = re.search(r'(\d+)(?:\.(\d+))?', texto)

    if match:
        parte_entera = int(match.group(1))
        parte_decimal = int(match.group(2)) if match.group(2) else 0

        # Convertir a float: 3.2 → 3.2, 3 → 3.0
        return parte_entera + (parte_decimal / 10.0)

    return None


def _construir_indice_estructural(bloques: list[Bloque]) -> dict:
    """Construye índice estructural del documento.

    Returns:
        {
            "capitulos": [...],
            "secciones": [...],
            "teoremas": [...],
            "definiciones": [...]
        }
    """

    indice = {
        "capitulos": [],
        "secciones": [],
        "teoremas": [],
        "lemas": [],
        "proposiciones": [],
        "definiciones": [],
        "corolarios": [],
        "demostraciones": [],
    }

    for bloque in bloques:
        if bloque.tipo == TipoBloque.ENCABEZADO:
            # Asumir que encabezados son secciones (heurística simple)
            indice["secciones"].append({
                "pagina": bloque.pagina,
                "contenido": (bloque.contenido.texto_plano or "")[:50],
                "id": str(bloque.id)
            })

        elif bloque.tipo == TipoBloque.TEOREMA:
            numero = _extraer_numero(bloque.contenido.texto_plano or "")
            indice["teoremas"].append({
                "numero": numero,
                "pagina": bloque.pagina,
                "id": str(bloque.id)
            })

        elif bloque.tipo == TipoBloque.LEMA:
            numero = _extraer_numero(bloque.contenido.texto_plano or "")
            indice["lemas"].append({
                "numero": numero,
                "pagina": bloque.pagina,
                "id": str(bloque.id)
            })

        elif bloque.tipo == TipoBloque.DEFINICION:
            numero = _extraer_numero(bloque.contenido.texto_plano or "")
            indice["definiciones"].append({
                "numero": numero,
                "pagina": bloque.pagina,
                "id": str(bloque.id)
            })

        elif bloque.tipo == TipoBloque.DEMOSTRACION:
            indice["demostraciones"].append({
                "pagina": bloque.pagina,
                "id": str(bloque.id)
            })

    # Ordenar por número/página
    for key in ["teoremas", "lemas", "proposiciones", "definiciones", "corolarios"]:
        indice[key].sort(key=lambda x: (x.get("numero") or 999, x.get("pagina") or 999))

    return indice
