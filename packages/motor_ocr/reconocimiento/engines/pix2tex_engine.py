"""Wrapper de pix2tex (LaTeX-OCR) — reconocimiento de fórmulas a LaTeX.

Se usa tanto para bloques `formula_display` completos (directo, sin
sub-segmentar) como para micro-segmentos `formula_inline` dentro de bloques
de texto, y para celdas de tabla con notación matemática.

## Checkpoint afinado

El motor puede correr con los pesos pre-entrenados que trae el paquete pix2tex
(lo de siempre) o con un `.pth` salido del fine-tuning propio
(`docs/ENTRENAMIENTO.md`). Cuál de los dos se usa se elige en caliente con
`configurar_checkpoint`, y el panel de administración lo expone para poder
probar un checkpoint recién bajado de Drive sin editar código ni reiniciar el
proceso.

Los checkpoints se buscan **sólo** dentro de `MOTOR_OCR_CHECKPOINTS_DIR`
(por defecto `entrenamiento/checkpoints/`): la selección viaja como nombre de
archivo, no como ruta, para que un pedido HTTP no pueda hacer que el proceso
cargue un `.pth` arbitrario del disco.

Dos detalles heredados de `entrenamiento/comparar_checkpoints.py`, por los
mismos motivos que ahí:

- La ruta del checkpoint y la del `config.yaml` van **absolutas**: `LatexOCR`
  corre bajo un decorador `in_model_path()` que cambia el cwd al directorio del
  paquete pix2tex, así que una ruta relativa se resolvería contra ese
  directorio.
- Con checkpoint propio se fuerza `no_resize=True`. `LatexOCR` activa un modelo
  auxiliar de reescalado sólo si encuentra un `image_resizer.pth` *junto al
  checkpoint*; un `.pth` bajado de Drive está solo en su carpeta. Sin forzarlo,
  el preprocesamiento dependería de si el archivo tiene o no un vecino, que es
  la peor forma de que dos corridas difieran.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Dónde se buscan los `.pth` afinados. Un solo directorio, y nada fuera de él.
DIRECTORIO_CHECKPOINTS = Path(
    os.environ.get("MOTOR_OCR_CHECKPOINTS_DIR", "entrenamiento/checkpoints")
)

_model = None
# None = pesos pre-entrenados de pix2tex. Si no, nombre de archivo dentro de
# DIRECTORIO_CHECKPOINTS.
_checkpoint: str | None = os.environ.get("MOTOR_OCR_PIX2TEX_CHECKPOINT") or None

# El pipeline corre varios documentos en hilos a la vez (`trabajos.py`): sin
# esto, dos hilos que entran juntos al lazy loader construirían dos modelos, y
# un cambio de checkpoint a mitad de camino dejaría uno de los dos vivo.
_bloqueo = threading.Lock()


def checkpoint_actual() -> str | None:
    """Nombre del `.pth` afinado en uso, o None si corre con los pesos base."""
    return _checkpoint


def checkpoints_disponibles() -> list[dict]:
    """Los `.pth` que hay hoy en el directorio de checkpoints, más nuevos primero."""
    if not DIRECTORIO_CHECKPOINTS.is_dir():
        return []

    archivos = [p for p in DIRECTORIO_CHECKPOINTS.glob("*.pth") if p.is_file()]
    archivos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "nombre": p.name,
            "bytes": p.stat().st_size,
            "modificado_en": p.stat().st_mtime,
        }
        for p in archivos
    ]


def resolver_checkpoint(nombre: str) -> Path:
    """Ruta absoluta del checkpoint `nombre`, verificando que no salga del directorio.

    Levanta ValueError si el nombre apunta afuera (`..`, ruta absoluta) o si el
    archivo no existe: es la validación de un dato que llega por HTTP.
    """
    directorio = DIRECTORIO_CHECKPOINTS.resolve()
    ruta = (directorio / nombre).resolve()

    if ruta.parent != directorio:
        raise ValueError(f"checkpoint fuera de {DIRECTORIO_CHECKPOINTS}: {nombre}")
    if not ruta.is_file():
        raise ValueError(f"no existe el checkpoint: {nombre}")

    return ruta


def configurar_checkpoint(nombre: str | None) -> None:
    """Cambia el checkpoint en caliente. None vuelve a los pesos pre-entrenados.

    Descarta el modelo cargado; el siguiente bloque que llegue lo reconstruye.
    Lo que ya está a mitad de un documento sigue con el modelo que tenía en la
    mano, igual que el cambio de paralelismo del panel.
    """
    global _model, _checkpoint

    if nombre is not None:
        resolver_checkpoint(nombre)  # valida antes de aceptar

    with _bloqueo:
        _checkpoint = nombre
        _model = None


def _construir_modelo():
    from pix2tex.cli import LatexOCR

    if _checkpoint is None:
        # Sin checkpoint propio: exactamente lo de siempre, incluido el
        # image_resizer que el paquete trae al lado de sus pesos.
        return LatexOCR()

    import pix2tex
    import torch
    from munch import Munch

    config = Path(pix2tex.__file__).parent / "model" / "settings" / "config.yaml"
    return LatexOCR(
        Munch(
            {
                "config": str(config.resolve()),
                "checkpoint": str(resolver_checkpoint(_checkpoint)),
                "no_cuda": not torch.cuda.is_available(),
                "no_resize": True,
            }
        )
    )


def _get_model():
    """Lazy loader para pix2tex model (costoso de inicializar)."""
    global _model
    if _model is not None:
        return _model

    with _bloqueo:
        if _model is None:
            try:
                _model = _construir_modelo()
            except ImportError:
                print("[pix2tex] No instalado, fallback a tesseract")
                return None
        return _model

def ocr_formula(imagen_recorte) -> tuple[str, float]:
    """Devuelve (latex_reconocido, confianza_engine).

    Args:
        imagen_recorte: numpy array (H, W) o (H, W, 3)

    Returns:
        (latex_formula, confidence)
    """
    if imagen_recorte is None or imagen_recorte.size == 0:
        return "", 0.0

    try:
        model = _get_model()
        if model is None:
            return "", 0.0

        # Ensure image is uint8
        if imagen_recorte.dtype != np.uint8:
            if imagen_recorte.max() <= 1.0:
                imagen_recorte = (imagen_recorte * 255).astype(np.uint8)
            else:
                imagen_recorte = imagen_recorte.astype(np.uint8)

        # Convert to RGB if grayscale
        if len(imagen_recorte.shape) == 2:
            imagen_recorte = cv2.cvtColor(imagen_recorte, cv2.COLOR_GRAY2RGB)
        elif len(imagen_recorte.shape) == 3 and imagen_recorte.shape[2] == 4:
            imagen_recorte = cv2.cvtColor(imagen_recorte, cv2.COLOR_BGRA2RGB)

        # pix2tex (LatexOCR) espera una PIL.Image, no un numpy array
        pil_image = Image.fromarray(imagen_recorte)
        latex = model(pil_image)

        # pix2tex no proporciona confidence scores nativas
        # Usamos heurística: largura vs complejidad
        if latex:
            # Confianza inversamente correlada con longitud (fórmulas cortas = más confiables)
            confianza = max(0.7, min(0.95, 0.95 - len(latex) * 0.001))
        else:
            confianza = 0.0

        return str(latex).strip(), float(confianza)

    except Exception as e:
        print(f"[pix2tex] Error: {e}")
        return "", 0.0
