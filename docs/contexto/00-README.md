# Documentación Técnica — Motor OCR

Especificación completa del motor de conversión de documentos académicos densos (PDF → LaTeX / Markdown / .ipynb), diseñado para ser implementado con Claude Code.

## Índice

| Documento | Contenido |
|---|---|
| [01-arquitectura-general.md](./01-arquitectura-general.md) | Principios de diseño, visión general del sistema, componentes de la plataforma |
| [02-herramientas-stack.md](./02-herramientas-stack.md) | Stack tecnológico, librerías por función, justificación de cada elección |
| [03-capas-pipeline.md](./03-capas-pipeline.md) | Definición detallada de las 5 capas del motor OCR: lógica, contratos de entrada/salida, decisiones de diseño |
| [04-estructura-proyecto.md](./04-estructura-proyecto.md) | Estructura de carpetas y módulos propuesta para la implementación |
| [05-esquema-metadata-bloque-ocr.md](./05-esquema-metadata-bloque-ocr.md) | Esquema de metadata a nivel de bloque, compatible con Graphify |

## Cómo usar esta documentación con Claude Code

1. Copia toda la carpeta `docs/` a la raíz de tu repositorio.
2. En tu primer prompt a Claude Code, referencia este README para que cargue el contexto completo antes de escribir código.
3. Sigue el orden de implementación sugerido en `04-estructura-proyecto.md` — capa por capa, con pruebas reales entre cada una.

## Principios que atraviesan todos los documentos

- **Calidad antes que velocidad.**
- **Minimización de tokens/LLM como restricción de primera clase** — todo lo determinista se resuelve sin IA; el LLM es el último recurso.
- **Trazabilidad de confianza y costo** en cada bloque procesado.
- **Diseño orientado a Graphify desde el inicio** — la salida del pipeline no es solo texto convertido, es un grafo de conocimiento indexable.
