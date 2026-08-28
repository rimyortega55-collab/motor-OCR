"""Compara el pix2tex pre-entrenado contra un checkpoint afinado sobre los mismos recortes.

Esto NO mide fidelidad: sin `latex_referencia` anotado a mano no se puede decir
cual de los dos acerto. Lo que mide es *cuanto cambio* el modelo, y deja una
lista concreta de casos para mirar a ojo.

Uso:
    python entrenamiento/comparar_checkpoints.py ruta/al/pix2tex_real_e07_step161.pth
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pix2tex
import torch
from munch import Munch
from PIL import Image
from pix2tex.cli import LatexOCR

BASE_PIX2TEX = Path(pix2tex.__file__).parent
CONFIG = BASE_PIX2TEX / "model" / "settings" / "config.yaml"
PESOS_BASE = BASE_PIX2TEX / "model" / "checkpoints" / "weights.pth"
RECORTES = Path(__file__).parent / "evaluacion_real"


def cargar(checkpoint: Path) -> LatexOCR:
    # Las rutas van absolutas a proposito: LatexOCR corre bajo un decorador
    # in_model_path() que cambia el cwd al directorio del paquete pix2tex, asi
    # que una ruta relativa se resolveria contra ese directorio y no contra este.
    #
    # no_resize=True en AMBOS a proposito: LatexOCR activa un modelo auxiliar de
    # reescalado solo si encuentra un image_resizer.pth junto al checkpoint. El
    # pre-entrenado lo tiene al lado y el bajado de Drive no, asi que sin forzar
    # esto se compararian dos preprocesamientos distintos.
    return LatexOCR(Munch({
        "config": str(CONFIG.resolve()),
        "checkpoint": str(Path(checkpoint).resolve()),
        "no_cuda": not torch.cuda.is_available(),
        "no_resize": True,
    }))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path, help="ruta al .pth afinado bajado de Drive")
    parser.add_argument("--recortes", type=Path, default=RECORTES)
    parser.add_argument("--salida", type=Path, default=Path(__file__).parent / "comparacion.jsonl")
    parser.add_argument("--limite", type=int, default=0, help="0 = todos")
    args = parser.parse_args()

    if not args.checkpoint.exists():
        print(f"No existe el checkpoint: {args.checkpoint}", file=sys.stderr)
        return 1
    if not PESOS_BASE.exists():
        print("Faltan los pesos pre-entrenados. Corre: python -c \"from pix2tex.model.checkpoints.get_latest_checkpoint "
              "import download_checkpoints; download_checkpoints()\"", file=sys.stderr)
        return 1

    pngs = sorted(args.recortes.rglob("*.png"))
    if args.limite:
        pngs = pngs[:args.limite]
    if not pngs:
        print(f"No hay recortes en {args.recortes}", file=sys.stderr)
        return 1

    print(f"{len(pngs)} recortes | dispositivo: {'cuda' if torch.cuda.is_available() else 'cpu'}")
    viejo, nuevo = cargar(PESOS_BASE), cargar(args.checkpoint)

    distintos = 0
    inicio = time.time()
    with args.salida.open("w", encoding="utf-8") as f:
        for i, png in enumerate(pngs, 1):
            with Image.open(png) as imagen:
                imagen.load()
                a, b = viejo(imagen), nuevo(imagen)
            difiere = a != b
            distintos += difiere
            f.write(json.dumps({
                "recorte": str(png.relative_to(args.recortes)).replace("\\", "/"),
                "viejo": a,
                "nuevo": b,
                "difiere": difiere,
                "latex_referencia": "",
            }, ensure_ascii=False) + "\n")
            if i % 10 == 0 or i == len(pngs):
                print(f"  {i}/{len(pngs)}  distintos={distintos}  ({time.time() - inicio:.0f}s)", flush=True)

    pct = 100 * distintos / len(pngs)
    print(f"\n{distintos}/{len(pngs)} recortes donde los dos modelos difieren ({pct:.1f}%)")
    print(f"Detalle en {args.salida}")
    print("Recorda: esto dice cuanto cambio el modelo, no si mejoro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
