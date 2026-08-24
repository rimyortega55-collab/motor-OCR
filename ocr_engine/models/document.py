"""Documento, ZonaDPI, IndiceEstructural — nivel raíz del documento.

Corresponde 1:1 a la sección 1 de .contexto/05-esquema-metadata-bloque-ocr.md.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Origen(str, Enum):
    NATIVO_DIGITAL = "nativo_digital"
    ESCANEADO = "escaneado"
    MIXTO = "mixto"


class ZonaDpi(BaseModel):
    paginas: tuple[int, int]
    dpi: int
    perfil_dominante: str


class Costo(BaseModel):
    tokens_entrada: int = 0
    tokens_salida: int = 0
    modelo_usado: list[str] = Field(default_factory=list)


class EntradaIndice(BaseModel):
    numero: str
    titulo: str | None = None
    bloque_id: UUID | None = None
    bloque_id_inicio: UUID | None = None


class IndiceEstructural(BaseModel):
    capitulos: list[EntradaIndice] = Field(default_factory=list)
    teoremas: list[EntradaIndice] = Field(default_factory=list)
    lemas: list[str] = Field(default_factory=list)
    definiciones: list[str] = Field(default_factory=list)
    ecuaciones_numeradas: list[EntradaIndice] = Field(default_factory=list)


class Inconsistencia(BaseModel):
    tipo: str  # "numeracion_faltante" | "referencia_rota"
    detalle: str
    ubicacion_pagina: int


class Documento(BaseModel):
    documento_id: UUID = Field(default_factory=uuid4)
    titulo: str
    origen: Origen
    idioma_original: str
    idiomas_traduccion: list[str] = Field(default_factory=list)
    total_paginas: int
    zonas_dpi: list[ZonaDpi] = Field(default_factory=list)
    version_pipeline: str
    fecha_procesamiento: datetime = Field(default_factory=datetime.utcnow)
    costo_total: Costo = Field(default_factory=Costo)
    indice_estructural: IndiceEstructural = Field(default_factory=IndiceEstructural)
    inconsistencias_no_resueltas: list[Inconsistencia] = Field(default_factory=list)
