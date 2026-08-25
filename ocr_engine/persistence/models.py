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

    # Contraseña para la sesión del navegador. Nula en usuarios creados por CLI,
    # que sólo operan con API key. A diferencia de la clave de API, acá sí hace
    # falta un hash lento (scrypt): una contraseña elegida por una persona es
    # atacable por diccionario.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    # Legado: las claves viven ahora en la tabla api_keys, para que un usuario
    # pueda tener varias y revocar una sin perder las demás. Estas dos columnas
    # quedan sólo como origen de la migración y no se escriben más.
    api_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    api_key_prefijo: Mapped[str | None] = mapped_column(String(12))

    plan: Mapped[str] = mapped_column(String(50), default="libre")
    activo: Mapped[bool] = mapped_column(default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    documentos: Mapped[list["DocumentoAlmacenado"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    costos: Mapped[list["CostoRegistrado"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    sesiones: Mapped[list["Sesion"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    """Clave de API de un usuario. Sólo se guarda su hash.

    Una fila por clave y no una columna en `usuarios` para que se pueda revocar
    la clave de una máquina sin dejar sin acceso a las demás, que es lo que pasa
    cuando la identidad del usuario y su credencial son la misma cosa.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    nombre: Mapped[str] = mapped_column(String(120), default="")
    # SHA-256 y no un hash lento a propósito: la clave es un secreto aleatorio de
    # 256 bits, no hay diccionario que probar, y se valida en cada request.
    clave_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Prefijo visible para que el usuario reconozca su clave en una lista.
    prefijo: Mapped[str] = mapped_column(String(12), nullable=False)

    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    ultimo_uso_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    usuario: Mapped[Usuario] = relationship(back_populates="api_keys")

    @property
    def activa(self) -> bool:
        return self.revocada_en is None


class Sesion(Base):
    """Sesión de navegador. El token viaja en una cookie HttpOnly.

    Se guardan en base y no como un JWT firmado porque así se pueden revocar:
    cerrar sesión o desactivar la cuenta corta el acceso en el acto, mientras que
    un token firmado sigue siendo válido hasta que expira.
    """

    __tablename__ = "sesiones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    expira_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ultimo_uso_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    usuario: Mapped[Usuario] = relationship(back_populates="sesiones")


class DocumentoAlmacenado(Base):
    """Documento procesado. Reemplaza el dict en memoria de la Capa 7."""

    __tablename__ = "documentos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    # en_cola | procesando | completado | error
    estado: Mapped[str] = mapped_column(String(30), default="en_cola")

    # Progreso por capa mientras el pipeline corre, para que la interfaz pueda
    # mostrar en qué va en vez de un spinner indefinido: procesar 200 páginas
    # tarda minutos y hasta ahora no había nada que mirar.
    progreso: Mapped[dict | None] = mapped_column(JSON)
    # Se usa para detectar trabajos colgados: un worker que muere deja el
    # documento en "procesando" para siempre si nadie mira cuándo dio señales.
    latido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    # Ruta del PDF original, relativa a MOTOR_OCR_DATA_DIR. Se conserva porque el
    # visor de revisión necesita renderizar páginas a demanda; antes se borraba
    # apenas terminaba el pipeline y no había forma de volver a mirarlas.
    ruta_pdf: Mapped[str | None] = mapped_column(String(500))

    # Qué páginas del archivo original se procesaron, 0-based. Nulo = todas.
    # Al procesar una selección, el PDF se recorta y la numeración interna queda
    # re-basada; esto es lo que permite que la interfaz muestre el número de
    # página que el usuario reconoce de su documento.
    paginas_origen: Mapped[list | None] = mapped_column(JSON)

    usuario: Mapped[Usuario] = relationship(back_populates="documentos")
    costos: Mapped[list["CostoRegistrado"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )
    decisiones: Mapped[list["DecisionAlmacenada"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )
    bloques: Mapped[list["BloqueAlmacenado"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )


class BloqueAlmacenado(Base):
    """Un bloque del documento, tal como quedó al final del pipeline.

    Una fila por bloque y no un JSON gigante en `documentos.resultado` porque la
    cola de revisión filtra y pagina sobre decenas de miles de bloques:
    deserializar el documento entero en cada request no escala.
    """

    __tablename__ = "bloques"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    documento_id: Mapped[str] = mapped_column(
        ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    pagina: Mapped[int] = mapped_column(Integer, default=0)
    orden_lectura: Mapped[int] = mapped_column(Integer, default=0)
    tipo: Mapped[str] = mapped_column(String(30))
    origen_contenido: Mapped[str] = mapped_column(String(20))

    # Normalizado a la caja de la página: cuatro flotantes en [0, 1]. Ver
    # ocr_engine/segmentation/bbox.py — así el frontend puede dibujar el overlay
    # sin saber el DPI ni de qué capa vino el bloque.
    bbox: Mapped[dict] = mapped_column(JSON)

    confianza_layout: Mapped[float] = mapped_column(Float, default=0.0)
    confianza_global: Mapped[float | None] = mapped_column(Float)

    texto_plano: Mapped[str | None] = mapped_column(Text)
    latex: Mapped[str | None] = mapped_column(Text)
    # Lo que dejó la revisión humana. Nulo mientras nadie lo tocó.
    contenido_final: Mapped[str | None] = mapped_column(Text)

    micro_segmentos: Mapped[list | None] = mapped_column(JSON)
    escalacion: Mapped[dict | None] = mapped_column(JSON)

    # pendiente | resuelto | no_requiere
    estado_revision: Mapped[str] = mapped_column(String(20), default="no_requiere")

    documento: Mapped["DocumentoAlmacenado"] = relationship(back_populates="bloques")


# El visor pide los bloques de una página en orden de lectura, y la cola pide los
# pendientes ordenados por confianza. Sin estos índices, las dos consultas
# recorren la tabla entera del documento.
Index("ix_bloques_pagina", BloqueAlmacenado.documento_id, BloqueAlmacenado.pagina,
      BloqueAlmacenado.orden_lectura)
Index("ix_bloques_revision", BloqueAlmacenado.documento_id,
      BloqueAlmacenado.estado_revision, BloqueAlmacenado.confianza_global)


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


class UmbralesUsuario(Base):
    """Umbrales de confianza de un usuario (Capa 7).

    Antes vivían en `umbrales_config.json`, escrito en ruta relativa: se perdía
    en cada despliegue y, al no tener dueño, un usuario le cambiaba los umbrales
    a todos los demás. Es la misma trampa que ya se había corregido para los
    documentos y los costos.

    Los tres ámbitos se guardan como JSON en vez de una columna por umbral
    porque las claves son los tipos de bloque del motor, que todavía cambian:
    agregar un tipo no debería pedir una migración de esquema.
    """

    __tablename__ = "umbrales"

    usuario_id: Mapped[str] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )

    capa3: Mapped[dict] = mapped_column(JSON, default=dict)
    capa4: Mapped[dict] = mapped_column(JSON, default=dict)
    globales: Mapped[dict] = mapped_column(JSON, default=dict)

    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )

    usuario: Mapped[Usuario] = relationship()


class TraduccionDocumento(Base):
    """Un pedido de traducción de un documento a un idioma, con su contexto.

    Una fila por (documento, idioma): el mismo documento puede traducirse a
    varios idiomas sin reprocesar el OCR, que es la razón por la que traducir se
    hace al exportar y no dentro del pipeline.

    El contexto lo decide el usuario y es lo que separa una traducción técnica
    utilizable de una literal: describir que es un libro de álgebra de posgrado
    cambia cómo se traduce "ring", y un glosario propio evita que el mismo término
    aparezca de tres formas distintas a lo largo de 200 páginas.
    """

    __tablename__ = "traducciones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    documento_id: Mapped[str] = mapped_column(
        ForeignKey("documentos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    idioma: Mapped[str] = mapped_column(String(12), nullable=False)

    # Qué es el documento y para quién. Viaja en cada llamada al modelo.
    descripcion: Mapped[str | None] = mapped_column(Text)
    # "academico" | "accesible"
    tono: Mapped[str] = mapped_column(String(20), default="academico")
    # {"eigenvalue": "autovalor", ...}. El motor propone y el usuario corrige.
    glosario: Mapped[dict] = mapped_column(JSON, default=dict)
    # Qué se traduce: {"paginas": [0,1,2], "tipos": ["parrafo","teorema"]}.
    # Vacío = todo lo traducible.
    seleccion: Mapped[dict] = mapped_column(JSON, default=dict)

    # en_cola | traduciendo | completada | error
    estado: Mapped[str] = mapped_column(String(20), default="en_cola")
    bloques_totales: Mapped[int] = mapped_column(Integer, default=0)
    bloques_traducidos: Mapped[int] = mapped_column(Integer, default=0)
    costo_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)

    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )

    documento: Mapped["DocumentoAlmacenado"] = relationship()


class TraduccionBloque(Base):
    """El texto traducido de un bloque.

    Tabla aparte y no una columna en `bloques` porque un bloque tiene tantas
    traducciones como idiomas se hayan pedido. Guardarlo por bloque además deja
    rehacer la traducción de uno solo cuando el usuario corrige su texto, sin
    volver a pagar las otras 27 000.
    """

    __tablename__ = "traducciones_bloque"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    traduccion_id: Mapped[str] = mapped_column(
        ForeignKey("traducciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bloque_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    contenido: Mapped[str] = mapped_column(Text)
    confianza: Mapped[float] = mapped_column(Float, default=0.0)
    # Lo que el revisor dejó, si tocó la traducción.
    contenido_final: Mapped[str | None] = mapped_column(Text)

    traduccion: Mapped[TraduccionDocumento] = relationship()


# El exportador pide todos los bloques de una traducción para recomponer el
# documento; sin índice recorre la tabla entera de todos los idiomas.
Index("ix_traduccion_bloque", TraduccionBloque.traduccion_id, TraduccionBloque.bloque_id)
