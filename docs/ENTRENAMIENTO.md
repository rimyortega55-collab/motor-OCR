# Entrenamiento del modelo matemático

Cómo se hace el fine-tuning del reconocedor de fórmulas, cómo se baja el modelo
resultante y cómo se comprueba si sirve para algo.

## Contexto: qué se entrena y qué no

El pipeline de motor-OCR es determinista en sus capas 1 a 4. PyMuPDF extrae la
prosa exacta y gratis, y en el corpus de prueba la matemática es apenas el
0,5%–6,7% de los caracteres. El modelo de IA no reemplaza nada de eso: sólo
recibe los recortes que el motor ya localizó y clasificó como
`formula_display` / `formula_inline`, y devuelve LaTeX.

El modelo es **pix2tex / LaTeX-OCR** de Lukas Blecher (licencia MIT), el mismo
que ya se usa como motor determinista en
[`pix2tex_engine.py`](../packages/motor_ocr/reconocimiento/engines/pix2tex_engine.py).
No se entrena desde cero: se parte de sus pesos pre-entrenados y se les hace
fine-tuning.

| | |
|---|---|
| Encoder | ViT híbrido: backbone ResNetV2 `[2,3,7]` + 4 capas de transformer, `dim` 256, 8 cabezas |
| Decoder | Transformer autorregresivo (`x-transformers`), 4 capas, 8000 tokens de vocabulario |
| Entrada | Imagen en escala de grises, hasta 192×672 px |
| Salida | Hasta 512 tokens de LaTeX |
| Tamaño | 25,5 M de parámetros (12,9 M encoder / 12,6 M decoder), 97 MB en disco |

Es un modelo chico a propósito: entra cómodo en una T4 del tier gratis de Colab.

### Qué cambia y qué se mantiene fijo

Los hiperparámetros de **arquitectura no se tocan**. Están fijados en
[`config_validacion.yaml`](../entrenamiento/config_validacion.yaml) y coinciden
clave por clave con los del `settings/config.yaml` que trae el paquete pix2tex.
Eso no es una coincidencia decorativa: si cambiaran, los pesos pre-entrenados no
cargarían, y el fine-tuning arrancaría de ruido.

Por la misma razón se reusa **el tokenizer del checkpoint pre-entrenado** en vez
de generar uno nuevo. Con un vocabulario distinto los embeddings pre-entrenados
no significarían nada.

Lo que sí cambia en el fine-tuning: el dataset, las épocas, el batch y el
learning rate. Este último baja a `1e-4` (contra el `1e-3` de la prueba de humo)
justamente porque se parte de pesos ya entrenados y no conviene destruirlos.

### De dónde salen los datos

De [`generar_dataset_sintetico.py`](../entrenamiento/generar_dataset_sintetico.py):
genera fórmulas LaTeX aleatorias, las renderiza con `pdflatex`, rasteriza el PDF
con PyMuPDF y recorta al bounding box real de la tinta.

