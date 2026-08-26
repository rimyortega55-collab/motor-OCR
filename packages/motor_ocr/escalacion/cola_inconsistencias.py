"""Cola 2 — inconsistencias documentales (origen: Capa 4).

Problema de "qué falta o qué está mal conectado", no de transcripción — no
requiere imagen, requiere contexto estructural en texto. Unidad de
batching: todas las inconsistencias del documento en una sola llamada (o
pocas, si excede context window razonable). Se envía: índice estructural +
fragmentos de texto inmediatamente antes/después de cada inconsistencia.

Regla crítica: si el LLM concluye que falta un bloque, NO genera contenido
nuevo. Marca la zona para reprocesamiento (segunda pasada de Capa 2 más
agresiva) o revisión humana. Inventar contenido matemático faltante es
inaceptable para la promesa de precisión del producto.
"""

from __future__ import annotations

from motor_ocr.modelos import Documento, Inconsistencia, EscalationResult
from .cliente_llm import llamar_llm_inconsistencia


def resolver_inconsistencias(
    documento: Documento,
    bloques: list,
    inconsistencias: list[Inconsistencia]
) -> list[EscalationResult]:
    """Resuelve inconsistencias documentales con LLM.

    Args:
        documento: Documento (para metadatos)
        bloques: Bloques del documento (para contexto)
        inconsistencias: Lista de inconsistencias detectadas

    Returns:
        Lista de EscalationResult, uno por inconsistencia
    """

    if not inconsistencias:
        return []

    # Construir índice estructural a partir de bloques
    indice = _construir_indice_desde_bloques(bloques)

    # Agrupar inconsistencias por tipo
    resultados = []

    # Procesar todas las inconsistencias en una sola llamada al LLM
    fragmentos_contexto = []

    for inconsistencia in inconsistencias:
        # Encontrar fragmentos de contexto relacionados
        contexto = _extraer_contexto_inconsistencia(
            bloques, inconsistencia
        )

        fragmentos_contexto.append({
            "tipo": inconsistencia.tipo,
            "detalle": inconsistencia.detalle,
            "ubicacion_pagina": inconsistencia.ubicacion_pagina,
            "contexto_antes": contexto.get("antes", ""),
            "contexto_despues": contexto.get("despues", "")
        })

    # Llamada única al LLM con todas las inconsistencias
    resultado_lote = llamar_llm_inconsistencia(
        indice_estructural=indice,
        fragmentos_contexto=fragmentos_contexto
    )

    # Crear un resultado por inconsistencia (compartiendo análisis)
    for i, inconsistencia in enumerate(inconsistencias):
        resultado = EscalationResult(
            cola_origen="inconsistencia_documental",
            contenido_final=resultado_lote.contenido_final,
            confianza_llm=resultado_lote.confianza_llm,
            requiere_revision_humana=resultado_lote.requiere_revision_humana,
            costo=resultado_lote.costo,
            razon_escalacion=f"Inconsistencia {i+1}/{len(inconsistencias)}: {resultado_lote.razon_escalacion}"
        )

        resultados.append(resultado)

    return resultados


def _construir_indice_desde_bloques(bloques: list) -> dict:
    """Construye índice estructural simple desde bloques."""

    from motor_ocr.modelos import TipoBloque

    indice = {
        "teoremas": [],
        "lemas": [],
        "proposiciones": [],
        "definiciones": [],
        "corolarios": [],
        "demostraciones": []
    }

    for bloque in bloques:
        if bloque.tipo == TipoBloque.TEOREMA:
            numero = _extraer_numero_desde_contenido(bloque.contenido.texto_plano or "")
            if numero:
                indice["teoremas"].append({
                    "numero": numero,
                    "pagina": bloque.pagina,
                    "id": str(bloque.id)
                })

        elif bloque.tipo == TipoBloque.LEMA:
            numero = _extraer_numero_desde_contenido(bloque.contenido.texto_plano or "")
            if numero:
                indice["lemas"].append({
                    "numero": numero,
                    "pagina": bloque.pagina,
                    "id": str(bloque.id)
                })

        elif bloque.tipo == TipoBloque.DEFINICION:
            numero = _extraer_numero_desde_contenido(bloque.contenido.texto_plano or "")
            if numero:
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

    # Ordenar por número
    for key in ["teoremas", "lemas", "proposiciones", "definiciones", "corolarios"]:
        indice[key].sort(key=lambda x: (x.get("numero") or 999, x.get("pagina") or 999))

    return indice


def _extraer_contexto_inconsistencia(bloques: list, inconsistencia: Inconsistencia) -> dict:
    """Extrae texto de contexto antes/después de una inconsistencia."""

    pagina = inconsistencia.ubicacion_pagina

    # Encontrar bloques en la página
    bloques_pagina = [b for b in bloques if b.pagina == pagina]

    contexto_antes = ""
    contexto_despues = ""

    if bloques_pagina:
        # Tomar últimos 50 chars antes y primeros 50 después
        if len(bloques_pagina) > 0:
            contexto_antes = (bloques_pagina[0].contenido.texto_plano or "")[-100:]

        if len(bloques_pagina) > 1:
            contexto_despues = (bloques_pagina[-1].contenido.texto_plano or "")[:100]

    return {
        "antes": contexto_antes,
        "despues": contexto_despues
    }


def _extraer_numero_desde_contenido(texto: str) -> str | None:
    """Extrae número como string desde contenido de bloque."""

    import re

    match = re.search(r'(\d+(?:\.\d+)?)', texto)
    if match:
        return match.group(1)

    return None
