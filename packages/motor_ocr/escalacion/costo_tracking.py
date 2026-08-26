"""Registro de tokens de entrada/salida por cada llamada a LLM.

Cada llamada se registra con: tokens de entrada/salida, documento/bloque que
la originó, y la razón de escalación. Alimenta el modelo de cobro por nivel
de trabajo real (no por conteo de páginas), y con el tiempo permite ajustar
los umbrales de confianza de las capas 3 y 4 — si un tipo de bloque escala
demasiado seguido, es señal de ajustar el engine determinista, no el umbral.

El registro se acumula en memoria por documento y la capa web lo persiste al
terminar de procesar, que es cuando se conoce el usuario al que atribuirlo. Se
mantiene esa división para que el motor no dependa de la base de datos: sigue
siendo usable como librería suelta.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from motor_ocr.modelos import Costo

# Precio por millón de tokens. Sin tabla por modelo el cálculo queda mal apenas
# se cambia de modelo: antes se asumía Sonnet 3.5 para todo.
TARIFAS_POR_MODELO: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
TARIFA_POR_DEFECTO = (5.00, 25.00)

# Registros agrupados por documento. Un único acumulador global mezclaría los
# costos de requests concurrentes y le cobraría a un usuario el trabajo de otro.
_registro_por_documento: dict[str, list["RegistroCosto"]] = defaultdict(list)

# Log opcional en JSONL, sólo para depuración local. La fuente de verdad es la
# base de datos: un archivo dentro del contenedor no sobrevive al despliegue.
_ruta_log: Path | None = (
    Path(os.environ["MOTOR_OCR_LOG_COSTOS"])
    if os.environ.get("MOTOR_OCR_LOG_COSTOS")
    else None
)


def calcular_costo_usd(tokens_entrada: int, tokens_salida: int, modelo: str) -> float:
    """Costo en dólares de una llamada, según la tarifa del modelo usado."""
    entrada, salida = TARIFAS_POR_MODELO.get(modelo, TARIFA_POR_DEFECTO)
    return (tokens_entrada * entrada + tokens_salida * salida) / 1_000_000


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
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.documento_id = str(documento_id)
        self.bloque_id = str(bloque_id) if bloque_id else None
        self.tokens_entrada = costo.tokens_entrada
        self.tokens_salida = costo.tokens_salida
        self.modelo_usado = costo.modelo_usado
        self.razon_escalacion = razon_escalacion
        self.tipo_cola = tipo_cola

    @property
    def modelo(self) -> str:
        if isinstance(self.modelo_usado, list):
            return self.modelo_usado[0] if self.modelo_usado else "desconocido"
        return self.modelo_usado or "desconocido"

    @property
    def costo_usd(self) -> float:
        return calcular_costo_usd(self.tokens_entrada, self.tokens_salida, self.modelo)

    def a_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "documento_id": self.documento_id,
            "bloque_id": self.bloque_id,
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "modelo_usado": self.modelo_usado,
            "costo_usd": self.costo_usd,
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

    _registro_por_documento[registro.documento_id].append(registro)

    if _ruta_log is not None:
        try:
            with open(_ruta_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro.a_dict()) + "\n")
        except Exception as e:
            print(f"[COSTO] Error escribiendo log: {e}")


def obtener_registros(documento_id: UUID | str | None = None) -> list[RegistroCosto]:
    """Registros de un documento, o de todos si no se indica ninguno."""
    if documento_id is None:
        return [r for registros in _registro_por_documento.values() for r in registros]
    return list(_registro_por_documento.get(str(documento_id), []))


def obtener_estadisticas(documento_id: UUID | str | None = None) -> dict:
    """Estadísticas de costos, de un documento o globales."""

    registros = obtener_registros(documento_id)

    if not registros:
        return {
            "total_llamadas": 0,
            "tokens_entrada_total": 0,
            "tokens_salida_total": 0,
            "costo_estimado_usd": 0.0,
            "por_tipo_cola": {}
        }

    total_entrada = sum(r.tokens_entrada for r in registros)
    total_salida = sum(r.tokens_salida for r in registros)
    costo_estimado = sum(r.costo_usd for r in registros)

    por_cola = {}
    for tipo_cola in ["micro_segmento", "inconsistencia_documental"]:
        registros_cola = [r for r in registros if r.tipo_cola == tipo_cola]
        if registros_cola:
            por_cola[tipo_cola] = {
                "llamadas": len(registros_cola),
                "tokens_entrada": sum(r.tokens_entrada for r in registros_cola),
                "tokens_salida": sum(r.tokens_salida for r in registros_cola),
                "costo_estimado_usd": sum(r.costo_usd for r in registros_cola),
            }

    return {
        "total_llamadas": len(registros),
        "tokens_entrada_total": total_entrada,
        "tokens_salida_total": total_salida,
        "costo_estimado_usd": costo_estimado,
        "por_tipo_cola": por_cola
    }


def limpiar_registro(documento_id: UUID | str | None = None) -> None:
    """Descarta los registros ya persistidos, o todos si no se indica documento."""
    if documento_id is None:
        _registro_por_documento.clear()
    else:
        _registro_por_documento.pop(str(documento_id), None)


def establecer_ruta_log(ruta: str | Path | None) -> None:
    """Establece (o desactiva, con None) el log JSONL de depuración."""
    global _ruta_log
    _ruta_log = Path(ruta) if ruta is not None else None
