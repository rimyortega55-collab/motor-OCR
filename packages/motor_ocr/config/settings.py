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
    # El valor del producto es la precisión de la corrección, así que por defecto
    # se usa el modelo más capaz. La diferencia frente a modelos más baratos es de
    # centavos por documento (ver pruebas/estimar_costo_escalacion.py) y se puede
    # cambiar sin tocar código con MOTOR_OCR_MODELO_ESCALACION.
    modelo_escalacion: str = "claude-opus-5"
    # Micro-segmentos por debajo de esta confianza se escalan al LLM (Cola 1)
    umbral_escalacion_micro_segmento: float = 0.6
    # Techo de gasto en LLM por documento. Un PDF con mucho ruido puede generar
    # cientos de micro-segmentos de baja confianza, y sin tope cada uno se
    # convierte en una llamada paga sin que nadie lo haya decidido. Al llegar al
    # tope el resto queda para revisión humana, que es la degradación honesta:
    # no se inventa contenido ni se sigue gastando en silencio.
    tope_gasto_documento_usd: float = 1.0

    model_config = {"env_prefix": "MOTOR_OCR_"}


settings = Settings()
