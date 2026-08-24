# Herramientas y Stack Tecnológico

Lenguaje base: **Python** (ecosistema OCR/ML).

## Extracción y renderizado de PDF

| Herramienta | Uso | Por qué |
|---|---|---|
| **PyMuPDF (`fitz`)** | Renderizar páginas a imagen, extraer texto nativo, inspeccionar fuentes embebidas | Rápido, permite controlar DPI por página/zona, expone metadata de fuentes necesaria para detectar contenido matemático en PDFs nativo-digitales sin necesidad de OCR |

## Motores de OCR especializados (Capa 3)

| Herramienta | Uso | Por qué |
|---|---|---|
| **EasyOCR** | OCR de texto plano general | Reemplaza a PaddleOCR: los wheels de PaddlePaddle requieren instrucciones AVX que el hardware de desarrollo (Intel Celeron N5100) no soporta — el proceso crashea al importar. EasyOCR es pytorch puro y corre sin problemas en este CPU |
| **docTR** | Detección de layout + reconocimiento de tablas | Reemplaza a PP-Structure por la misma razón (submódulo de PaddleOCR, mismo problema de AVX). Pytorch puro, resuelve segmentación de layout y estructura de tabla |
| **pix2tex (LaTeX-OCR)** | Reconocimiento de fórmulas matemáticas → LaTeX | Especializado en notación matemática, se usa tanto en bloques `formula_display` completos como en micro-segmentos `formula_inline` dentro de bloques de texto |
| **Tesseract** | Fallback / segunda opinión para consenso de confianza | No es el motor principal; se usa para comparar resultados con EasyOCR en segmentos dudosos antes de escalar a LLM — barato comparado con una llamada a LLM |

> **Nota (2026-08-21):** el stack original especificaba PaddleOCR/PP-Structure. Se descartaron por incompatibilidad de hardware (CPU sin AVX) en la máquina de desarrollo — ver arriba. Si el pipeline se despliega en un servidor con CPU compatible con AVX (o GPU), reevaluar volver a PaddleOCR/PP-Structure por su mejor manejo de layouts complejos.

## Corrección post-OCR (Capa 4, sin LLM)

- Diccionario ortográfico general del idioma + **diccionario técnico-matemático curado** (términos, notación en palabras, nombres propios de matemáticos) para evitar que un corrector genérico "arregle" términos legítimos.
- Parser ligero de sintaxis LaTeX (validación de balanceo de llaves/entornos, sin necesidad de compilar con `pdflatex` completo).
- Reglas de normalización de comandos LaTeX equivalentes (definidas como guía de estilo interna del pipeline).

## Traducción

| Herramienta | Uso |
|---|---|
| **NLLB-200** | Traducción local, modelo open-source multilingüe |
| **Opus-MT** | Traducción local, alternativa/complemento a NLLB-200 |
| LLM | Reservado únicamente para casos semánticos límite que los modelos locales no resuelven bien |

## Generación de plantillas

| Herramienta | Uso |
|---|---|
| **Jinja2** | Renderizado de salida final a LaTeX/Markdown/.ipynb, minimizando llamadas libres a LLM para tareas de formateo determinista |

## Orquestación

| Herramienta | Uso |
|---|---|
| **LangGraph** | Orquestador de agentes con máquinas de estado finitas explícitas — coordina el flujo entre capas del motor OCR, módulo de traducción y generación de plantillas |

## Escalación a LLM (Capa 5, último recurso)

- Modelo con capacidad de **visión** (no solo texto) — necesario porque el error casi siempre viene de algo que el engine determinista no pudo interpretar bien visualmente.
- Salida estructurada (JSON) con contenido corregido + confianza propia del modelo, para poder marcar casos de doble baja confianza (engine determinista + LLM) para revisión humana.
- Se usa el API de Anthropic (`/v1/messages`) para las llamadas de escalación.

## Indexación / Knowledge Graph

| Herramienta | Uso |
|---|---|
| **Graphify** | Transforma la salida estructurada del pipeline en un grafo de conocimiento consultable, permitiendo que agentes de IA recuperen solo el contexto relevante en vez de documentos completos |

> **Nota pendiente:** existen múltiples paquetes con el nombre "Graphify" (incluyendo `@sentropic/graphify` y `graphifyy` en PyPI). Antes de escribir la lógica de integración final, hay que confirmar cuál es el paquete específico que se va a usar, para no generar instrucciones de integración incorrectas.

## Resumen por capa del motor OCR

| Capa | Herramientas principales |
|---|---|
| 1. Triage | PyMuPDF |
| 2. Segmentación de layout | PyMuPDF (nativo-digital) / docTR (escaneado) |
| 3. OCR especializado | EasyOCR, pix2tex, docTR, Tesseract (fallback) |
| 4. Corrección post-OCR | Diccionarios curados, parser LaTeX ligero, reglas deterministas |
| 5. Escalación a LLM | API de Anthropic (visión + texto estructurado) |
