"""Contratos de entrada/salida entre capas (no son el Bloque/Documento final).

Corresponden a los bloques "Contrato de salida" de cada capa en
.contexto/03-capas-pipeline.md.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from .block import EngineOcr
from .document import Costo, Inconsistencia


class PerfilContenido(BaseModel):
    texto_ratio: float
    formula_ratio: float
    tabla_ratio: float
    figura_ratio: float


class TriageResult(BaseModel):
    """Salida de Capa 1, por página."""

    pagina: int
    origen: str  # "nativo_digital" | "escaneado"
    perfil_contenido: PerfilContenido
    dpi_objetivo: int
    requiere_ocr: bool
    fuentes_detectadas: list[str] = Field(default_factory=list)


class MicroSegmentoOcr(BaseModel):
    tipo: str
    contenido: str
    engine_usado: EngineOcr
    confianza_engine: float
    confianza_estructural: float


class BlockOcrResult(BaseModel):
    """Salida de Capa 3, por bloque."""

    id: UUID
    contenido: str
    micro_segmentos: list[MicroSegmentoOcr] = Field(default_factory=list)
    confianza_global: float
    requiere_escalacion: bool


class BloqueCorregido(BaseModel):
    id: UUID
    contenido_normalizado: str
    reparaciones_aplicadas: list[str] = Field(default_factory=list)


class DocumentPostCorrection(BaseModel):
    """Salida de Capa 4."""

    bloques_corregidos: list[BloqueCorregido] = Field(default_factory=list)
    inconsistencias_detectadas: list[Inconsistencia] = Field(default_factory=list)
    bloques_pendientes_escalacion: list[UUID] = Field(default_factory=list)


class EscalationResult(BaseModel):
    """Salida de Capa 5."""

    cola_origen: str  # "micro_segmento" | "inconsistencia_documental"
    contenido_final: str
    confianza_llm: float
    requiere_revision_humana: bool
    costo: Costo
    razon_escalacion: str
