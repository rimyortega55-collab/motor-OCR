"""Lanzador de `pix2tex.train` que aplica los parches de `_compat.py` antes de importarlo.

Uso (identico a `python -m pix2tex.train`, mismos argumentos):
    python entrenamiento/entrenar.py --config entrenamiento/config_validacion.yaml --no_cuda
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _compat import instalar_stub_torchtext  # noqa: E402

instalar_stub_torchtext()

if __name__ == "__main__":
    # alter_sys=True es imprescindible: pix2tex guarda sus datasets con pickle
    # mientras corre como "python -m pix2tex.dataset.dataset" (`__main__`), y
    # el unpickler busca la clase `Im2LatexDataset` en `sys.modules['__main__']`.
    # Sin alter_sys, runpy ejecuta pix2tex.train en un namespace temporal sin
    # reemplazar sys.modules['__main__'], y la carga del dataset falla con
    # "Can't get attribute 'Im2LatexDataset' on <module '__main__'>".
    runpy.run_module("pix2tex.train", run_name="__main__", alter_sys=True)
