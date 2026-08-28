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

from motor_ocr.modelos import (
    Bloque, Documento, TipoBloque, IdentificadorSemantico
)
from motor_ocr.modelos.results import DocumentPostCorrection
from motor_ocr.modelos.document import Inconsistencia


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

    # Verificar continuidad por tipo. Sólo se comparan elementos que comparten
    # prefijo -es decir, que viven en el mismo capítulo o sección-: pasar del
    # "Teorema 3.7" al "Teorema 4.1" no es un salto, es el capítulo siguiente,
    # y contarlo como inconsistencia llenaría la cola de escalación de ruido en
    # todo documento con más de un capítulo.
    for tipo_bloque, elementos in estructuras.items():
        por_prefijo = defaultdict(list)
        for numero, bloque in elementos:
            por_prefijo[numero[:-1]].append((numero, bloque))

        for elementos_del_prefijo in por_prefijo.values():
            elementos_del_prefijo.sort(key=lambda x: x[0])

            for i in range(len(elementos_del_prefijo) - 1):
                num_actual, bloque_actual = elementos_del_prefijo[i]
                num_proximo, _ = elementos_del_prefijo[i + 1]

                if num_proximo[-1] - num_actual[-1] > 1:
                    inconsistencias.append(Inconsistencia(
                        tipo="salto_numeracion",
                        detalle=(
                            f"Salto en numeración de {tipo_bloque.value}: "
                            f"{_numero_a_texto(num_actual)} → {_numero_a_texto(num_proximo)}"
                        ),
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
                key = f"{tipo_nombre}_{_numero_a_texto(numero)}"
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


def _extraer_numero(texto: str) -> tuple[int, ...] | None:
    """Extrae la numeración de "Teorema 3.2." como la tupla (3, 2).

    La numeración de un documento no es un número decimal: "3.2" quiere decir
    capítulo 3, elemento 2. Modelarla como `float` -3 + 2/10- parece
    inofensivo y rompe dos cosas a la vez. El salto de 3.2 a 3.4 pasa a valer
    0.2, con lo cual ningún umbral razonable lo detecta y el validador queda
    inerte; y a partir del décimo elemento el mapeo deja de ser inyectivo,
    porque "3.10" y "4" caen los dos en 4.0.

    Con una tupla de enteros la comparación es exacta y ordena bien: (3, 9)
    viene antes de (3, 10), que es lo que un lector espera.
    """
    if not texto:
        return None

    match = re.search(r'\d+(?:\.\d+)*', texto)
    if not match:
        return None

    return tuple(int(parte) for parte in match.group(0).split("."))


def _numero_a_texto(numero: tuple[int, ...]) -> str:
    """(3, 2) -> "3.2". Es la forma canónica con la que se arman las claves."""
    return ".".join(str(parte) for parte in numero)


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
