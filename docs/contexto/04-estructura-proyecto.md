# Estructura de Proyecto — Motor OCR

Estructura de carpetas y módulos propuesta, alineada 1:1 con las 5 capas definidas en `03-capas-pipeline.md`. Pensada para implementarse de forma incremental con Claude Code, capa por capa, con pruebas reales entre cada una.

```
ocr_engine/
├── pyproject.toml / requirements.txt
├── config/
│   └── settings.py              # umbrales de confianza, DPI por defecto, límites de concurrencia
│
├── models/                      # esquemas de datos compartidos (Pydantic)
│   ├── document.py              # Documento, ZonaDPI, IndiceEstructural
│   ├── block.py                 # Block, taxonomía de tipos, relaciones
│   └── results.py               # TriageResult, BlockOCRResult, EscalationResult, etc.
│
├── triage/                      # Capa 1
│   ├── deteccion_origen.py      # nativo-digital vs escaneado (PyMuPDF)
│   ├── deteccion_fuentes.py     # fuentes matemáticas embebidas
│   ├── perfil_visual.py         # heurísticas de baja resolución (escaneado)
│   └── zonificacion.py          # agrupación de páginas en zonas DPI
│
├── segmentation/                # Capa 2
│   ├── nativo_digital.py        # segmentación por estructura del PDF
│   ├── escaneado.py             # segmentación vía PP-Structure
│   ├── taxonomia.py             # reglas de clasificación semántica (teorema/lema/etc.)
│   └── orden_lectura.py         # resolución de columnas múltiples
│
├── ocr_specialized/              # Capa 3
│   ├── sub_segmentacion.py      # detección de fórmulas inline dentro de bloques de texto
│   ├── engines/
│   │   ├── easyocr_engine.py
│   │   ├── pix2tex_engine.py
│   │   ├── doctr_engine.py
│   │   └── tesseract_fallback.py
│   ├── enrutador.py             # enrutamiento por tipo de bloque
│   └── confianza.py             # combinación de las tres señales de confianza
│
├── correction/                   # Capa 4
│   ├── normalizacion_latex.py
│   ├── reparacion_estructural.py # balanceo de llaves/entornos
│   ├── ortografia.py            # corrección quirúrgica con diccionario técnico
│   └── consistencia_documental.py # numeración, referencias cruzadas
│
├── escalation/                   # Capa 5
│   ├── cola_micro_segmentos.py
│   ├── cola_inconsistencias.py
│   ├── batching.py
│   ├── cliente_llm.py           # llamadas al API de Anthropic con control de concurrencia
│   └── costo_tracking.py
│
├── pipeline.py                   # orquestador end-to-end (LangGraph, máquina de estados)
├── metadata/
│   └── exportador_graphify.py   # ensambla la salida final según 05-esquema-metadata-bloque-ocr.md
│
└── tests/
    ├── fixtures/                 # PDFs de prueba reales (texto plano, fórmulas densas, tablas, escaneado)
    ├── test_triage.py
    ├── test_segmentation.py
    ├── test_ocr_specialized.py
    ├── test_correction.py
    └── test_escalation.py
```

## Orden de implementación sugerido

1. `models/` — definir los esquemas de datos primero; todo lo demás depende de ellos.
2. `triage/` — validar con PDFs reales de distintos tipos (nativo-digital limpio, escaneado, mixto) antes de avanzar.
3. `segmentation/` — probar especialmente el caso de dos columnas y la taxonomía semántica extendida.
4. `ocr_specialized/` — empezar con el enrutamiento básico (texto/fórmula/tabla) antes de afinar la sub-segmentación de fórmulas inline.
5. `correction/` — se puede desarrollar en paralelo a `ocr_specialized/` una vez que el formato de bloque esté estable.
6. `escalation/` — implementar al final; depende de tener bloques reales de baja confianza generados por las capas anteriores para probar el batching.
7. `pipeline.py` — conectar todo con la orquestación de LangGraph una vez que cada capa funcione de forma aislada.
8. `metadata/exportador_graphify.py` — última pieza, ensambla la salida final.

## Notas de implementación

- Cada módulo de capa debe exponer una función/clase con **una sola responsabilidad clara** y un contrato de entrada/salida que coincida exactamente con lo definido en `03-capas-pipeline.md` — esto facilita probar cada capa de forma aislada con fixtures reales antes de conectar el pipeline completo.
- Los engines en `ocr_specialized/engines/` deben tener una interfaz común (mismo método de entrada/salida) para poder intercambiarlos o agregar nuevos sin modificar `enrutador.py`.
- `config/settings.py` centraliza todos los umbrales (confianza mínima, DPI por defecto, límite de concurrencia hacia el LLM) para poder ajustarlos sin tocar lógica de negocio — importante dado que estos umbrales se van a calibrar con datos reales de uso (ver tracking de costo en Capa 5).
