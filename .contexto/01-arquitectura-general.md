# Arquitectura General

## Propósito

Plataforma SaaS para conversión, procesamiento, traducción y generación de documentación académica avanzada. Convierte PDFs densos (artículos, informes, libros de matemática compleja) a LaTeX, Markdown y `.ipynb`, con traducción integrada y funciones adicionales de diseño de arquitectura textual.

## Cliente objetivo

Personas que descargan PDFs y necesitan formatos limpios y editables — no solo por conveniencia, sino para poder practicar y aplicar el contenido con ayuda de IA u otros medios en proyectos y trabajos propios. La cuña de entrada del producto es la **conversión limpia y precisa**; la capa de "practicar/aplicar con IA" es una expansión posterior sobre la misma base de contenido bien estructurado.

## Diferenciación

- Precisión antes que velocidad, sin límite artificial de páginas por documento (cobro por nivel de trabajo real ejercido, no por conteo de páginas).
- Automatización configurada por proceso, evitando reconfiguración manual en cada documento.
- Capacidad específica para libros de matemática densa y avanzada — el punto donde la competencia (Mathpix, conversores genéricos, o pegar el PDF directo en un chat de IA general) falla de forma más consistente: documentos largos y estructuralmente complejos, notación matemática avanzada, ausencia de salida a `.ipynb`, traducción no integrada al flujo.

## Principios de diseño (aplican a todo el sistema, no solo al OCR)

1. **Calidad sobre velocidad.** Toda decisión de arquitectura prioriza precisión sobre tiempo de procesamiento.
2. **Minimización de tokens/LLM como restricción de primera clase.** Los enfoques deterministas y locales son la norma; el LLM se reserva para casos de baja confianza o ambigüedad genuina, nunca como primer recurso.
3. **Graphify como restricción estructural desde el inicio.** El formato de salida de cada componente se diseña pensando en ser indexable como grafo de conocimiento, no se retrofitea después.
4. **Automatización determinista y explícita.** Máquinas de estado finitas explícitas en lugar de comportamiento de agente ambiguo.

## Componentes de la plataforma

```
┌─────────────────────────────────────────────────────────┐
│                    Orquestador de Agentes                 │
│              (LangGraph, máquinas de estado)               │
└───────────────┬─────────────────────────────┬─────────────┘
                │                             │
    ┌───────────▼───────────┐     ┌───────────▼───────────┐
    │     Motor OCR           │     │  Módulo de Traducción   │
    │  (5 capas, ver          │     │  (NLLB-200, Opus-MT,     │
    │   03-capas-pipeline.md) │     │   LLM en casos límite)   │
    └───────────┬───────────┘     └───────────┬───────────┘
                │                             │
                └──────────────┬──────────────┘
                              │
                ┌───────────▼───────────┐
                │  Generación de Plantillas │
                │       (Jinja2)             │
                └───────────┬───────────┘
                            │
                ┌───────────▼───────────┐
                │  Salida estructurada       │
                │  JSON / Markdown / LaTeX /  │
                │  .ipynb — indexable por     │
                │  Graphify                   │
                └─────────────────────────┘
```

## Componentes detallados

| Componente | Función | Documento relacionado |
|---|---|---|
| Motor OCR | Convierte imágenes de página en bloques de contenido estructurado y corregido | `03-capas-pipeline.md` |
| Módulo de traducción | Traduce contenido con modelos locales, LLM solo para casos semánticos límite | (pendiente de detallar) |
| Generación de plantillas | Renderiza el contenido final a LaTeX/Markdown/.ipynb vía Jinja2, minimizando llamadas libres a LLM | (pendiente de detallar) |
| Orquestador de agentes | Coordina el flujo completo con máquinas de estado explícitas (LangGraph) | (pendiente de detallar) |
| Graphify | Indexa la salida estructurada como grafo de conocimiento consultable por agentes | `05-esquema-metadata-bloque-ocr.md` |

Este documento cubre el sistema completo; el resto de la documentación técnica en esta carpeta se enfoca específicamente en el **motor OCR**, que es el componente que se está implementando primero.
