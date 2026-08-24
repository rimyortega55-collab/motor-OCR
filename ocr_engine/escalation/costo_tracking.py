"""Registro de tokens de entrada/salida por cada llamada a LLM.

Cada llamada se registra con: tokens de entrada/salida, documento/bloque que
la originó, y la razón de escalación. Alimenta el modelo de cobro por nivel
de trabajo real (no por conteo de páginas), y con el tiempo permite ajustar
los umbrales de confianza de las capas 3 y 4 — si un tipo de bloque escala
demasiado seguido, es señal de ajustar el engine determinista, no el umbral.
"""

from __future__ import annotations

from uuid import UUID
from datetime import datetime
from pathlib import Path

from ocr_engine.models import Costo

# Registro de llamadas (en-memory; en producción usar DB)
_registro_llamadas = []
_ruta_log = Path("costo_escalaciones.jsonl")


class RegistroCosto:
    """Entrada en el registro de costos."""

    def __init__(
        self,
        documento_id: UUID,
        bloque_id: UUID | None,
        costo: Costo,
        razon_escalacion: str,
        tipo_cola: str = "micro_segmento"
    ):
        self.timestamp = datetime.utcnow().isoformat()
        self.documento_id = str(documento_id)
        self.bloque_id = str(bloque_id) if bloque_id else None
        self.tokens_entrada = costo.tokens_entrada
        self.tokens_salida = costo.tokens_salida
        self.modelo_usado = costo.modelo_usado
        self.razon_escalacion = razon_escalacion
        self.tipo_cola = tipo_cola

    def a_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "documento_id": self.documento_id,
            "bloque_id": self.bloque_id,
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "modelo_usado": self.modelo_usado,
            "razon_escalacion": self.razon_escalacion,
            "tipo_cola": self.tipo_cola,
        }


def registrar_costo(
    documento_id: UUID,
    bloque_id: UUID | None,
    costo: Costo,
    razon_escalacion: str,
    tipo_cola: str = "micro_segmento"
) -> None:
    """Registra costo de una llamada a LLM.

    Args:
        documento_id: ID del documento
        bloque_id: ID del bloque (None para inconsistencias documentales)
        costo: Objeto Costo con tokens y modelo
        razon_escalacion: Razón por la que se escaló
        tipo_cola: "micro_segmento" o "inconsistencia_documental"
    """

    registro = RegistroCosto(
        documento_id=documento_id,
        bloque_id=bloque_id,
        costo=costo,
        razon_escalacion=razon_escalacion,
        tipo_cola=tipo_cola
    )

    _registro_llamadas.append(registro)

    # Escribir a JSONL (append-only)
    try:
        import json
        with open(_ruta_log, "a") as f:
            f.write(json.dumps(registro.a_dict()) + "\n")
    except Exception as e:
        print(f"[COSTO] Error escribiendo log: {e}")


def obtener_estadisticas() -> dict:
    """Obtiene estadísticas de costos."""

    if not _registro_llamadas:
        return {
            "total_llamadas": 0,
            "tokens_entrada_total": 0,
            "tokens_salida_total": 0,
            "costo_estimado_usd": 0.0,
            "por_tipo_cola": {}
        }

    total_entrada = sum(r.tokens_entrada for r in _registro_llamadas)
    total_salida = sum(r.tokens_salida for r in _registro_llamadas)

    # Precios aproximados de Claude 3.5 Sonnet
    precio_entrada = 3 / 1_000_000  # $3 por 1M tokens entrada
    precio_salida = 15 / 1_000_000  # $15 por 1M tokens salida

    costo_estimado = (total_entrada * precio_entrada) + (total_salida * precio_salida)

    # Estadísticas por cola
    por_cola = {}
    for tipo_cola in ["micro_segmento", "inconsistencia_documental"]:
        registros_cola = [r for r in _registro_llamadas if r.tipo_cola == tipo_cola]
        if registros_cola:
            entrada_cola = sum(r.tokens_entrada for r in registros_cola)
            salida_cola = sum(r.tokens_salida for r in registros_cola)
            costo_cola = (entrada_cola * precio_entrada) + (salida_cola * precio_salida)

            por_cola[tipo_cola] = {
                "llamadas": len(registros_cola),
                "tokens_entrada": entrada_cola,
                "tokens_salida": salida_cola,
                "costo_estimado_usd": costo_cola
            }

    return {
        "total_llamadas": len(_registro_llamadas),
        "tokens_entrada_total": total_entrada,
        "tokens_salida_total": total_salida,
        "costo_estimado_usd": costo_estimado,
        "por_tipo_cola": por_cola
    }


def limpiar_registro():
    """Limpia el registro en-memory (para testing)."""
    global _registro_llamadas
    _registro_llamadas = []


def establecer_ruta_log(ruta: str | Path) -> None:
    """Establece la ruta del log de costos."""
    global _ruta_log
    _ruta_log = Path(ruta)
