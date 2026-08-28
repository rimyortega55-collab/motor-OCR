# motor-OCR

Motor híbrido de OCR para convertir PDF matemático a LaTeX y Markdown: un
pipeline determinista propio que localiza y extrae todo el documento, más
modelos de IA especializados que resuelven sólo lo que ese motor no puede
hacer con reglas (matemática compleja, casos ambiguos).

No es un modelo de visión-lenguaje de extremo a extremo. La mayoría de un PDF
académico es prosa, y PyMuPDF la extrae exacta y gratis; en el corpus de
prueba la matemática es apenas 0,5%–6,7% de los caracteres. Por eso el motor
propio hace el trabajo pesado y la IA se reserva para donde realmente hace
falta.

Proyecto open source, con la API y el frontend mantenidos como parte del
mismo repositorio — el frontend está pensado para quienes no programan, no es
un añadido opcional.

## Arquitectura: pipeline de 7 capas

```
1. Triage              clasifica cada página (origen, perfil, DPI)
2. Segmentación         divide la página en bloques semánticos
3. OCR especializado    enruta cada bloque al motor que le corresponde
                        (EasyOCR, docTR, pix2tex, Tesseract como respaldo)
4. Corrección           normalización, reparación y ortografía deterministas
5. Escalación a LLM     sólo para los casos que quedan ambiguos tras 1-4
6. Revisión humana      cola de revisión con feedback hacia el pipeline
7. Interfaz web         API + frontend, con auto-ajuste de umbrales
```

Cada documento se puede procesar en uno de dos modos, que se eligen al subirlo
y sólo cambian la capa 3: **híbrido** (el default y el recomendado — el motor
determinista resuelve todo lo que puede y el modelo de IA ve sólo los recortes
de fórmula) o **sólo modelo de IA** (todos los bloques van al modelo, útil para
evaluar el modelo por separado o para PDFs con la capa de texto rota, a costa
de bastante más tiempo). Ver
[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md#modo-de-reconocimiento-híbrido-o-sólo-modelo-de-ia).

Las capas 1 a 4 son 100% deterministas. La capa 5 es la única que llama a un
LLM, y sólo para lo que el resto del pipeline no resolvió con confianza. El
motor se refina un formato a la vez: primero LaTeX, después Markdown.

El plan de mediano plazo es hacerle fine-tuning a un modelo open source ya
entrenado (candidato: pix2tex/LaTeX-OCR, ya integrado como motor determinista
en [`pix2tex_engine.py`](packages/motor_ocr/reconocimiento/engines/pix2tex_engine.py))
para mejorar el reconocimiento matemático, en vez de entrenar un modelo desde
cero o reemplazar el pipeline determinista.

## Estructura del repositorio

```
packages/
  motor_ocr/          núcleo del pipeline (triage, layout, reconocimiento,
                       corrección, escalación, traducción)
  motor_ocr_api/       backend FastAPI: sin cuentas —clave única opcional de
                       instancia—, subida, revisión, traducción, administración
  motor_ocr_render/    renderizado de resultados (LaTeX, Markdown)
frontend/              SPA en React + TypeScript + Vite
entrenamiento/         fine-tuning y evaluación de pix2tex
tests/                 pruebas de pytest del núcleo y la API
docs/                  arquitectura del pipeline
```

El núcleo (`motor_ocr`) se instala solo, sin arrastrar un framework web: quien
quiera convertir un PDF desde un script no necesita la API ni una base de
datos.

## Instalación

Requiere Python ≥ 3.11.

```bash
pip install -e ".[api,ui,dev]"
```

Extras disponibles:

| Extra | Para qué |
|---|---|
| `api` | FastAPI, Uvicorn, SQLAlchemy — necesario para levantar el backend |
| `ui` | Streamlit, pandas, plotly — demo standalone sin el frontend en React |
| `dev` | pytest |
| `train` | dependencias adicionales para el fine-tuning de pix2tex en `entrenamiento/` |

Para el frontend, además:

```bash
cd frontend && npm install
```

## Cómo correr

```bash
# Pruebas
pytest -q

# API (FastAPI)
uvicorn motor_ocr_api.api:app --reload

# Frontend en desarrollo (Vite en :5173, proxea /api a :8000)
cd frontend && npm run dev

# Frontend compilado (FastAPI lo sirve directamente, un solo origen)
cd frontend && npm run build
```

Variables de entorno relevantes:

| Variable | Para qué |
|---|---|
| `MOTOR_OCR_DATA_DIR` | Dónde viven la base SQLite, los PDF y el caché de páginas. Por defecto `datos/` |
| `DATABASE_URL` | Apuntar a Postgres en vez de SQLite, sin tocar código |
| `MOTOR_OCR_COOKIE_SEGURA=0` | Apaga el flag `Secure` de la cookie de sesión, para servir por HTTP plano (no hace falta en `localhost`) |
| `MOTOR_OCR_UMBRAL_CONFIANZA_GLOBAL_ESCALACION` | Ajusta el umbral de confianza que decide qué bloques entran a la cola de revisión humana |

Documentación más detallada en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).
La API no tiene un contrato estático: FastAPI genera documentación
interactiva en `/docs` (Swagger UI) con el servidor corriendo.

## Entrenar el modelo matemático en Google Colab

El fine-tuning de pix2tex necesita GPU. Los dos notebooks de `entrenamiento/`
están preparados para correr en Colab tal cual, sin subir nada a mano: clonan el
repositorio desde GitHub, instalan las dependencias y generan su propio dataset.

| Notebook | Para qué | Duración aproximada |
|---|---|---|
| [`colab_prueba_humo.ipynb`](https://colab.research.google.com/github/rimyortega55-collab/motor-OCR/blob/main/entrenamiento/colab_prueba_humo.ipynb) | Confirmar que el bucle de entrenamiento corre y guarda un checkpoint. 300 fórmulas, 1 época. No produce un modelo útil. | ~30 min |
| [`colab_finetuning_real.ipynb`](https://colab.research.google.com/github/rimyortega55-collab/motor-OCR/blob/main/entrenamiento/colab_finetuning_real.ipynb) | El fine-tuning de verdad: dataset grande, varias épocas, checkpoints en Google Drive. | horas |

Corre primero la prueba de humo. Ambos notebooks empiezan verificando que hay
GPU asignada y cortan con un mensaje claro si no la hay (**Entorno de ejecución →
Cambiar tipo de entorno de ejecución → GPU**).

El notebook de fine-tuning real guarda los checkpoints y una copia del dataset
en `MyDrive/motor-ocr-finetuning/`, porque el disco local de Colab se borra al
desconectarse. Como Colab desconecta los entornos por tiempo y este
entrenamiento dura horas, el notebook trae una celda de reanudación
(`REANUDAR = True`) que retoma desde el último checkpoint guardado en Drive y
restaura el dataset cacheado en segundos en vez de regenerarlo.

Que el entrenamiento termine no significa que el modelo haya mejorado: hay que
medirlo contra los pesos originales sobre fórmulas que el fine-tuning no vio.

El procedimiento completo —qué modelo es y qué se entrena, cómo bajar el
checkpoint de Drive, cómo compararlo contra los pesos originales y qué falta
todavía para poder afirmar que mejoró— está en
[`docs/ENTRENAMIENTO.md`](docs/ENTRENAMIENTO.md).

## Contribuir

Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) para el entorno de desarrollo, cómo
correr las pruebas y las convenciones del proyecto.

## Licencia

AGPL-3.0-or-later. La dependencia de PyMuPDF (AGPL-3.0) para leer PDF es la
razón por la que el proyecto entero lleva esa licencia.
