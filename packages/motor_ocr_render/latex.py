"""Exportación a LaTeX.

Es uno de los dos formatos principales del producto, junto con Markdown: quien
convierte un paper matemático normalmente quiere seguir trabajándolo en LaTeX,
no leerlo.

La regla que ordena todo el módulo es que hay dos clases de contenido y se tratan
al revés. Lo que sale de pix2tex **ya es LaTeX** y va tal cual; lo que sale de un
engine de texto es prosa y hay que escaparlo. Confundirlos es lo que hace que un
`.tex` exportado no compile: escapar una fórmula la destruye, y no escapar la
prosa la rompe en el primer `%`, que comenta el resto de la línea.

La segunda causa de `.tex` que no compilan es el Unicode que arrastra el OCR. Un
PDF escaneado devuelve ligaduras tipográficas (ﬁ, ﬂ), comillas curvas, viñetas,
símbolos matemáticos sueltos en medio de la prosa y, de vez en cuando, bytes de
control crudos. `pdflatex` aborta con «Unicode character not set up for use with
LaTeX» ante cualquiera de ellos, así que todo texto pasa por `sanear()` antes de
llegar al documento: se tiran los controles y se traduce cada símbolo a su macro.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from .contrato import BloqueRenderizable, DocumentoRenderizable, ordenar

# Entornos de amsthm por tipo de bloque del motor. El preámbulo los declara.
ENTORNO_POR_TIPO = {
    "teorema": "theorem",
    "lema": "lemma",
    "proposicion": "proposition",
    "definicion": "definition",
    "corolario": "corollary",
    "demostracion": "proof",
}

PREAMBULO = r"""\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{textcomp}
\usepackage{amsmath, amssymb, amsthm}
\usepackage{graphicx}
\usepackage{listings}
\usepackage[hidelinks]{hyperref}

\theoremstyle{plain}
\newtheorem{theorem}{Teorema}[section]
\newtheorem{lemma}[theorem]{Lema}
\newtheorem{proposition}[theorem]{Proposición}
\newtheorem{corollary}[theorem]{Corolario}

