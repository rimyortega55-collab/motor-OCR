"""Genera un dataset sintético de pares (imagen, LaTeX) para el fine-tuning de pix2tex.

Renderiza fórmulas LaTeX generadas aleatoriamente (ver `generador_formulas.py`)
con `pdflatex` y rasteriza el PDF resultante con PyMuPDF, sin depender de
ImageMagick. La salida queda en el formato que espera
`pix2tex.dataset.dataset.Im2LatexDataset`: por cada split, una carpeta
`imagenes/` con archivos `{indice:07d}.png` y un archivo `formulas.txt` con
una fórmula por línea, alineado por índice con el nombre de archivo.

Requiere una distribución LaTeX con `pdflatex` en el PATH (MiKTeX o TeX Live).

Uso:
    python entrenamiento/generar_dataset_sintetico.py --n-train 4000 --n-val 400
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
from generador_formulas import generar_corpus

PLANTILLA_TEX = r"""\documentclass[preview,border=2pt]{{standalone}}
\usepackage{{amsmath,amssymb,bm}}
\begin{{document}}
$$ {formula} $$
\end{{document}}
"""


def _renderizar_formula(indice: int, formula: str, dir_imagenes: Path, dpi: int, dir_tmp_base: Path) -> tuple[int, bool]:
    # Se usa un directorio temporal propio (no el temp del sistema): en Windows
    # el temp del sistema puede resolver a una ruta corta 8.3 con "~" (p. ej.
    # RIMYAL~1), y pdflatex interpreta el "~" como caracter activo de LaTeX y
    # trunca el nombre de archivo, fallando con "I can't find file".
    with tempfile.TemporaryDirectory(prefix="formula_", dir=str(dir_tmp_base)) as tmp:
        tmp_path = Path(tmp)
        tex_path = tmp_path / "f.tex"
        tex_path.write_text(PLANTILLA_TEX.format(formula=formula), encoding="utf-8")
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "-output-directory", str(tmp_path), str(tex_path)],
                capture_output=True, timeout=20, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return indice, False

        pdf_path = tmp_path / "f.pdf"
        if not pdf_path.exists():
            return indice, False
        try:
            doc = pymupdf.open(str(pdf_path))
            pix = doc[0].get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            doc.close()

            # El recorte de `standalone` deja de margen mucho mas espacio del
            # que ocupa la tinta (medido: formulas cortas quedaban con ~80%
            # de blanco). Se recorta al bounding box real de la tinta con un
            # margen fijo, igual que hace el propio pipeline de datos de pix2tex.
            imagen = Image.open(io.BytesIO(png_bytes)).convert("L")
            bbox = ImageOps.invert(imagen).getbbox()
            if bbox is None:
                return indice, False
            margen = 8
            x0, y0, x1, y1 = bbox
            x0, y0 = max(0, x0 - margen), max(0, y0 - margen)
            x1, y1 = min(imagen.width, x1 + margen), min(imagen.height, y1 + margen)
            recorte = imagen.crop((x0, y0, x1, y1))

            # El encoder hibrido de pix2tex indexa su tabla de posiciones
            # asumiendo que el ancho/alto son multiplos de 32 (es lo que hace
            # su propio `dataset/render.py` con el parametro `divable`); sin
            # este padding, formulas de tamano "impar" hacen que el numero de
            # parches que calcula el backbone no coincida con el esperado y
            # el entrenamiento falla con un error de forma en `pos_embed`.
            divisor = 32
            w, h = recorte.size
            w_pad = -(-w // divisor) * divisor
            h_pad = -(-h // divisor) * divisor
            lienzo = Image.new("L", (w_pad, h_pad), 255)
            lienzo.paste(recorte, (0, 0))
            lienzo.save(str(dir_imagenes / f"{indice:07d}.png"))
        except Exception:
            return indice, False
    return indice, True


def generar_split(nombre: str, formulas: list[str], directorio_base: Path,
                   dpi_min: int, dpi_max: int, workers: int, seed: int) -> None:
    dir_split = directorio_base / nombre
    dir_imagenes = dir_split / "imagenes"
    dir_imagenes.mkdir(parents=True, exist_ok=True)
    dir_tmp_base = dir_split / "_tmp_render"
    dir_tmp_base.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    exitos = [False] * len(formulas)
    total = len(formulas)
    pendientes = list(range(total))

    try:
        # MiKTeX bajo Windows tiene contencion real al correr muchos pdflatex
        # en paralelo (bloqueo de su base de archivos), asi que una fraccion de
        # formulas perfectamente validas falla en la primera pasada. Se
        # reintenta lo que falle con cada vez menos paralelismo hasta agotarlo.
        intentos_workers = [workers, max(1, workers // 2), 1]
        for intento, n_workers in enumerate(intentos_workers):
            if not pendientes:
                break
            with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
                futuros = {
                    pool.submit(_renderizar_formula, i, formulas[i], dir_imagenes,
                                rng.randint(dpi_min, dpi_max), dir_tmp_base): i
                    for i in pendientes
                }
                completados = 0
                for futuro in concurrent.futures.as_completed(futuros):
                    indice, ok = futuro.result()
                    exitos[indice] = ok
                    completados += 1
                    if completados % 100 == 0 or completados == len(pendientes):
                        print(f"  [{nombre}] intento {intento + 1}: {completados}/{len(pendientes)}")
            pendientes = [i for i in pendientes if not exitos[i]]
    finally:
        shutil.rmtree(dir_tmp_base, ignore_errors=True)

    fallidos = total - sum(exitos)

    with open(dir_split / "formulas.txt", "w", encoding="utf-8") as fh:
        for i, formula in enumerate(formulas):
            fh.write(formula if exitos[i] else "")
            fh.write("\n")

    print(f"[{nombre}] listo: {total - fallidos}/{total} fórmulas renderizadas -> {dir_split}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n-train", type=int, default=4000)
    parser.add_argument("--n-val", type=int, default=400)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "dataset_sintetico")
    parser.add_argument("--profundidad-max", type=int, default=3)
    parser.add_argument("--dpi-min", type=int, default=100)
    parser.add_argument("--dpi-max", type=int, default=200)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if shutil.which("pdflatex") is None:
        sys.exit("No se encontró 'pdflatex' en el PATH. Instala una distribución LaTeX (MiKTeX o TeX Live).")

    total = args.n_train + args.n_val
    print(f"Generando {total} fórmulas únicas (seed={args.seed})...")
    formulas = generar_corpus(total, seed=args.seed, profundidad_max=args.profundidad_max)
    if len(formulas) < total:
        print(f"Aviso: solo se generaron {len(formulas)} fórmulas únicas de las {total} pedidas.")

    train = formulas[:args.n_train]
    val = formulas[args.n_train:args.n_train + args.n_val]

    args.out.mkdir(parents=True, exist_ok=True)
    generar_split("train", train, args.out, args.dpi_min, args.dpi_max, args.workers, args.seed)
    generar_split("val", val, args.out, args.dpi_min, args.dpi_max, args.workers, args.seed + 1)


if __name__ == "__main__":
    main()
