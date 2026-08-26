from .deteccion_fuentes import detectar_fuentes_matematicas
from .deteccion_origen import detectar_origen
from .perfil_visual import calcular_perfil_visual
from .zonificacion import zonificar_paginas

from motor_ocr.modelos import TriageResult, PerfilContenido, Origen
import fitz


def procesar_triage(ruta_pdf: str) -> tuple[list[TriageResult], list]:
    """
    Procesa un PDF completo a través de Capa 1 (Triage).

    Retorna:
    - lista de TriageResult (uno por página)
    - lista de ZonaDpi (agrupaciones de páginas por perfil)
    """
    doc = fitz.open(ruta_pdf)
    total_paginas = len(doc)
    doc.close()

    resultados = []
    for pagina_num in range(total_paginas):
        origen = detectar_origen(ruta_pdf, pagina_num)

        # Detect mathematical fonts if native-digital
        fuentes_detectadas = []
        if origen == Origen.NATIVO_DIGITAL:
            fuentes_detectadas = detectar_fuentes_matematicas(ruta_pdf, pagina_num)

        # Calculate visual profile
        if origen == Origen.ESCANEADO:
            perfil = calcular_perfil_visual(ruta_pdf, pagina_num, dpi=150)
        else:
            # Native-digital pages: use font detection for profile
            has_math_fonts = len(fuentes_detectadas) > 0
            perfil = PerfilContenido(
                texto_ratio=1.0 if not has_math_fonts else 0.7,
                formula_ratio=0.3 if has_math_fonts else 0.0,
                tabla_ratio=0.0,
                figura_ratio=0.0,
            )

        # Determine DPI and whether OCR is needed
        if origen == Origen.NATIVO_DIGITAL and len(fuentes_detectadas) == 0:
            dpi_objetivo = 200
            requiere_ocr = False
        elif origen == Origen.ESCANEADO:
            # Adjust DPI based on content profile
            if perfil.formula_ratio > 0.3:
                dpi_objetivo = 400
            elif perfil.tabla_ratio > 0.2:
                dpi_objetivo = 300
            else:
                dpi_objetivo = 200
            requiere_ocr = True
        else:
            dpi_objetivo = 300 if perfil.formula_ratio > 0.2 else 200
            requiere_ocr = len(fuentes_detectadas) > 0

        resultado = TriageResult(
            pagina=pagina_num,
            origen=origen.value,
            perfil_contenido=perfil,
            dpi_objetivo=dpi_objetivo,
            requiere_ocr=requiere_ocr,
            fuentes_detectadas=fuentes_detectadas,
        )
        resultados.append(resultado)

    # Zone pages by similar profiles
    zonas = zonificar_paginas(resultados)

    return resultados, zonas


__all__ = [
    "procesar_triage",
    "zonificar_paginas",
    "detectar_origen",
    "detectar_fuentes_matematicas",
    "calcular_perfil_visual",
]
