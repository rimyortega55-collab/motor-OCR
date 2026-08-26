"""Pase visual barato (~150 DPI) para páginas escaneadas, heurísticas rápidas.

- Densidad de componentes conectados pequeños y aislados -> indicio de fórmulas.
- Líneas rectas en rejilla (Hough) -> indicio de tabla.
- Regiones grandes de tono uniforme no textual -> indicio de figura/diagrama.
- Densidad de texto corrido, líneas parejas -> texto plano.

No usa modelos pesados; es la señal que alimenta `PerfilContenido` en
`TriageResult`.
"""

from __future__ import annotations

from motor_ocr.modelos import PerfilContenido


def calcular_perfil_visual(ruta_pdf: str, pagina: int, dpi: int = 150) -> PerfilContenido:
    import cv2
    import fitz
    import numpy as np

    doc = fitz.open(ruta_pdf)
    if pagina < 0 or pagina >= len(doc):
        return PerfilContenido(
            texto_ratio=0.0,
            formula_ratio=0.0,
            tabla_ratio=0.0,
            figura_ratio=0.0,
        )

    page = doc[pagina]
    # Render at low resolution
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    doc.close()

    # Convert to grayscale
    if img_data.shape[2] == 3:
        gray = cv2.cvtColor(img_data, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_data[:, :, 0]

    # Detect connected components (small isolated components suggest formulas)
    _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    num_labels, labels = cv2.connectedComponents(binary)

    # Calculate heuristics
    small_components = 0
    total_foreground = cv2.countNonZero(binary)
    for i in range(1, num_labels):
        component_size = np.sum(labels == i)
        if component_size < 50:  # small isolated components
            small_components += 1

    # Detect lines using Hough transform (tables)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 50)
    num_lines = len(lines) if lines is not None else 0

    # Detect large uniform regions (figures/diagrams)
    # Dilate binary to merge close components
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dilated = cv2.dilate(binary, kernel, iterations=2)
    _, labels_dilated = cv2.connectedComponents(dilated)

    large_regions = 0
    for i in range(1, labels_dilated.max() + 1):
        region_size = np.sum(labels_dilated == i)
        total_pixels = gray.shape[0] * gray.shape[1]
        if region_size > total_pixels * 0.05:  # > 5% of page
            large_regions += 1

    # Estimate ratios (simplified heuristic)
    total_pixels = gray.shape[0] * gray.shape[1]
    foreground_ratio = total_foreground / total_pixels if total_pixels > 0 else 0

    formula_ratio = (small_components / max(num_labels, 1)) * 0.3
    tabla_ratio = min(num_lines / 50, 0.3) if num_lines > 0 else 0
    figura_ratio = large_regions * 0.15
    texto_ratio = foreground_ratio * 0.5

    # Normalize to sum to 1
    total = formula_ratio + tabla_ratio + figura_ratio + texto_ratio
    if total > 0:
        formula_ratio /= total
        tabla_ratio /= total
        figura_ratio /= total
        texto_ratio /= total

    return PerfilContenido(
        texto_ratio=float(texto_ratio),
        formula_ratio=float(formula_ratio),
        tabla_ratio=float(tabla_ratio),
        figura_ratio=float(figura_ratio),
    )