\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definición}
"""

# El orden importa: la barra invertida va primero, porque si no, los reemplazos
# siguientes introducen barras que este mismo paso volvería a escapar.
_ESCAPES = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]

# Controles C0/C1, marcas de dirección y espacios de ancho cero. No significan
# nada en el papel y cualquiera de ellos aborta la compilación.
_CONTROLES = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"  # C0 y C1
    "\u00ad\u200b-\u200f\u2028\u2029\u202a-\u202e\ufeff]"  # invisibles
)

# Hasta Latin Extended-A el par inputenc+T1 resuelve solo (á, ñ, ü, š, ł...).
# Más allá hace falta una macro explícita o el documento no compila.
_LIMITE_SOPORTADO = 0x17F

# Símbolos a macro de LaTeX en modo texto. Los que son matemáticos van entre `$`
# porque en la prosa del OCR aparecen sueltos, fuera de cualquier entorno.
_MAPA_UNICODE = {
    # Ligaduras tipográficas: el OCR de un PDF las devuelve como un solo carácter.
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st",
    # Comillas, guiones y puntuación.
    "‘": "`", "’": "'", "‚": ",", "‛": "`",
    "“": "``", "”": "''", "„": ",,", "‟": "``",
    "‐": "-", "‑": "-", "‒": "--", "–": "--", "—": "---",
    "―": "---", "…": r"\dots{}", "•": r"\textbullet{}",
    "‣": r"\textbullet{}", "●": r"\textbullet{}", "▪": r"\textbullet{}",
    "·": r"\textperiodcentered{}", "‧": r"\textperiodcentered{}",
    "′": "$'$", "″": "$''$", "‴": "$'''$",
    "⁄": "/", "∕": "/",
    "\u00a0": "~", "\u202f": "~", "\u2007": "~",
    "\u2009": r"\,", "\u200a": r"\,", "\u2008": r"\,",
    "\u2003": r"\quad{}", "\u2002": r"\enspace{}",
    "™": r"\texttrademark{}", "№": "No.", "‰": r"\textperthousand{}",
    "←": r"$\leftarrow$", "→": r"$\to$", "↔": r"$\leftrightarrow$",
    "↦": r"$\mapsto$", "⇐": r"$\Leftarrow$", "⇒": r"$\Rightarrow$",
    "⇔": r"$\Leftrightarrow$", "↑": r"$\uparrow$", "↓": r"$\downarrow$",
    "↪": r"$\hookrightarrow$", "↛": r"$\nrightarrow$",
    # Operadores y relaciones.
    "−": "$-$", "×": r"$\times$", "÷": r"$\div$", "±": r"$\pm$",
    "∓": r"$\mp$", "⋅": r"$\cdot$", "∘": r"$\circ$", "∗": "$*$",
    "≤": r"$\leq$", "≥": r"$\geq$", "⩽": r"$\leq$", "⩾": r"$\geq$",
    "≠": r"$\neq$", "≈": r"$\approx$", "≡": r"$\equiv$",
    "≢": r"$\not\equiv$", "∼": r"$\sim$", "≅": r"$\cong$",
    "≪": r"$\ll$", "≫": r"$\gg$", "∝": r"$\propto$",
    "∞": r"$\infty$", "∂": r"$\partial$", "∇": r"$\nabla$",
    "√": r"$\surd$", "∛": r"$\sqrt[3]{\ }$",
    "∑": r"$\sum$", "∏": r"$\prod$", "∫": r"$\int$", "∮": r"$\oint$",
    "∅": r"$\emptyset$", "∈": r"$\in$", "∉": r"$\notin$", "∋": r"$\ni$",
    "⊂": r"$\subset$", "⊃": r"$\supset$", "⊆": r"$\subseteq$",
    "⊇": r"$\supseteq$", "∪": r"$\cup$", "∩": r"$\cap$",
    "∖": r"$\setminus$", "⊕": r"$\oplus$", "⊗": r"$\otimes$",
    "∀": r"$\forall$", "∃": r"$\exists$", "∄": r"$\nexists$",
    "¬": r"$\neg$", "∧": r"$\land$", "∨": r"$\lor$",
    "∴": r"$\therefore$", "∵": r"$\because$", "∎": r"$\blacksquare$",
    "⊥": r"$\perp$", "∥": r"$\parallel$", "∠": r"$\angle$",
    "⊢": r"$\vdash$", "⊨": r"$\models$", "⋯": r"$\cdots$",
    "⋮": r"$\vdots$", "⋱": r"$\ddots$",
    "⌈": r"$\lceil$", "⌉": r"$\rceil$", "⌊": r"$\lfloor$", "⌋": r"$\rfloor$",
    "⟨": r"$\langle$", "⟩": r"$\rangle$", "‖": r"$\|$",
    "ℝ": r"$\mathbb{R}$", "ℕ": r"$\mathbb{N}$", "ℤ": r"$\mathbb{Z}$",
    "ℚ": r"$\mathbb{Q}$", "ℂ": r"$\mathbb{C}$", "ℵ": r"$\aleph$",
    "ℓ": r"$\ell$", "ℏ": r"$\hbar$", "°": r"\textdegree{}",
    # Fracciones.
    "½": r"$\frac{1}{2}$", "⅓": r"$\frac{1}{3}$", "⅔": r"$\frac{2}{3}$",
    "¼": r"$\frac{1}{4}$", "¾": r"$\frac{3}{4}$", "⅛": r"$\frac{1}{8}$",
    # Índices sueltos.
    "²": "$^{2}$", "³": "$^{3}$", "¹": "$^{1}$", "⁰": "$^{0}$",
    "⁴": "$^{4}$", "⁵": "$^{5}$", "⁶": "$^{6}$", "⁷": "$^{7}$",
    "⁸": "$^{8}$", "⁹": "$^{9}$", "⁺": "$^{+}$", "⁻": "$^{-}$",
    "ⁿ": "$^{n}$", "₀": "$_{0}$", "₁": "$_{1}$", "₂": "$_{2}$",
    "₃": "$_{3}$", "₄": "$_{4}$", "₅": "$_{5}$", "₆": "$_{6}$",
    "₇": "$_{7}$", "₈": "$_{8}$", "₉": "$_{9}$",
    # Acentos sueltos que el OCR separa de su letra.
    "´": "'", "ˆ": r"\^{}", "˜": r"\textasciitilde{}",
}

# El griego va aparte porque es una tabla regular y ocupa media pantalla.
_GRIEGO = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "varepsilon", "ϵ": "epsilon", "ζ": "zeta", "η": "eta",
    "θ": "theta", "ϑ": "vartheta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "µ": "mu", "ν": "nu", "ξ": "xi",
    "π": "pi", "ϖ": "varpi", "ρ": "rho", "ϱ": "varrho",
    "σ": "sigma", "ς": "varsigma", "τ": "tau", "υ": "upsilon",
    "φ": "varphi", "ϕ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda",
    "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma", "Υ": "Upsilon",
    "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega", "Ω": "Omega",
}
_MAPA_UNICODE.update({letra: f"$\\{macro}$" for letra, macro in _GRIEGO.items()})

# Equivalentes ASCII para los entornos verbatim, donde una macro se imprimiría
# literal en vez de ejecutarse.
_MAPA_VERBATIM = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "--",
    "−": "-", "…": "...", "•": "*", "·": ".", " ": " ",
    "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~=", "×": "x",
    "÷": "/", "→": "->", "←": "<-", "⇒": "=>", "⇔": "<=>",
    "⁄": "/", "′": "'", "″": '"',
}


def limpiar(texto: str) -> str:
    """Quita lo que ninguna variante de LaTeX puede imprimir.

    La normalización a NFC va después de tirar los controles porque recompone
    las secuencias que el OCR parte en dos (`=` + U+0338 vuelve a ser `≠`), y así
    el mapa de símbolos las encuentra como un solo carácter.
    """
    return unicodedata.normalize("NFC", _CONTROLES.sub("", texto))


def _degradar(caracter: str) -> str:
    """Último recurso para un símbolo sin macro: su esqueleto ASCII, o nada.

    Se prefiere perder un carácter exótico antes que emitir un `.tex` que aborta:
    el documento entero vale más que el símbolo.
    """
    plano = unicodedata.normalize("NFKD", caracter)
    return "".join(c for c in plano if ord(c) <= _LIMITE_SOPORTADO and not unicodedata.combining(c))


def _traducir(texto: str, mapa: dict) -> str:
    piezas = []
    for caracter in texto:
        if caracter in mapa:
            piezas.append(mapa[caracter])
        elif ord(caracter) <= _LIMITE_SOPORTADO:
            piezas.append(caracter)
        else:
            piezas.append(_degradar(caracter))
    return "".join(piezas)


def sanear(texto: str) -> str:
    """Deja el Unicode del OCR en algo que pdflatex sepa componer."""
    return _traducir(limpiar(texto), _MAPA_UNICODE)


def escapar(texto: str) -> str:
    """Vuelve inocua la prosa que va a un documento LaTeX.

    El saneado de símbolos va al final, después de escapar: introduce macros con
    barras y llaves que el escapado convertiría en texto literal.
    """
    texto = limpiar(texto)
    for crudo, escapado in _ESCAPES:
        texto = texto.replace(crudo, escapado)
    return _traducir(texto, _MAPA_UNICODE)


_PATRON_FORMULA_INLINE = re.compile(r"\$[^$]+\$")


def escapar_con_formulas(texto: str) -> str:
    """Escapa la prosa de un bloque que puede traer fórmulas `$...$` embebidas.

    Capa 3 intercala fragmentos ya reconocidos por pix2tex dentro del texto
    corrido de un bloque nativo-digital (ver
    reconocimiento/enrutador.py:_procesar_bloque_nativo_con_formulas). Pasar
    el bloque entero por `escapar` destruye esas fórmulas —convierte cada
    barra y llave de su sintaxis en texto literal—, así que sólo la prosa
    alrededor de cada `$...$` se escapa; el interior sólo pasa por `sanear`,
    igual que se hace con `formula_display`.
    """
    piezas = []
    ultimo = 0
    for coincidencia in _PATRON_FORMULA_INLINE.finditer(texto):
        if coincidencia.start() > ultimo:
            piezas.append(escapar(texto[ultimo:coincidencia.start()]))
        piezas.append("$" + sanear(coincidencia.group()[1:-1]) + "$")
        ultimo = coincidencia.end()
    piezas.append(escapar(texto[ultimo:]))
    return "".join(piezas)


def _verbatim(texto: str, entorno: str) -> str:
    """Prepara contenido literal: sin macros, y sin poder cerrar su propio entorno."""
    texto = _traducir(limpiar(texto), _MAPA_VERBATIM)
    # Un `\end{verbatim}` dentro del contenido cierra el entorno antes de tiempo
    # y descarrila el resto del documento.
    return texto.replace("\\end{" + entorno + "}", "\\end {" + entorno + "}")


def renderizar(
    documento: DocumentoRenderizable, bloques: Sequence[BloqueRenderizable]
) -> str:
    """Arma el documento completo.

    Cada bloque llega con su `texto` ya resuelto: la regla de prioridad que
    antepone la corrección humana vive una sola vez, en `contrato.py`, porque
    es la misma para todos los formatos.
    """

    titulo = documento.titulo or "Documento"
    partes = [PREAMBULO, ""]
    partes.append(r"\title{" + escapar(titulo.rsplit(".", 1)[0] or "Documento") + "}")
    partes.append(r"\date{}")
    partes.append(r"\begin{document}")
    partes.append(r"\maketitle")
    partes.append("")

    for bloque in ordenar(bloques):
        texto = bloque.texto.strip()
        if not texto:
            continue

        tipo = bloque.tipo
        entorno = ENTORNO_POR_TIPO.get(tipo)

        if tipo == "encabezado":
            partes.append(r"\section{" + escapar_con_formulas(texto) + "}")
        elif tipo == "formula_display":
            # Ya es LaTeX: escaparlo lo convertiría en texto literal. Aun así pasa
            # por `sanear`, porque pix2tex también devuelve símbolos crudos y ahí
            # el contexto ya es matemático.
            partes.append(r"\begin{equation*}")
            partes.append(sanear(texto))
            partes.append(r"\end{equation*}")
        elif entorno:
            partes.append(r"\begin{" + entorno + "}")
            partes.append(escapar_con_formulas(texto))
            partes.append(r"\end{" + entorno + "}")
        elif tipo == "codigo":
            # lstlisting es verbatim: escapar acá rompería el código.
            partes.append(r"\begin{lstlisting}")
            partes.append(_verbatim(texto, "lstlisting"))
            partes.append(r"\end{lstlisting}")
        elif tipo == "caption":
            partes.append(r"\textit{" + escapar_con_formulas(texto) + "}")
        elif tipo == "tabla":
            # La tabla llega como Markdown desde la Capa 3. Convertirla a tabular
            # pide un parser propio; hasta entonces se preserva en verbatim en vez
            # de emitir un tabular malformado que no compile.
            partes.append(r"\begin{verbatim}")
            partes.append(_verbatim(texto, "verbatim"))
            partes.append(r"\end{verbatim}")
        else:
            partes.append(escapar_con_formulas(texto))

        partes.append("")

    partes.append(r"\end{document}")
    return "\n".join(partes)
