"""Agrupación de páginas contiguas con perfil de contenido similar en zonas DPI.

No se decide DPI estrictamente página por página: páginas 1-40 (texto
narrativo) -> zona DPI 200; páginas 41-65 (capítulo denso en fórmulas) ->
zona DPI 400. Esto simplifica la orquestación de renderizado sin perder el
ahorro de cómputo de la optimización clave de Capa 1: una página
nativo-digital sin fórmulas no pasa por OCR.
"""

from __future__ import annotations

from motor_ocr.modelos import TriageResult, ZonaDpi


def zonificar_paginas(resultados_por_pagina: list[TriageResult]) -> list[ZonaDpi]:
    if not resultados_por_pagina:
        return []

    zonas: list[ZonaDpi] = []
    zona_inicio = 0
    zona_dpi = resultados_por_pagina[0].dpi_objetivo
    zona_perfil = _obtener_perfil_dominante(resultados_por_pagina[0])

    for i in range(1, len(resultados_por_pagina)):
        actual = resultados_por_pagina[i]
        perfil_actual = _obtener_perfil_dominante(actual)

        # Change zone if DPI or dominant profile changes
        if actual.dpi_objetivo != zona_dpi or perfil_actual != zona_perfil:
            zonas.append(
                ZonaDpi(
                    paginas=(zona_inicio, i - 1),
                    dpi=zona_dpi,
                    perfil_dominante=zona_perfil,
                )
            )
            zona_inicio = i
            zona_dpi = actual.dpi_objetivo
            zona_perfil = perfil_actual

    # Add final zone
    zonas.append(
        ZonaDpi(
            paginas=(zona_inicio, len(resultados_por_pagina) - 1),
            dpi=zona_dpi,
            perfil_dominante=zona_perfil,
        )
    )

    return zonas


def _obtener_perfil_dominante(resultado: TriageResult) -> str:
    perfil = resultado.perfil_contenido
    ratios = {
        "texto": perfil.texto_ratio,
        "formula": perfil.formula_ratio,
        "tabla": perfil.tabla_ratio,
        "figura": perfil.figura_ratio,
    }
    return max(ratios, key=ratios.get)
