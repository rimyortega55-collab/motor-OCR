"""Bloque — nodo principal del grafo, y su taxonomía extendida de tipos.

Corresponde 1:1 a la sección 2 de .contexto/05-esquema-metadata-bloque-ocr.md
y a la taxonomía extendida definida en .contexto/03-capas-pipeline.md (Capa 2).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .document import Costo


class TipoBloque(str, Enum):
    ENCABEZADO = "encabezado"
    PARRAFO = "parrafo"
    FORMULA_INLINE = "formula_inline"
    FORMULA_DISPLAY = "formula_display"
    TABLA = "tabla"
    FIGURA = "figura"
    CAPTION = "caption"
    TEOREMA = "teorema"
    LEMA = "lema"
    PROPOSICION = "proposicion"
    DEFINICION = "definicion"
    COROLARIO = "corolario"
    DEMOSTRACION = "demostracion"
    NOTA_PIE = "nota_pie"
    LISTA = "lista"
    CODIGO = "codigo"
    RUIDO = "ruido"


class OrigenContenido(str, Enum):
    TEXTO_NATIVO = "texto_nativo"
    REQUIERE_OCR = "requiere_ocr"


class EngineOcr(str, Enum):
    EASYOCR = "easyocr"
    PIX2TEX = "pix2tex"
    DOCTR = "doctr"
    TESSERACT = "tesseract"


class MotorTraduccion(str, Enum):
    NLLB_200 = "nllb-200"
    OPUS_MT = "opus-mt"
    LLM = "llm"


class TipoRelacion(str, Enum):
    PROVES = "PROVES"
    USES_DEFINITION = "USES_DEFINITION"
    REFERENCES = "REFERENCES"
    CAPTION_OF = "CAPTION_OF"
    PART_OF = "PART_OF"
    CONTINUES = "CONTINUES"


class ColaOrigen(str, Enum):
    MICRO_SEGMENTO = "micro_segmento"
    INCONSISTENCIA_DOCUMENTAL = "inconsistencia_documental"


class IdentificadorSemantico(BaseModel):
    numero: str | None = None
    capitulo: str | None = None
    seccion: str | None = None


class Layout(BaseModel):
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    orden_lectura: int
    bloque_padre_id: UUID | None = None
    confianza_layout: float


class IpynbCell(BaseModel):
    cell_type: str  # "markdown" | "code"
    source: str


class Contenido(BaseModel):
    texto_plano: str | None = None
    latex: str | None = None
    markdown: str | None = None
    ipynb_cell: IpynbCell | None = None


class SegmentoCrudo(BaseModel):
    """Tramo de texto o fórmula detectado en Capa 2, previo a Capa 3.

    Puente entre `nativo_digital.py` (que ve los spans del PDF y puede ubicar
    una fórmula por fuente matemática o por tamaño/offset de super-/subíndice)
    y `enrutador.py` (que recorta esa región de la página renderizada y la
    manda a pix2tex). Sin este puente, la información geométrica de dónde está
    la fórmula se pierde en cuanto los spans se aplanan a `texto_plano`.
    """

    tipo: str  # "texto" | "formula"
    texto: str  # contenido nativo; en "formula" es el respaldo si pix2tex falla
    bbox: tuple[float, float, float, float] | None = None  # normalizado a la página, solo en "formula"


class MicroSegmento(BaseModel):
    tipo: str  # "texto" | "formula_inline"
    contenido: str
    engine_usado: EngineOcr
    confianza_engine: float
    confianza_estructural: float


class Ocr(BaseModel):
    micro_segmentos: list[MicroSegmento] = Field(default_factory=list)
    confianza_global: float | None = None


class Correccion(BaseModel):
    reparaciones_aplicadas: list[str] = Field(default_factory=list)
    diccionario_usado: str | None = None  # "general" | "tecnico_matematico"


class Escalacion(BaseModel):
    requirio_escalacion: bool = False
    cola_origen: ColaOrigen | None = None
    # Lo que devolvió el modelo, aparte del contenido del bloque. El panel de
    # revisión compara "lo que leyó el motor" contra "lo que corrigió el modelo";
    # sin guardar las dos versiones esa comparación no se puede mostrar.
    contenido_llm: str | None = None
    confianza_llm: float | None = None
    requiere_revision_humana: bool = False
    razon_escalacion: str | None = None
    costo: Costo = Field(default_factory=Costo)


class Traduccion(BaseModel):
    idioma: str
    contenido: str
    motor: MotorTraduccion
    confianza: float


class RelacionSaliente(BaseModel):
    tipo: TipoRelacion
    objetivo_id: UUID | None = None
    referencia_texto: str | None = None


class RelacionEntrante(BaseModel):
    tipo: TipoRelacion
    origen_id: UUID


class Relacion(BaseModel):
    salientes: list[RelacionSaliente] = Field(default_factory=list)
    entrantes: list[RelacionEntrante] = Field(default_factory=list)


class Provenance(BaseModel):
    creado_por_capa: str
    modificado_por_capas: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Bloque(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    documento_id: UUID
    pagina: int
    tipo: TipoBloque

    identificador_semantico: IdentificadorSemantico = Field(
        default_factory=IdentificadorSemantico
    )
    layout: Layout
    origen_contenido: OrigenContenido
    contenido: Contenido = Field(default_factory=Contenido)
    segmentos_capa2: list[SegmentoCrudo] = Field(default_factory=list)
    ocr: Ocr = Field(default_factory=Ocr)
    correccion: Correccion = Field(default_factory=Correccion)
    escalacion: Escalacion = Field(default_factory=Escalacion)
    traduccion: Traduccion | None = None
    relaciones: Relacion = Field(default_factory=Relacion)
    provenance: Provenance
