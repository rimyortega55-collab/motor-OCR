/** Tipos del contrato de API (docs/CONTRATO_API_FRONTEND.md).
 *
 * Escritos a mano y no generados del OpenAPI a propósito: mientras el contrato
 * se está negociando, tener los tipos acá deja ver de un vistazo qué se acordó.
 * Cuando el backend se estabilice conviene generarlos con openapi-typescript.
 */

export type Usuario = {
  id: string
  nombre: string
  email: string | null
  plan: string
  creado_en: string | null
}

export type ApiKey = {
  id: string
  nombre: string
  prefijo: string
  creada_en: string | null
  ultimo_uso_en: string | null
  revocada_en: string | null
}

/** Sólo en la respuesta de creación: la clave en claro no vuelve a aparecer. */
export type ApiKeyCreada = ApiKey & { api_key: string }

export type EstadoDocumento = 'en_cola' | 'procesando' | 'completado' | 'error'

export type DocumentoResumen = {
  documento_id: string
  titulo: string
  estado: EstadoDocumento
  total_paginas: number
  total_bloques: number
  inconsistencias: number
  necesita_revision: boolean
  creado_en: string | null
}

export type Pagina<T> = {
  items: T[]
  siguiente_cursor: string | null
  total: number
}

export type FiltrosDocumentos = {
  estado?: EstadoDocumento
  buscar?: string
  necesita_revision?: boolean
  limite?: number
}

export type EstadoCapa = 'pendiente' | 'en_curso' | 'completada' | 'omitida'

export type CapaProgreso = {
  capa: number
  nombre: 'triage' | 'segmentacion' | 'ocr' | 'correccion' | 'escalacion'
  estado: EstadoCapa
  detalle?: string
  progreso?: { hechos: number; total: number }
  detalle_engines?: Record<string, number>
}

export type EstadoProceso = {
  documento_id: string
  titulo: string
  estado: EstadoDocumento
  capa_actual: number | null
  capas: CapaProgreso[]
  total_paginas: number
  total_bloques: number
  costo_usd_parcial: number
  error: string | null
  actualizado_en: string | null
}

export type TrabajoEncolado = {
  documento_id: string
  estado: EstadoDocumento
  titulo: string
}

export type TipoBloque =
  | 'encabezado' | 'parrafo' | 'formula_inline' | 'formula_display' | 'tabla'
  | 'figura' | 'caption' | 'teorema' | 'lema' | 'proposicion' | 'definicion'
  | 'corolario' | 'demostracion' | 'nota_pie' | 'lista' | 'codigo' | 'ruido'

/** Normalizado a la caja de la página: cuatro fracciones en [0, 1]. */
export type Bbox = { x0: number; y0: number; x1: number; y1: number }

export type MicroSegmento = {
  tipo: string
  contenido: string
  engine_usado: 'easyocr' | 'pix2tex' | 'doctr' | 'tesseract'
  confianza_engine: number
  confianza_estructural: number
}

export type Escalacion = {
  requirio_escalacion: boolean
  cola_origen: string | null
  contenido_llm: string | null
  confianza_llm: number | null
  razon_escalacion: string | null
  requiere_revision_humana: boolean
  tokens_entrada?: number
  tokens_salida?: number
}

export type EstadoRevision = 'pendiente' | 'resuelto' | 'no_requiere'

export type Bloque = {
  id: string
  pagina: number
  orden_lectura: number
  tipo: TipoBloque
  origen_contenido: 'texto_nativo' | 'requiere_ocr'
  bbox: Bbox
  confianza_layout: number
  confianza_global: number | null
  texto_plano: string | null
  latex: string | null
  contenido_final: string | null
  estado_revision: EstadoRevision
  micro_segmentos?: MicroSegmento[]
  escalacion?: Escalacion | null
}

export type PaginaInfo = {
  pagina: number
  ancho_px: number
  alto_px: number
  dpi: number
  bloques: number
}

export type Decision = 'aceptar' | 'rechazar' | 'editar' | 'escalar'

export type ResultadoDecision = {
  decision_id: number
  siguiente_bloque_id: string | null
  pendientes: number
}

export type LimitesPlan = {
  paginas_mes: number | null
  gasto_llm_mes_usd: number | null
}

export type TotalesConsumo = {
  documentos: number
  paginas: number
  llamadas_llm: number
  tokens_entrada: number
  tokens_salida: number
  costo_llm_usd: number
}

export type DiaConsumo = {
  fecha: string
  micro_segmento_usd: number
  inconsistencia_documental_usd: number
}

export type ConsumoDocumento = {
  documento_id: string
  titulo: string
  llamadas: number
  tokens_entrada: number
  tokens_salida: number
  costo_usd: number
}

export type Consumo = {
  usuario: string
  plan: string
  desde: string
  hasta: string
  limites: LimitesPlan
  totales: TotalesConsumo
  serie_diaria: DiaConsumo[]
  por_documento: ConsumoDocumento[]
}

/** Los cuatro formatos de exportación. LaTeX y Markdown son los principales. */
export type FormatoExport = 'latex' | 'markdown' | 'ipynb' | 'graphify'

export type Umbrales = {
  capa3: Record<string, number>
  capa4: Record<string, number>
  globales: Record<string, number>
  actualizado_en: string | null
}

export type Recomendacion = {
  ambito: string
  clave: string
  actual: number
  propuesto: number
  confianza: number
  razon: string
  aplicable: boolean
}

export type Recomendaciones = {
  decisiones_analizadas: number
  recomendaciones: Recomendacion[]
}

export type ResultadoAplicar = {
  status: string
  razon?: string
  cambios_aplicados: number
  umbrales: Umbrales
  detalles?: { clave: string; de: number; a: number; razon: string }[]
  /** Viaja en null hasta que exista validación contra un lote real. */
  validacion: null
}

// ============================================================================
// TRADUCCIÓN
// ============================================================================

export type TerminoSugerido = {
  termino: string
  apariciones: number
  traduccion: string
}

export type SeleccionTraduccion = {
  paginas: number[]
  tipos: string[]
}

export type PedidoTraduccion = {
  idioma: string
  descripcion?: string
  tono?: 'academico' | 'accesible'
  glosario?: Record<string, string>
  seleccion?: SeleccionTraduccion
}

export type Traduccion = {
  id: string
  idioma: string
  descripcion: string
  tono: string
  glosario: Record<string, string>
  seleccion: Partial<SeleccionTraduccion>
  estado: 'en_cola' | 'traduciendo' | 'completada' | 'error'
  bloques_totales: number
  bloques_traducidos: number
  costo_usd: number
  error: string | null
}
