#!/usr/bin/env python
"""Arnés de evaluación (Fase B): corre el pipeline completo sobre los 11 PDF de
prueba y mide robustez estructural, no fidelidad textual.

No hay ground truth en el repo, así que este arnés no compara el LaTeX/Markdown
generado contra una referencia. Lo que sí puede medir sin inventar nada:

- Si el pipeline termina sin excepción para cada PDF.
- Si el .tex resultante compila con pdflatex (un .tex que no compila es un
  fracaso de robustez, no un matiz de fidelidad).
- Qué motor de OCR resolvió cada bloque, y qué fracción del documento quedó
  sin resolver (contenido vacío) o escalada al LLM.
- Cuánto del documento es matemática (fórmulas), para poder repetir la
  medición del 0,5%-6,7% citada como base del corpus.

Uso:
    .venv/Scripts/python.exe pruebas/arnes_evaluacion.py [c1 c2 ...]

Sin argumentos corre los 11. Con argumentos, sólo esos (útil para iterar
rápido sobre uno que falló).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from motor_ocr.pipeline import Pipeline
from motor_ocr_render import renderizar
from motor_ocr_render.contrato import DocumentoRenderizable, desde_bloque, ordenar

RAIZ = Path(__file__).parent
DIR_PDFS = RAIZ / "pdfs_de_prueba"
DIR_SALIDA = RAIZ / "resultados_arnes"


def _compilar_latex(tex: str, nombre: str) -> tuple[bool, str]:
    """Compila con pdflatex en un directorio temporal. Devuelve (compiló, log)."""
    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        return False, "pdflatex no está en el PATH"

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = Path(tmp) / f"{nombre}.tex"
        tex_path.write_text(tex, encoding="utf-8")
        try:
            resultado = subprocess.run(
                [pdflatex, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout de 120s compilando"

        pdf_generado = (Path(tmp) / f"{nombre}.pdf").exists()
        log = resultado.stdout[-4000:]
        return pdf_generado, log


def _es_bloque_matematico(tipo: str) -> bool:
    return tipo in {"formula_display", "formula_inline"}


def evaluar_uno(ruta_pdf: Path) -> dict:
    nombre = ruta_pdf.stem
    inicio = time.monotonic()
    reporte: dict = {"pdf": nombre, "ok": False}

    try:
        documento, bloques = Pipeline().ejecutar(str(ruta_pdf))
    except Exception as e:
        reporte["error_pipeline"] = f"{type(e).__name__}: {e}"
        reporte["traceback"] = traceback.format_exc()[-4000:]
        reporte["segundos"] = round(time.monotonic() - inicio, 1)
        return reporte

    reporte["segundos"] = round(time.monotonic() - inicio, 1)
    reporte["total_paginas"] = documento.total_paginas
    reporte["total_bloques"] = len(bloques)

    # Distribución por tipo, por motor y por origen del contenido.
    por_tipo: dict[str, int] = {}
    por_engine: dict[str, int] = {}
    vacios = 0
    caracteres_totales = 0
    caracteres_matematica = 0

    for b in bloques:
        tipo = getattr(b.tipo, "value", str(b.tipo))
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1

        texto = (b.contenido.latex or b.contenido.texto_plano or "").strip()
        if not texto:
            vacios += 1
        caracteres_totales += len(texto)
        if _es_bloque_matematico(tipo):
            caracteres_matematica += len(texto)

        for micro in b.ocr.micro_segmentos:
            motor = getattr(micro.engine_usado, "value", str(micro.engine_usado))
            por_engine[motor] = por_engine.get(motor, 0) + 1

    reporte["bloques_por_tipo"] = por_tipo
    reporte["bloques_por_engine"] = por_engine
    reporte["bloques_vacios"] = vacios
    reporte["porcentaje_matematica"] = (
        round(100 * caracteres_matematica / caracteres_totales, 2)
        if caracteres_totales
        else 0.0
    )

    # Render y compilación: la prueba de robustez real.
    doc_renderizable = DocumentoRenderizable(titulo=documento.titulo, total_paginas=documento.total_paginas)
    bloques_renderizables = ordenar(desde_bloque(b) for b in bloques)

    try:
        tex = renderizar("latex", doc_renderizable, bloques_renderizables)
    except Exception as e:
        reporte["error_render_latex"] = f"{type(e).__name__}: {e}"
        reporte["ok"] = False
        return reporte

    try:
        md = renderizar("markdown", doc_renderizable, bloques_renderizables)
    except Exception as e:
        reporte["error_render_markdown"] = f"{type(e).__name__}: {e}"
        md = None

    DIR_SALIDA.mkdir(exist_ok=True)
    (DIR_SALIDA / f"{nombre}.tex").write_text(tex, encoding="utf-8")
    if md is not None:
        (DIR_SALIDA / f"{nombre}.md").write_text(md, encoding="utf-8")

    compiló, log = _compilar_latex(tex, nombre)
    reporte["latex_compila"] = compiló
    if not compiló:
        (DIR_SALIDA / f"{nombre}_pdflatex.log").write_text(log, encoding="utf-8")
        reporte["log_compilacion"] = log[-1500:]

    reporte["ok"] = compiló and "error_pipeline" not in reporte
    return reporte


def main() -> None:
    pedidos = sys.argv[1:]
    if pedidos:
        pdfs = [DIR_PDFS / f"{p}.pdf" for p in pedidos]
    else:
        pdfs = sorted(DIR_PDFS.glob("c*.pdf"), key=lambda p: int(p.stem[1:]))

    DIR_SALIDA.mkdir(exist_ok=True)
    reportes = []

    for ruta in pdfs:
        print(f"\n=== {ruta.stem} ===")
        reporte = evaluar_uno(ruta)
        reportes.append(reporte)

        if "error_pipeline" in reporte:
            print(f"  ✗ el pipeline lanzó una excepción: {reporte['error_pipeline']}")
            continue

        print(f"  {reporte['total_paginas']} páginas · {reporte['total_bloques']} bloques "
              f"· {reporte['segundos']}s")
        print(f"  matemática: {reporte['porcentaje_matematica']}% de los caracteres")
        print(f"  bloques vacíos: {reporte['bloques_vacios']}")
        print(f"  motores: {reporte.get('bloques_por_engine', {})}")
        if "error_render_latex" in reporte:
            print(f"  ✗ el render a LaTeX lanzó una excepción: {reporte['error_render_latex']}")
        elif reporte.get("latex_compila"):
            print("  ✓ el .tex compila con pdflatex")
        else:
            print("  ✗ el .tex NO compila (ver *_pdflatex.log)")

    (DIR_SALIDA / "reporte.json").write_text(
        json.dumps(reportes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = len(reportes)
    ok = sum(1 for r in reportes if r.get("ok"))
    print(f"\n=== resumen: {ok}/{total} documentos procesaron y compilaron sin fallar ===")
    if ok < total:
        print("fallaron:", ", ".join(r["pdf"] for r in reportes if not r.get("ok")))


if __name__ == "__main__":
    main()
