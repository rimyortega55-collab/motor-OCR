# Arquitectura

`motor-OCR` convierte PDF académico (con o sin fórmulas) a LaTeX y Markdown
mediante un pipeline de 7 capas. Las primeras cuatro son 100% deterministas;
sólo la quinta llama a un LLM, y únicamente para lo que el resto del pipeline
no resolvió con confianza suficiente.

```
1. Triage              → packages/motor_ocr/triage
2. Segmentación         → packages/motor_ocr/layout
3. OCR especializado    → packages/motor_ocr/reconocimiento
4. Corrección           → packages/motor_ocr/correccion
5. Escalación a LLM     → packages/motor_ocr/escalacion
6. Revisión humana      → packages/motor_ocr_api/revision
7. Interfaz web         → packages/motor_ocr_api + frontend/
```

El orquestador de las capas 1-5 es
[`Pipeline`](../packages/motor_ocr/pipeline.py), que las ejecuta como pasos
secuenciales explícitos (no como agente ni como grafo de estados): cada capa
se prueba aislada y el orden es siempre el mismo, sin ramas condicionales que
por ahora ameriten una máquina de estados.

## 1. Triage

Clasifica cada página del PDF antes de procesarla: si el texto viene nativo
o es una imagen escaneada, el perfil visual de la página y el DPI efectivo.
Esa clasificación decide qué camino sigue la página en las capas siguientes.

## 2. Segmentación

Divide cada página en bloques semánticos (párrafo, fórmula, tabla, figura,
encabezado, pie de página, etc.) y determina el orden de lectura. Un PDF
nativo-digital se segmenta a partir de su capa de texto; uno escaneado, a
partir del layout visual.

## 3. OCR especializado

Enruta cada bloque al motor que mejor lo resuelve:

- **PyMuPDF** para texto nativo-digital (exacto y gratis, sin OCR).
- **pix2tex** para fórmulas matemáticas (imagen recortada → LaTeX).
- **EasyOCR** / **docTR** para texto escaneado.
- **Tesseract** como motor de respaldo cuando los anteriores no aplican.

Cada resultado lleva un puntaje de confianza que las capas siguientes usan
para decidir si hace falta escalar.

### Modo de reconocimiento: híbrido o sólo modelo de IA

El enrutamiento de arriba es el modo **híbrido**, que es el default y el que
conviene para procesar de verdad: el motor determinista resuelve todo lo que
puede -la prosa nativa sale exacta y gratis de PyMuPDF- y el modelo de IA sólo
ve los recortes que ya fueron localizados como fórmula.

El modo **sólo modelo de IA** (`solo_ia`) desactiva todos esos atajos: cada
bloque que no sea ruido ni figura se recorta de la página renderizada y se
manda entero al modelo, incluido el texto que el PDF ya traía escrito y lo que
docTR transcribió en la Capa 2. Existe por dos razones: poder medir al modelo
solo -sin que el motor determinista le tape los errores, que es lo que hace
falta para evaluar un fine-tuning- y procesar PDFs cuya capa de texto está
rota. Es bastante más lento y más frágil, porque el modelo está afinado para
fórmulas y no para párrafos.

El modo se elige **por documento** al subirlo (campo `modo_motor` de
`POST /api/procesar`, o el selector de la pantalla de subida) y queda guardado
en la fila del documento: sin eso, dos documentos de la misma instancia con
calidades muy distintas no se podrían explicar. Sólo gobierna la Capa 3 — las
capas 1, 2, 4 y 5 corren igual en los dos modos.

## 4. Corrección determinista

Normalización de LaTeX, reparación estructural (párrafos partidos por saltos
de página, guiones de corte, folios corrientes mezclados con el texto) y
verificación ortográfica, todo con reglas explícitas — sin LLM.

## 5. Escalación a LLM

Los bloques que llegan con confianza por debajo del umbral configurado se
agrupan en lotes y se resuelven con un LLM, con tracking de costo y límites
de tasa. Es la única capa no determinista del pipeline, y por diseño debería
tocar la menor cantidad de contenido posible: en el corpus de prueba, la
matemática (lo único que suele necesitar esta capa) es apenas 0,5%–6,7% de
los caracteres de un documento típico.

## 6. Revisión humana

Los bloques que ni la capa 4 ni la 5 resuelven con confianza suficiente
quedan en una cola de revisión. Las decisiones tomadas ahí alimentan el
auto-ajuste de umbrales de la capa 7.

## 7. Interfaz web

`motor_ocr_api` (FastAPI) expone el pipeline como servicio: sin cuentas —una
clave única opcional protege la instancia entera—, subida de documentos, cola
de revisión, traducción y administración (incluida la rotación de esa clave).
El frontend en `frontend/` (React + TypeScript) es la interfaz para usuarios que
no programan. `app_streamlit.py` es una interfaz alternativa más simple,
pensada para correr el pipeline localmente sin levantar el frontend completo.

## Hacia dónde va el reconocimiento matemático

El plan de mediano plazo no es reemplazar el pipeline determinista por un
modelo de visión-lenguaje de extremo a extremo, sino hacerle fine-tuning a un
modelo open source ya entrenado para mejorar específicamente el paso 3 en
fórmulas complejas. El candidato natural es
[pix2tex/LaTeX-OCR](https://github.com/lukas-blecher/LaTeX-OCR), que ya está
integrado como motor determinista en
[`pix2tex_engine.py`](../packages/motor_ocr/reconocimiento/engines/pix2tex_engine.py).
Los scripts de entrenamiento y evaluación viven en [`entrenamiento/`](../entrenamiento/),
y el procedimiento completo está en [`ENTRENAMIENTO.md`](ENTRENAMIENTO.md).

El motor se refina un formato a la vez: primero LaTeX, después Markdown.

## Referencia de la API

La API no tiene un documento de contrato estático: FastAPI genera la
documentación interactiva automáticamente. Con el servidor corriendo
(`uvicorn motor_ocr_api.api:app --reload`), está disponible en
`http://localhost:8000/docs` (Swagger UI) y `http://localhost:8000/redoc`.