**Esto es una limitación real, no un detalle.** El dataset es 100% sintético: no
tiene ruido de escaneo ni de fotografía, ni la tipografía concreta de tus PDF.
Una mejora medida sobre datos sintéticos no garantiza una mejora sobre tu corpus.
Ver [Lo que falta](#lo-que-falta) más abajo.

## Procedimiento: entrenar en Colab

Hacen falta dos notebooks, en este orden. Los dos clonan el repositorio desde
GitHub, así que **lo que corre en Colab es lo que esté en `origin/main`**: si
tocaste algo en local, pushealo antes.

### 1. Prueba de humo (~30 min, una sola vez)

[`entrenamiento/colab_prueba_humo.ipynb`](../entrenamiento/colab_prueba_humo.ipynb)
→ [abrir en Colab](https://colab.research.google.com/github/rimyortega55-collab/motor-OCR/blob/main/entrenamiento/colab_prueba_humo.ipynb)

300 fórmulas, 1 época. El checkpoint que produce es descartable: lo único que
confirma es que el entorno funciona de punta a punta —GPU asignada, `pdflatex`
instalado, empaquetado del dataset, bucle de pix2tex, guardado del `.pth`—. Si
algo del entorno está roto conviene enterarse acá y no tres horas adentro del
entrenamiento real.

### 2. Fine-tuning real (horas)

[`entrenamiento/colab_finetuning_real.ipynb`](../entrenamiento/colab_finetuning_real.ipynb)
→ [abrir en Colab](https://colab.research.google.com/github/rimyortega55-collab/motor-OCR/blob/main/entrenamiento/colab_finetuning_real.ipynb)

Por defecto 3000 fórmulas de entrenamiento, 300 de validación, 20 épocas. Los
parámetros están en la celda 5 y son un punto de partida razonable, no valores
probados como óptimos. Si Colab se queda sin memoria de GPU, bajá
`BATCHSIZE`/`MICRO_BATCHSIZE` antes que ninguna otra cosa.

Antes de empezar: **Entorno de ejecución → Cambiar tipo de entorno de ejecución →
GPU**. Los notebooks lo verifican en su primera celda y cortan con un mensaje
claro si falta.

### Qué se guarda dónde

El disco de la VM de Colab se borra al desconectarse. Por eso:

| Archivo | Dónde queda | Por qué |
|---|---|---|
| Checkpoints del fine-tuning | Drive, `MyDrive/motor-ocr-finetuning/checkpoints_real/pix2tex_real/` | Es el resultado; sin esto perdés horas de GPU |
| Dataset sintético | Drive, `MyDrive/motor-ocr-finetuning/dataset_real.tar` | Regenerarlo con `pdflatex` tarda muchísimo |
| Salidas de evaluación | Drive, `MyDrive/motor-ocr-finetuning/outputs_real/` | — |
| Pesos pre-entrenados (`weights.pth`) | Disco local de Colab | Se rebajan solos desde GitHub en ~1 min |

Los pesos base **no** van a Drive. `download_checkpoints()` los escribe dentro
del paquete pix2tex instalado en la VM, y se rebajan en cada sesión nueva. Es
automático y no vale la pena cachearlos.

El dataset se cachea como **un solo `.tar`** y no como miles de PNG sueltos
porque escribir muchos archivos chicos en Drive es lentísimo, mientras que un
archivo grande no.

### Cuando Colab te desconecte

Va a pasar: Colab corta los entornos por tiempo y esto dura horas. Para
continuar:

1. Volvé a abrir el notebook y corré todo desde el principio. El dataset se
   restaura del `.tar` de Drive en segundos en vez de regenerarse.
2. En la celda **8.b**, poné `REANUDAR = True` antes de entrenar.

Esa celda busca el último `.pth` en Drive, lo pone en `load_chkpt` y fija
`epoch`, que es donde pix2tex arranca su bucle (`for e in range(args.epoch,
args.epochs)`).

Un detalle que conviene saber: **pix2tex sólo guarda los pesos, no el estado del
optimizador**. Al reanudar, Adam y el scheduler arrancan de cero. Con un learning
rate bajo la diferencia es menor, pero no es una reanudación perfecta.

## Bajar el modelo entrenado

Los checkpoints quedan en tu Drive, no hace falta nada especial: entrás a
`MyDrive/motor-ocr-finetuning/checkpoints_real/pix2tex_real/` y los bajás desde
el navegador. Se llaman `pix2tex_real_e{época}_step{paso}.pth` y pesan ~97 MB
cada uno.

Cuál elegir: pix2tex guarda por dos motivos distintos. Guarda **cada `save_freq`
épocas** (checkpoint periódico) y también **cada vez que mejora a la vez el BLEU
y la precisión por token** en validación. El último por fecha de modificación es
el que la celda de reanudación usa; para evaluar suele interesar el de mejor
métrica, no el más reciente.

Si preferís bajarlo por línea de comandos en vez del navegador, cualquier cliente
de Drive sirve; no hay nada específico del proyecto en ese paso.

## Cómo lo probamos

Acá hay que ser directo: **hoy no hay forma de medir si el fine-tuning mejoró la
fidelidad**, porque no hay ground truth anotado. Lo que sí se puede hacer hoy, y
lo que falta, van separados.

### Lo que se puede hacer hoy: comparar los dos checkpoints entre sí

Se corre el modelo viejo y el nuevo sobre los mismos recortes de fórmulas reales
y se mira dónde difieren. Eso no dice cuál acertó —para eso hace falta la
referencia—, pero sí dice **cuánto cambió el modelo** y te da una lista corta de
casos concretos para mirar a ojo.

Los recortes ya existen: `entrenamiento/extraer_muestra_evaluacion.py` corre el
pipeline sobre los PDF de `pruebas/pdfs_de_prueba/`, recorta cada bloque
matemático a 300 DPI y escribe un `manifiesto.jsonl` con la predicción actual y
un campo `latex_referencia` vacío para completar a mano.

Un script de comparación mínimo:

```python
from pathlib import Path

import pix2tex
import torch
from munch import Munch
from PIL import Image
from pix2tex.cli import LatexOCR

BASE_PIX2TEX = Path(pix2tex.__file__).parent
CONFIG = BASE_PIX2TEX / "model" / "settings" / "config.yaml"


def cargar(checkpoint: Path) -> LatexOCR:
    # Las rutas van absolutas a proposito: LatexOCR corre bajo un decorador
    # in_model_path() que cambia el cwd al directorio del paquete pix2tex, asi
    # que una ruta relativa se resolveria contra ese directorio y no contra el tuyo.
    return LatexOCR(Munch({
        "config": str(CONFIG.resolve()),
        "checkpoint": str(Path(checkpoint).resolve()),
        "no_cuda": not torch.cuda.is_available(),
        "no_resize": True,   # ver la nota de abajo: NO lo cambies para una sola de las dos
    }))


viejo = cargar(BASE_PIX2TEX / "model" / "checkpoints" / "weights.pth")
nuevo = cargar("pix2tex_real_e20_step300.pth")  # el que bajaste de Drive

recortes = sorted(Path("entrenamiento/evaluacion_real").rglob("*.png"))
distintos = 0
for png in recortes:
    imagen = Image.open(png)
    a, b = viejo(imagen), nuevo(imagen)
    if a != b:
        distintos += 1
        print(f"\n{png}\n  viejo: {a}\n  nuevo: {b}")

print(f"\n{distintos}/{len(recortes)} recortes donde los dos modelos difieren")
```

Dos trampas al comparar, las dos importantes:

- **`config.yaml` tiene que ser el mismo para los dos.** El fine-tuning no cambia
  la arquitectura, así que el `settings/config.yaml` del paquete construye
  correctamente tanto el modelo base como el afinado. Verificado: las 15 claves
  de arquitectura coinciden entre ese archivo y `config_validacion.yaml`.
- **`no_resize` tiene que ser igual para los dos.** `LatexOCR` activa un modelo
  auxiliar de reescalado sólo si encuentra un `image_resizer.pth` *en la misma
  carpeta que el checkpoint*. Tu `.pth` bajado de Drive está solo en su carpeta,
  el pre-entrenado no: si no forzás `no_resize=True` en ambos, estarías
  comparando dos preprocesamientos distintos y atribuyendo la diferencia al
  fine-tuning.

### Probarlo en el motor completo

Comparar recortes sueltos no dice cómo queda el documento entero. Para eso el
checkpoint se puede enchufar al pipeline sin tocar código y sin reiniciar el
proceso:

1. Copiá el `.pth` que bajaste de Drive a `entrenamiento/checkpoints/` (o a
   donde apunte `MOTOR_OCR_CHECKPOINTS_DIR`, si preferís otro directorio).
2. Levantá la API, entrá al panel: **Administración → Modelo matemático (Capa 3,
   fórmulas)**, elegí el archivo en la lista y dale a *Aplicar*.
3. Subí un PDF con fórmulas y mirá el resultado en Documentos/Revisión.

La elección se guarda en base (`configuracion_modelo_matematico`) y se vuelve a
aplicar al arrancar, así que sobrevive a un reinicio. Si el `.pth` elegido
desaparece del disco, el arranque no falla: avisa por consola, sigue con los
pesos pre-entrenados, y el panel muestra que lo guardado y lo que corre no
coinciden.

Rige para lo que se suba a partir de ahí: un documento que ya está a mitad del
pipeline termina con el modelo que tenía cargado.

Dos cosas que esto **no** es. No es una medición: sirve para mirar a ojo, y sin
`latex_referencia` sigue sin haber con qué comparar. Y el preprocesamiento no es
idéntico entre las dos opciones —con checkpoint propio se fuerza `no_resize=True`
por el motivo del `image_resizer.pth` explicado más arriba, mientras que los
pesos base corren con el reescalado que trae el paquete—, así que una diferencia
en el documento no es atribuible al fine-tuning sin más.

### Lo que NO mide el arnés existente

`pruebas/arnes_evaluacion.py` **no sirve para esto**. Su propio docstring lo
aclara: mide robustez estructural (que el pipeline no explote, que el `.tex`
compile, qué motor resolvió cada bloque), no fidelidad textual, precisamente
porque no hay ground truth. Un fine-tuning puede empeorar todas las fórmulas y
el arnés seguiría dando verde.

Además `pruebas/` está en `.gitignore`, así que no llega al clon de Colab: esa
evaluación se corre en local con el `.pth` ya bajado.

## Lo que falta

Tres huecos concretos entre "el entrenamiento terminó" y "el motor mejoró".

**1. No hay ground truth.** `entrenamiento/evaluacion_real/` tiene hoy 237
recortes, pero de sólo 4 de los 11 PDF (c1 tiene 1 solo) y sin el
`manifiesto.jsonl` que los acompaña. Hasta que alguien complete a mano el campo
`latex_referencia`, no se puede decir "el modelo mejoró", sólo "el modelo
cambió". Es trabajo manual y no hay atajo.

**2. ~~El pipeline no puede usar el checkpoint afinado.~~ Resuelto** — ver
[Probarlo en el motor completo](#probarlo-en-el-motor-completo). Lo que sigue
faltando es el punto 1: que el motor lo use no dice si acierta más.

**3. El dataset no se parece a los datos reales.** Es sintético: `pdflatex` sobre
fondo limpio. Falta ruido de escaneo, compresión JPEG, inclinación, y sobre todo
la tipografía real de los PDF del corpus. Si la mejora medida no se sostiene
sobre fórmulas reales, el paso siguiente no es entrenar más épocas sino conseguir
un dataset más realista.

Mientras tanto vale la prioridad declarada del proyecto: **LaTeX primero**, hasta
que cumpla su criterio de calidad; recién después Markdown.
