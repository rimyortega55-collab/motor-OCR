"""Tablas del motor: documentos, bloques, costos y decisiones de revisión.

Sin usuarios: el proyecto es open source y de un solo operador, así que no hay
cuentas, planes ni API keys — el que levanta la instancia es su único
"usuario", y todo lo que antes vivía por cuenta (umbrales, consumo) ahora es
una configuración global de la instancia, igual que `ConfiguracionMotorIA`.
"""

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


class DocumentoAlmacenado(Base):
    """Documento procesado. Reemplaza el dict en memoria de la Capa 7."""

    __tablename__ = "documentos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

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

    # Lo que declaró quien subió el documento al procesarlo. Es sólo metadato
    # -no cambia qué motor de OCR se usa- y sirve de default al abrir el
    # diálogo de traducción, para no ofrecer traducir al mismo idioma.
    idioma_original: Mapped[str | None] = mapped_column(String(20))

    # Con qué modo de Capa 3 se procesó: "hibrido" (motor determinista + modelo
    # de IA sólo en las fórmulas) o "solo_ia" (todos los bloques al modelo).
    # Se guarda por documento y no como configuración global porque cambia el
    # resultado: sin esto, dos documentos de la misma instancia con calidades
    # muy distintas no se podrían explicar.
    modo_motor: Mapped[str] = mapped_column(String(20), default="hibrido")

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
    # motor_ocr/segmentation/bbox.py — así el frontend puede dibujar el overlay
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
    """Costo de una llamada al LLM (Capa 5), atribuido al documento.

    Sustituye a costo_escalaciones.jsonl, que se escribía en ruta relativa y por
    lo tanto se perdía en cada despliegue.
    """

    __tablename__ = "costos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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

    documento: Mapped[DocumentoAlmacenado | None] = relationship(back_populates="costos")


# La serie de consumo agrupa por fecha en un rango; sin este índice esa
# consulta recorre la tabla entera.
Index("ix_costos_fecha", CostoRegistrado.registrado_en)


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


class UmbralesGlobales(Base):
    """Umbrales de confianza de la instancia (Capa 7).

    Fila única (id fijo "global"), como `ConfiguracionMotorIA`: sin cuentas, no
    hay "los umbrales de quién" — son los de esta instancia. Antes vivían en
    `umbrales_config.json`, escrito en ruta relativa y sin dueño, y después en
    una fila por usuario; ambas etapas se saltaban con este único juego.

    Los tres ámbitos se guardan como JSON en vez de una columna por umbral
    porque las claves son los tipos de bloque del motor, que todavía cambian:
    agregar un tipo no debería pedir una migración de esquema.
    """

    __tablename__ = "umbrales"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="global")

    capa3: Mapped[dict] = mapped_column(JSON, default=dict)
    capa4: Mapped[dict] = mapped_column(JSON, default=dict)
    globales: Mapped[dict] = mapped_column(JSON, default=dict)

    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )


