"""Tablas del motor: usuarios, documentos, costos y decisiones de revisión."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _ahora() -> datetime:
    """UTC con tzinfo: comparar fechas de instancias en distintas zonas si no, falla."""
    return datetime.now(timezone.utc)


class Usuario(Base):
    """Cliente del motor. La API key identifica y habilita la facturación."""

    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)

    # Sólo el hash: si se filtra la base, las claves siguen sin ser utilizables.
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Prefijo visible para que el usuario reconozca su clave en una lista.
    api_key_prefijo: Mapped[str] = mapped_column(String(12), nullable=False)

    plan: Mapped[str] = mapped_column(String(50), default="libre")
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    documentos: Mapped[list["DocumentoAlmacenado"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    costos: Mapped[list["CostoRegistrado"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class DocumentoAlmacenado(Base):
    """Documento procesado. Reemplaza el dict en memoria de la Capa 7."""

    __tablename__ = "documentos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    estado: Mapped[str] = mapped_column(String(30), default="procesando")
    total_paginas: Mapped[int] = mapped_column(Integer, default=0)
    total_bloques: Mapped[int] = mapped_column(Integer, default=0)
    inconsistencias: Mapped[int] = mapped_column(Integer, default=0)
    necesita_revision: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text)

    # Resultado completo serializado. JSON en vez de una tabla de bloques porque
    # la forma del bloque todavía cambia entre versiones del pipeline.
    resultado: Mapped[dict | None] = mapped_column(JSON)

    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )

    usuario: Mapped[Usuario] = relationship(back_populates="documentos")
    costos: Mapped[list["CostoRegistrado"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )
    decisiones: Mapped[list["DecisionAlmacenada"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )


class CostoRegistrado(Base):
    """Costo de una llamada al LLM (Capa 5), atribuido a usuario y documento.

    Sustituye a costo_escalaciones.jsonl, que se escribía en ruta relativa y por
    lo tanto se perdía en cada despliegue.
    """

    __tablename__ = "costos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usuario_id: Mapped[str | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    documento_id: Mapped[str | None] = mapped_column(
        ForeignKey("documentos.id", ondelete="CASCADE"), index=True
    )
    bloque_id: Mapped[str | None] = mapped_column(String(36))

    tipo_cola: Mapped[str] = mapped_column(String(50))
    modelo: Mapped[str] = mapped_column(String(100))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, default=0)
    costo_usd: Mapped[float] = mapped_column(Float, default=0.0)
    razon_escalacion: Mapped[str | None] = mapped_column(Text)

    registrado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, index=True
    )

    usuario: Mapped[Usuario | None] = relationship(back_populates="costos")
    documento: Mapped[DocumentoAlmacenado | None] = relationship(back_populates="costos")


# Facturar es sumar costos de un usuario en un rango de fechas; sin este índice
# esa consulta recorre la tabla entera.
Index("ix_costos_usuario_fecha", CostoRegistrado.usuario_id, CostoRegistrado.registrado_en)


class DecisionAlmacenada(Base):
    """Decisión de revisión humana (Capa 6), antes en decisiones_revision.jsonl."""

    __tablename__ = "decisiones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    documento_id: Mapped[str] = mapped_column(
        ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bloque_id: Mapped[str] = mapped_column(String(36), nullable=False)

    pagina: Mapped[int] = mapped_column(Integer, default=0)
    tipo_bloque: Mapped[str] = mapped_column(String(50))
    decision: Mapped[str] = mapped_column(String(30))
    contenido_original: Mapped[str | None] = mapped_column(Text)
    contenido_final: Mapped[str | None] = mapped_column(Text)
    confianza_engine: Mapped[float] = mapped_column(Float, default=0.0)
    confianza_usuario: Mapped[float] = mapped_column(Float, default=0.0)
    comentarios: Mapped[str | None] = mapped_column(Text)
    revisor: Mapped[str | None] = mapped_column(String(200))

    registrado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    documento: Mapped[DocumentoAlmacenado] = relationship(back_populates="decisiones")
