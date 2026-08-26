#!/usr/bin/env python
"""Proyecta el costo de la Capa 5 sin gastar en llamadas reales al LLM.

La Capa 5 nunca se ejecutó de verdad: sin ANTHROPIC_API_KEY el cliente cae al
fallback y todas las corridas registran $0.0000. Como el costo por documento es
lo que define el margen del producto, este script lo estima a partir de lo que
*efectivamente se enviaría*: recorre el pipeline real hasta Capa 3, detecta qué
micro-segmentos superarían el umbral de escalación y mide sus recortes.

El conteo de tokens de imagen sigue la regla de Claude (ancho*alto/750). Los
tokens de texto se aproximan por caracteres/4, suficiente para un orden de
magnitud; el número exacto sale de messages.count_tokens cuando haya credenciales.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from motor_ocr.triage import procesar_triage
from motor_ocr.layout import segmentar_documento
from motor_ocr.reconocimiento import enrutar_bloque
from motor_ocr.reconocimiento.sub_segmentacion import sub_segmentar
from motor_ocr.modelos import Documento, Origen

# Precios por millón de tokens (Claude API, primera parte)
TARIFAS = {
    "claude-opus-5":   {"entrada": 5.00, "salida": 25.00},
    "claude-sonnet-5": {"entrada": 3.00, "salida": 15.00},
    "claude-haiku-4-5": {"entrada": 1.00, "salida": 5.00},
}

UMBRAL_ESCALACION = 0.6
TOKENS_PROMPT = 160        # plantilla de cliente_llm.py, medida
TOKENS_CONTEXTO = 120      # contexto de texto circundante que se adjunta
TOKENS_SALIDA = 180        # respuesta JSON típica (max_tokens=1024 es el techo)

pdf_dir = Path(__file__).parent / "pdfs_escaneados"


def tokens_imagen(ancho: int, alto: int) -> float:
    """Tokens que consume una imagen en la API de Claude."""
    return (ancho * alto) / 750.0


def analizar(ruta_pdf: Path) -> dict:
    resultados_triage, zonas = procesar_triage(str(ruta_pdf))
    documento = Documento(
        titulo=ruta_pdf.stem,
        origen=Origen.ESCANEADO,
        idioma_original="es",
        total_paginas=len(resultados_triage),
        version_pipeline="estimacion-costo",
        zonas_dpi=zonas,
    )
    bloques = segmentar_documento(documento, str(ruta_pdf), resultados_triage)

    doc = pymupdf.open(str(ruta_pdf))
    escalados = []

    for idx, triage in enumerate(resultados_triage):
        zoom = triage.dpi_objetivo / 72.0
        pix = doc[idx].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        imagen = cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img.shape[2] == 3 else img[:, :, 0]

        for bloque in [b for b in bloques if b.pagina == idx]:
            resultado = enrutar_bloque(bloque, imagen, triage.dpi_objetivo)
            if resultado.confianza_global >= UMBRAL_ESCALACION:
                continue
            # Cada micro-segmento del bloque sería una llamada con imagen
            for _, region in sub_segmentar(bloque, imagen, triage.dpi_objetivo):
                if isinstance(region, np.ndarray) and region.size:
                    escalados.append((region.shape[1], region.shape[0]))

    doc.close()
    return {
        "paginas": len(resultados_triage),
        "bloques": len(bloques),
        "llamadas": escalados,
    }


def main() -> None:
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print("No hay PDFs escaneados. Corré antes: python generar_pdfs_escaneados.py")
        raise SystemExit(1)

    total_paginas = 0
    todas_llamadas: list[tuple[int, int]] = []

    for pdf in pdfs:
        datos = analizar(pdf)
        total_paginas += datos["paginas"]
        todas_llamadas.extend(datos["llamadas"])
        print(f"{pdf.name}: {datos['paginas']} pag, {datos['bloques']} bloques, "
              f"{len(datos['llamadas'])} llamadas al LLM")

    if not todas_llamadas:
        print("\nNingún bloque supera el umbral de escalación en este corpus.")
        return

    tok_img = [tokens_imagen(w, h) for w, h in todas_llamadas]
    entrada_por_llamada = np.mean(tok_img) + TOKENS_PROMPT + TOKENS_CONTEXTO
    llamadas_por_pagina = len(todas_llamadas) / total_paginas

    print("\n" + "=" * 62)
    print("PROYECCIÓN DE COSTO — CAPA 5")
    print("=" * 62)
    print(f"Corpus: {total_paginas} páginas, {len(todas_llamadas)} llamadas")
    print(f"Llamadas por página: {llamadas_por_pagina:.2f}")
    print(f"Tokens de imagen por llamada: {np.mean(tok_img):.0f} "
          f"(min {min(tok_img):.0f}, max {max(tok_img):.0f})")
    print(f"Tokens de entrada por llamada: {entrada_por_llamada:.0f}")
    print(f"Tokens de salida por llamada: {TOKENS_SALIDA}")

    for paginas_doc in (10, 25, 100):
        llamadas = llamadas_por_pagina * paginas_doc
        print(f"\n--- Documento de {paginas_doc} páginas ({llamadas:.0f} llamadas) ---")
        for modelo, tarifa in TARIFAS.items():
            costo = (
                llamadas * entrada_por_llamada / 1_000_000 * tarifa["entrada"]
                + llamadas * TOKENS_SALIDA / 1_000_000 * tarifa["salida"]
            )
            print(f"  {modelo:18} ${costo:7.4f}")

    print("\nNota: proyección, no medición. Los micro-segmentos nunca se encolan")
    print("(encolar_micro_segmento no se llama desde ningún lado), así que hoy el")
    print("costo real es $0 porque la funcionalidad no está conectada.")


if __name__ == "__main__":
    main()