class TraduccionDocumento(Base):
    """Un pedido de traducción de un documento a un idioma, con su contexto.

    Una fila por (documento, idioma): el mismo documento puede traducirse a
    varios idiomas sin reprocesar el OCR, que es la razón por la que traducir se
    hace al exportar y no dentro del pipeline.

    El contexto lo decide quien traduce y es lo que separa una traducción
    técnica utilizable de una literal: describir que es un libro de álgebra de
    posgrado cambia cómo se traduce "ring", y un glosario propio evita que el
    mismo término aparezca de tres formas distintas a lo largo de 200 páginas.
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
    # {"eigenvalue": "autovalor", ...}. El motor propone y se corrige a mano.
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
    rehacer la traducción de uno solo cuando se corrige el texto, sin volver a
    pagar las otras 27 000.
    """

    __tablename__ = "traducciones_bloque"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    traduccion_id: Mapped[str] = mapped_column(
        ForeignKey("traducciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bloque_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    contenido: Mapped[str] = mapped_column(Text)
    confianza: Mapped[float] = mapped_column(Float, default=0.0)
    # Lo que quedó tras la revisión, si se tocó la traducción.
    contenido_final: Mapped[str | None] = mapped_column(Text)

    traduccion: Mapped[TraduccionDocumento] = relationship()


# El exportador pide todos los bloques de una traducción para recomponer el
# documento; sin índice recorre la tabla entera de todos los idiomas.
Index("ix_traduccion_bloque", TraduccionBloque.traduccion_id, TraduccionBloque.bloque_id)


class ClaveAccesoInstancia(Base):
    """Clave de acceso de la instancia, cuando se administra desde el panel.

    Fila única (id fijo "global"), como `ConfiguracionMotorIA`. Empieza sin
    fila: en ese caso `acceso.py` sigue leyendo `MOTOR_OCR_CLAVE_ACCESO` del
    entorno, tal como antes de que existiera este panel. En cuanto se rota una
    clave por primera vez, esta fila pasa a mandar — eso es lo que permite
    rotarla o revocarla en caliente, algo que una variable de entorno no deja
    hacer sin reiniciar el proceso.
    """

    __tablename__ = "clave_acceso_instancia"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="global")
    clave: Mapped[str | None] = mapped_column(Text)
    rotada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConfiguracionProcesamiento(Base):
    """Cuántos documentos procesa el pipeline a la vez, para toda la instancia.

    Fila única (id fijo "global"), mismo patrón que `ClaveAccesoInstancia`.
    Vivía sólo en `MOTOR_OCR_PROCESAMIENTO_PARALELO`, fija al arrancar el
    proceso; ahora el panel la edita en caliente y esta fila es lo que
    sobrevive a un reinicio (`trabajos.aplicar_limite_paralelo` la aplica de
    nuevo al arrancar).
    """

    __tablename__ = "configuracion_procesamiento"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="global")
    max_paralelo: Mapped[int] = mapped_column(Integer, default=4)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )


class ConfiguracionMotorIA(Base):
    """Qué proveedor de IA usa la Capa 5 (escalación) para este despliegue.

    Fila única (id fijo "global"): quien se auto-hospeda el motor configura un
    solo proveedor para toda la instancia. Vivía sólo en variables de entorno
    (MOTOR_OCR_MODELO_ESCALACION y las del SDK de Anthropic), lo que obligaba a
    reiniciar el proceso para cambiar de proveedor o de clave; ahora el panel
    de administración la edita en caliente.

    La clave se guarda en claro porque el motor la necesita para llamar al
    proveedor en cada escalación, igual que hoy la lee de una variable de
    entorno sin cifrar; lo que sí protege este modelo es no devolverla nunca
    al frontend (ver `rutas_admin.py`).
    """

    __tablename__ = "configuracion_motor_ia"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="global")

    # anthropic | openai_compatible | local
    proveedor: Mapped[str] = mapped_column(String(30), default="anthropic")
    modelo: Mapped[str] = mapped_column(String(100), default="claude-opus-5")
    # Sólo aplica a openai_compatible: endpoint del proveedor (p. ej. la URL de
    # un gateway propio o de un servidor vLLM/Ollama con API compatible).
    base_url: Mapped[str | None] = mapped_column(String(500))
    api_key: Mapped[str | None] = mapped_column(Text)
    habilitado: Mapped[bool] = mapped_column(default=True)

    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )


class ConfiguracionModeloMatematico(Base):
    """Qué checkpoint de pix2tex usa la Capa 3 para reconocer fórmulas.

    Fila única (id fijo "global"), mismo patrón que `ConfiguracionProcesamiento`.
    `checkpoint` NULL significa "los pesos pre-entrenados que trae el paquete
    pix2tex"; si no, es el nombre de un `.pth` dentro de
    `MOTOR_OCR_CHECKPOINTS_DIR` salido del fine-tuning propio.

    Se guarda el **nombre de archivo** y no una ruta: la ruta sale siempre de
    resolverlo contra ese directorio (ver `pix2tex_engine.resolver_checkpoint`),
    así una fila vieja no puede hacer que el proceso cargue un `.pth` de
    cualquier lado del disco.
    """

    __tablename__ = "configuracion_modelo_matematico"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="global")
    checkpoint: Mapped[str | None] = mapped_column(String(255))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora, onupdate=_ahora
    )
