"""Generador aleatorio de expresiones LaTeX matemáticas.

Produce fórmulas sintéticas variadas (fracciones, potencias, sumatorias,
integrales, límites, matrices, funciones trigonométricas/logarítmicas...)
para alimentar el renderizador de datasets en `generar_dataset_sintetico.py`.
No busca corrección matemática, solo validez sintáctica de LaTeX.
"""
from __future__ import annotations

import random

_VARIABLES = list("abcdefghijklmnopqrstuvwxyz")
_VARIABLES_MAYUSCULAS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_GRIEGAS = [
    "alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu",
    "pi", "sigma", "phi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Omega",
]
_FUNCIONES = ["sin", "cos", "tan", "log", "ln", "exp", "cosh", "sinh", "arctan"]


def _atomo(rng: random.Random) -> str:
    opcion = rng.random()
    if opcion < 0.45:
        return rng.choice(_VARIABLES)
    if opcion < 0.55:
        return rng.choice(_VARIABLES_MAYUSCULAS)
    if opcion < 0.75:
        return "\\" + rng.choice(_GRIEGAS)
    if opcion < 0.9:
        return str(rng.randint(0, 20))
    return "%s_%d" % (rng.choice(_VARIABLES), rng.randint(0, 9))


def _expresion(rng: random.Random, profundidad: int) -> str:
    if profundidad <= 0:
        return _atomo(rng)

    def sub() -> str:
        return _expresion(rng, profundidad - 1)

    opcion = rng.random()
    if opcion < 0.18:
        return "\\frac{%s}{%s}" % (sub(), sub())
    if opcion < 0.30:
        # La base va entre llaves: sin ellas, encadenar potencias (p. ej. al
        # generar una potencia cuya propia base ya es otra potencia) produce
        # "a^b^c", que LaTeX rechaza como doble superindice.
        return "{%s}^{%s}" % (sub(), sub())
    if opcion < 0.40:
        return "{%s}_{%s}" % (sub(), sub())
    if opcion < 0.48:
        return "\\sqrt{%s}" % sub()
    if opcion < 0.54:
        return "\\sqrt[%d]{%s}" % (rng.randint(2, 5), sub())
    if opcion < 0.62:
        limite_sup = rng.choice(["n", "N", "\\infty"])
        return "\\sum_{%s=%d}^{%s} %s" % (rng.choice(_VARIABLES), rng.randint(0, 3), limite_sup, sub())
    if opcion < 0.68:
        return "\\prod_{%s=1}^{%s} %s" % (rng.choice(_VARIABLES), rng.choice(["n", "N"]), sub())
    if opcion < 0.76:
        return "\\int_{%s}^{%s} %s \\, d%s" % (sub(), sub(), sub(), rng.choice(_VARIABLES))
    if opcion < 0.82:
        return "\\%s\\left(%s\\right)" % (rng.choice(_FUNCIONES), sub())
    if opcion < 0.88:
        destino = rng.choice(["0", "\\infty", rng.choice(_VARIABLES)])
        return "\\lim_{%s \\to %s} %s" % (rng.choice(_VARIABLES), destino, sub())
    if opcion < 0.94:
        return "%s %s %s" % (sub(), rng.choice(["+", "-"]), sub())
    return "%s \\cdot %s" % (sub(), sub())


def _matriz(rng: random.Random) -> str:
    entorno = rng.choice(["pmatrix", "bmatrix", "vmatrix"])
    filas, columnas = rng.randint(2, 3), rng.randint(2, 3)
    filas_tex = [" & ".join(_atomo(rng) for _ in range(columnas)) for _ in range(filas)]
    cuerpo = " \\\\ ".join(filas_tex)
    return "\\begin{%s} %s \\end{%s}" % (entorno, cuerpo, entorno)


def generar_formula(rng: random.Random, profundidad_max: int = 3) -> str:
    """Genera una única fórmula LaTeX aleatoria."""
    if rng.random() < 0.08:
        return _matriz(rng)

    profundidad = rng.randint(1, profundidad_max)
    izquierda = _expresion(rng, profundidad)
    if rng.random() < 0.35:
        relacion = rng.choice(["=", "\\leq", "\\geq", "\\neq", "\\approx"])
        derecha = _expresion(rng, max(0, profundidad - 1))
        return "%s %s %s" % (izquierda, relacion, derecha)
    return izquierda


def generar_corpus(n: int, seed: int = 42, profundidad_max: int = 3, max_intentos_factor: int = 20) -> list[str]:
    """Genera hasta `n` fórmulas LaTeX únicas (puede devolver menos si se agotan los intentos)."""
    rng = random.Random(seed)
    vistos: set[str] = set()
    resultado: list[str] = []
    intentos = 0
    max_intentos = n * max_intentos_factor
    while len(resultado) < n and intentos < max_intentos:
        intentos += 1
        formula = generar_formula(rng, profundidad_max)
        if formula not in vistos:
            vistos.add(formula)
            resultado.append(formula)
    return resultado
