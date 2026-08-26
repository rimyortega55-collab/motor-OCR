"""Parches de compatibilidad para poder correr `pix2tex.train`/`pix2tex.eval` en este entorno.

`torchtext` (usado por pix2tex solo para `torchtext.data.metrics.bleu_score`)
dejó de mantenerse y su extensión nativa (`libtorchtext.pyd`) no es compatible
en binario con versiones recientes de `torch` (falla con
"OSError: Could not load this library"). En vez de fijar una versión antigua
de `torch`/`torchtext` -lo que rompería el resto del proyecto-, se registra un
stub de `torchtext.data.metrics.bleu_score` en `sys.modules` antes de que
`pix2tex.eval` intente importarlo.
"""
from __future__ import annotations

import math
import sys
import types
from collections import Counter


def _ngramas(tokens: list, n: int) -> list[tuple]:
    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def bleu_score(candidate_corpus, references_corpus, max_n: int = 4,
                weights=(0.25, 0.25, 0.25, 0.25)) -> float:
    """Reimplementacion minima de `torchtext.data.metrics.bleu_score` (BLEU corpus-level)."""
    coincidencias = [0] * max_n
    totales = [0] * max_n
    len_candidato, len_referencia = 0, 0

    for candidato, referencias in zip(candidate_corpus, references_corpus):
        len_candidato += len(candidato)
        if referencias:
            len_referencia += min(len(r) for r in referencias)
        for n in range(1, max_n + 1):
            cand_ngramas = Counter(_ngramas(candidato, n))
            max_ref_ngramas: Counter = Counter()
            for referencia in referencias:
                ref_ngramas = Counter(_ngramas(referencia, n))
                for ng, c in ref_ngramas.items():
                    max_ref_ngramas[ng] = max(max_ref_ngramas[ng], c)
            coincidencias[n - 1] += sum(min(c, max_ref_ngramas.get(ng, 0)) for ng, c in cand_ngramas.items())
            totales[n - 1] += max(0, len(candidato) - n + 1)

    if len_candidato == 0 or any(t == 0 for t in totales):
        return 0.0
    precisiones = [coincidencias[n] / totales[n] for n in range(max_n)]
    if min(precisiones) == 0:
        return 0.0
    log_precision = sum(w * math.log(p) for w, p in zip(weights, precisiones))
    penalizacion_brevedad = 1.0 if len_candidato > len_referencia else math.exp(1 - len_referencia / len_candidato)
    return penalizacion_brevedad * math.exp(log_precision)


def instalar_stub_torchtext() -> None:
    """Registra un `torchtext` falso en sys.modules si el real no se puede cargar."""
    if "torchtext" in sys.modules:
        return
    try:
        import torchtext  # noqa: F401
        return  # el real funciona, no hace falta el stub
    except Exception:
        pass

    modulo_metrics = types.ModuleType("torchtext.data.metrics")
    modulo_metrics.bleu_score = bleu_score
    modulo_data = types.ModuleType("torchtext.data")
    modulo_data.metrics = modulo_metrics
    modulo_torchtext = types.ModuleType("torchtext")
    modulo_torchtext.data = modulo_data

    sys.modules["torchtext"] = modulo_torchtext
    sys.modules["torchtext.data"] = modulo_data
    sys.modules["torchtext.data.metrics"] = modulo_metrics
