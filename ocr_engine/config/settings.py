"""Umbrales de confianza, DPI por defecto y límites de concurrencia.

Centralizado acá (en vez de constantes dispersas en cada capa) porque estos
valores se van a calibrar con datos reales de uso — ver
.contexto/04-estructura-proyecto.md, sección "Notas de implementación".
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Triage (Capa 1)
    dpi_triage_bajo_costo: int = 150
    dpi_zona_texto: int = 200
    dpi_zona_formula: int = 400

    # OCR especializado (Capa 3)
    umbral_confianza_engine: float = 0.75
    umbral_confianza_estructural: float = 0.75
    umbral_confianza_global_escalacion: float = 0.70

    # Corrección (Capa 4)
    distancia_edicion_maxima_ortografia: int = 1

    # Escalación (Capa 5)
    limite_concurrencia_llm: int = 4
    modelo_escalacion: str = "claude-sonnet-5"

    model_config = {"env_prefix": "MOTOR_OCR_"}


settings = Settings()
