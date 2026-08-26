# Contribuir a motor-OCR

## Entorno de desarrollo

Requiere Python ≥ 3.11.

```bash
pip install -e ".[api,ui,dev]"
cd frontend && npm install
```

También hay una configuración de dev container
([`.devcontainer/`](.devcontainer/devcontainer.json)) con Tesseract y las
librerías de sistema que OpenCV y PyMuPDF necesitan ya instaladas.

## Pruebas

```bash
pytest -q
```

Algunas pruebas de integración usan un PDF real como fixture
(`pruebas/pdfs_de_prueba/c1.pdf` en el entorno de desarrollo original) y se
saltean automáticamente (`skipif`) si ese archivo no está presente — ese
corpus de prueba no se distribuye con el repositorio porque son libros de
texto con derechos de autor, no material propio. Para aportar un caso de
prueba nuevo, agregá un PDF del que tengas derecho de uso a
`pruebas/pdfs_de_prueba/` localmente, o generá uno sintético con
[`entrenamiento/generar_dataset_sintetico.py`](entrenamiento/generar_dataset_sintetico.py).

## Convenciones del proyecto

- **Determinismo antes que LLM.** Las capas 1 a 4 del pipeline
  (ver [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md)) no deben depender de un
  modelo de lenguaje. La escalación a LLM (capa 5) es el último recurso, y
  sólo para lo que no se pudo resolver con reglas.
- **Nombres en español** en el código del pipeline (`triage`, `layout`,
  `reconocimiento`, `correccion`, `escalacion`), consistente con el resto del
  proyecto.
- **Un formato a la vez.** El motor se refina primero para LaTeX y recién
  después para Markdown; si hay que elegir dónde invertir esfuerzo, LaTeX
  tiene prioridad.
- **Comentarios que expliquen el porqué, no el qué.** El código ya dice qué
  hace; un comentario vale cuando documenta una restricción no obvia o una
  decisión de diseño (ver los docstrings de
  [`pipeline.py`](packages/motor_ocr/pipeline.py) como referencia de tono).

## Reportar problemas

Al abrir un issue, indicá qué capa del pipeline está involucrada (ver
[`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md)) y, si es un problema de
fidelidad en la conversión, incluí el bloque de entrada y la salida obtenida:
la robustez del resultado es el criterio principal de este proyecto, más que
la velocidad.
