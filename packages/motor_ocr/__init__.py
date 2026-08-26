"""Motor OCR — pipeline determinista de 5 capas.

triage -> segmentation -> ocr_specialized -> correction -> escalation

Especificación completa en .contexto/ (raíz del proyecto):
- 01-arquitectura-general.md
- 02-herramientas-stack.md
- 03-capas-pipeline.md
- 04-estructura-proyecto.md
- 05-esquema-metadata-bloque-ocr.md
"""

import sys

# En Windows, la consola suele usar cp1252 en vez de UTF-8. Varias dependencias
# (easyocr/tqdm, etc.) imprimen barras de progreso con caracteres Unicode
# (p.ej. '█') que provocan UnicodeEncodeError y quedan silenciados por los
# try/except de los engines, devolviendo resultados vacíos sin avisar.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
