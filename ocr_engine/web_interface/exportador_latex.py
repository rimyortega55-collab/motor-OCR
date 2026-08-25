"""Exportación a LaTeX.

Es uno de los dos formatos principales del producto, junto con Markdown: quien
convierte un paper matemático normalmente quiere seguir trabajándolo en LaTeX,
no leerlo.

La regla que ordena todo el módulo es que hay dos clases de contenido y se tratan
al revés. Lo que sale de pix2tex **ya es LaTeX** y va tal cual; lo que sale de un
engine de texto es prosa y hay que escaparlo. Confundirlos es lo que hace que un
`.tex` exportado no compile: escapar una fórmula la destruye, y no escapar la
prosa la rompe en el primer `%`, que comenta el resto de la línea.
"""

from __future__ import annotations

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


def escapar(texto: str) -> str:
    """Vuelve inocua la prosa que va a un documento LaTeX."""
    for crudo, escapado in _ESCAPES:
        texto = texto.replace(crudo, escapado)
    return texto


def renderizar(titulo: str, bloques: list, contenido_de) -> str:
    """Arma el documento completo.

    `contenido_de(bloque)` resuelve qué texto vale para cada bloque, con la
    corrección humana por delante; se recibe como parámetro para no duplicar esa
    regla de prioridad, que es la misma para todos los formatos.
    """

    partes = [PREAMBULO, ""]
    partes.append(r"\title{" + escapar(titulo.rsplit(".", 1)[0] or "Documento") + "}")
    partes.append(r"\date{}")
    partes.append(r"\begin{document}")
    partes.append(r"\maketitle")
    partes.append("")

    for bloque in bloques:
        texto = (contenido_de(bloque) or "").strip()
        if not texto:
            continue

        tipo = bloque.tipo
        entorno = ENTORNO_POR_TIPO.get(tipo)

        if tipo == "encabezado":
            partes.append(r"\section{" + escapar(texto) + "}")
        elif tipo == "formula_display":
            # Ya es LaTeX: escaparlo lo convertiría en texto literal.
            partes.append(r"\begin{equation*}")
            partes.append(texto)
            partes.append(r"\end{equation*}")
        elif entorno:
            partes.append(r"\begin{" + entorno + "}")
            partes.append(escapar(texto))
            partes.append(r"\end{" + entorno + "}")
        elif tipo == "codigo":
            # lstlisting es verbatim: escapar acá rompería el código.
            partes.append(r"\begin{lstlisting}")
            partes.append(texto)
            partes.append(r"\end{lstlisting}")
        elif tipo == "caption":
            partes.append(r"\textit{" + escapar(texto) + "}")
        elif tipo == "tabla":
            # La tabla llega como Markdown desde la Capa 3. Convertirla a tabular
            # pide un parser propio; hasta entonces se preserva en verbatim en vez
            # de emitir un tabular malformado que no compile.
            partes.append(r"\begin{verbatim}")
            partes.append(texto)
            partes.append(r"\end{verbatim}")
        else:
            partes.append(escapar(texto))

        partes.append("")

    partes.append(r"\end{document}")
    return "\n".join(partes)
