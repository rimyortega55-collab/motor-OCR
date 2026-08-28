/** Hooks de TanStack Query. Toda la comunicación con la API pasa por acá. */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { descargar, esNoAutenticado, pedir, subir } from './cliente'
import type {
  ActualizacionMotorIA,
  Bloque,
  ClaveAccesoRotada,
  ConfiguracionModeloMatematico,
  ConfiguracionMotorIA,
  ConfiguracionProcesamiento,
  EstadoAcceso,
  EstadoClaveAcceso,
  FormatoExport,
  ModoMotor,
  PedidoTraduccion,
  Recomendaciones,
  ResultadoAplicar,
  ResumenAdmin,
  TerminoSugerido,
  Traduccion,
  Umbrales,
  Decision,
  DocumentoResumen,
  EstadoProceso,
  PaginaInfo,
  ResultadoDecision,
  FiltrosDocumentos,
  Pagina,
  TrabajoEncolado,
} from './tipos'

export const claves = {
  acceso: ['acceso'] as const,
  documentos: (filtros: FiltrosDocumentos) => ['documentos', filtros] as const,
  estado: (id: string) => ['documento-estado', id] as const,
  cola: (id: string) => ['cola', id] as const,
  bloque: (doc: string, id: string) => ['bloque', doc, id] as const,
  bloquesPagina: (doc: string, pagina: number) => ['bloques-pagina', doc, pagina] as const,
  paginas: (id: string) => ['paginas', id] as const,
  umbrales: ['umbrales'] as const,
  recomendaciones: ['umbrales', 'recomendaciones'] as const,
  traducciones: (id: string) => ['traducciones', id] as const,
  glosario: (id: string) => ['glosario', id] as const,
  motorIA: ['admin', 'motor-ia'] as const,
  resumenAdmin: ['admin', 'resumen'] as const,
  claveAcceso: ['admin', 'clave-acceso'] as const,
  procesamiento: ['admin', 'procesamiento'] as const,
  modeloMatematico: ['admin', 'modelo-matematico'] as const,
}

// ============================================================================
// ACCESO
// ============================================================================

/** Sin cuentas: sólo hay que saber si esta instancia pide clave y si ya se
 * destrabó. Sin `MOTOR_OCR_CLAVE_ACCESO` en el servidor, esto siempre da
 * `desbloqueado: true` y la pantalla de clave no llega a mostrarse. */
export function useEstadoAcceso() {
  return useQuery({
    queryKey: claves.acceso,
    queryFn: () => pedir<EstadoAcceso>('/acceso'),
    // Un 401 no debería pasar acá — este endpoint es público — pero si el
    // servidor cambia de idea, reintentarlo sólo demora la pantalla.
    retry: (intentos, error) => !esNoAutenticado(error) && intentos < 2,
    staleTime: 5 * 60 * 1000,
  })
}

export function useDesbloquear() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (clave: string) =>
      pedir<EstadoAcceso>('/acceso', { metodo: 'POST', cuerpo: { clave } }),
    onSuccess: (estado) => cliente.setQueryData(claves.acceso, estado),
  })
}

export function useSalir() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: () => pedir<void>('/salir', { metodo: 'POST' }),
    // Se limpia todo y no sólo el acceso: cualquier dato en caché quedó
    // obsoleto apenas se cierra el acceso a la instancia.
    onSuccess: () => cliente.clear(),
  })
}

// ============================================================================
// DOCUMENTOS
// ============================================================================

export function useDocumentos(filtros: FiltrosDocumentos) {
  return useInfiniteQuery({
    queryKey: claves.documentos(filtros),
    queryFn: ({ pageParam }) =>
      pedir<Pagina<DocumentoResumen>>('/documentos', {
        parametros: {
          limite: filtros.limite ?? 25,
          estado: filtros.estado,
          buscar: filtros.buscar,
          necesita_revision: filtros.necesita_revision,
          cursor: pageParam,
        },
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (ultima) => ultima.siguiente_cursor ?? undefined,
    // Mientras algo esté en cola o procesándose, la lista se refresca sola
    // para que la fila pase a "completado" sin que haya que recargar la
    // página; cada fila en curso ya sondea su propio progreso por separado
    // (`useEstadoDocumento`), esto es sólo lo que hace falta para que el
    // estado general de la fila (y sus columnas de páginas/bloques) también
    // se ponga al día.
    refetchInterval: (consulta) => {
      const enCurso = consulta.state.data?.pages.some((p) =>
        p.items.some((d) => d.estado === 'procesando' || d.estado === 'en_cola'),
      )
      return enCurso ? 3000 : false
    },
  })
}

export function useProcesar() {
  const cliente = useQueryClient()
  return useMutation({
    // `paginas` viaja vacío cuando se quiere el documento entero; el servidor lo
    // interpreta como "todas" y evita recortar el PDF sin necesidad. `dpi`
    // vacío o "auto" deja el DPI adaptativo del triage, como siempre.
    mutationFn: ({
      archivo,
      paginas,
      dpi,
      idioma_original,
      modo_motor,
    }: {
      archivo: File
      paginas?: string
      dpi?: string
      idioma_original?: string
      modo_motor?: ModoMotor
    }) =>
      subir<TrabajoEncolado>('/procesar', archivo, {
        ...(paginas ? { paginas } : {}),
        ...(dpi ? { dpi } : {}),
        ...(idioma_original ? { idioma_original } : {}),
        // Sin mandarlo, el servidor procesa en híbrido: es el default de
        // siempre y no hace falta que la interfaz lo repita.
        ...(modo_motor && modo_motor !== 'hibrido' ? { modo_motor } : {}),
      }),
    // El documento aparece en la lista apenas se encola, en estado "en cola".
    onSuccess: () => cliente.invalidateQueries({ queryKey: ['documentos'] }),
  })
}

/** Sondea el progreso mientras el documento se procesa, y para al terminar. */
export function useEstadoDocumento(id: string | null) {
  return useQuery({
    queryKey: claves.estado(id ?? ''),
    queryFn: () => pedir<EstadoProceso>(`/documentos/${id}/estado`),
    enabled: id !== null,
    refetchInterval: (consulta) => {
      const estado = consulta.state.data?.estado
      // Dos segundos alcanzan para que la barra se vea viva sin castigar a la
      // base; cuando el documento termina no hay nada más que preguntar.
      return estado === 'completado' || estado === 'error' ? false : 2000
    },
  })
}

// ============================================================================
// REVISIÓN
// ============================================================================

/** La cola: los bloques pendientes, lo peor primero. */
export function useCola(documentoId: string) {
  return useQuery({
    queryKey: claves.cola(documentoId),
    queryFn: () =>
      pedir<Pagina<Bloque>>(`/documentos/${documentoId}/bloques`, {
        parametros: { estado_revision: 'pendiente', orden: 'confianza', limite: 200 },
      }),
  })
}

/** Un bloque con todo: micro-segmentos y corrección del modelo. */
export function useBloque(documentoId: string, bloqueId: string | null) {
  return useQuery({
    queryKey: claves.bloque(documentoId, bloqueId ?? ''),
    queryFn: () => pedir<Bloque>(`/documentos/${documentoId}/bloques/${bloqueId}`),
    enabled: bloqueId !== null,
  })
}

/** Los bloques de una página, para dibujar el overlay completo. */
export function useBloquesDePagina(documentoId: string, pagina: number | null) {
  return useQuery({
    queryKey: claves.bloquesPagina(documentoId, pagina ?? -1),
    queryFn: () =>
      pedir<Pagina<Bloque>>(`/documentos/${documentoId}/bloques`, {
        parametros: { pagina: pagina ?? 0, limite: 200 },
      }),
    enabled: pagina !== null,
  })
}

export function usePaginas(documentoId: string) {
  return useQuery({
    queryKey: claves.paginas(documentoId),
    queryFn: () =>
      pedir<{ total_paginas: number; paginas: PaginaInfo[] }>(
        `/documentos/${documentoId}/paginas`,
      ),
    // El PDF no cambia: no hay motivo para volver a pedir esto.
    staleTime: Infinity,
  })
}

export function useDecidir(documentoId: string) {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (decision: {
      bloque_id: string
      decision: Decision
      contenido_final: string
      confianza_usuario: number
      comentarios?: string
    }) =>
      pedir<ResultadoDecision>(`/revision/${documentoId}/decision`, {
        metodo: 'POST',
        cuerpo: decision,
      }),
    onSuccess: () => {
      cliente.invalidateQueries({ queryKey: claves.cola(documentoId) })
      cliente.invalidateQueries({ queryKey: ['documentos'] })
      cliente.invalidateQueries({ queryKey: ['bloques-pagina', documentoId] })
    },
  })
}

// ============================================================================
// UMBRALES
// ============================================================================

export function useUmbrales() {
  return useQuery({
    queryKey: claves.umbrales,
    queryFn: () => pedir<Umbrales>('/umbrales'),
  })
}

export function useGuardarUmbrales() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (cambios: Partial<Omit<Umbrales, 'actualizado_en'>>) =>
      pedir<Umbrales>('/umbrales', { metodo: 'PUT', cuerpo: cambios }),
    onSuccess: (datos) => {
      cliente.setQueryData(claves.umbrales, datos)
      // Las recomendaciones se calculan contra los umbrales vigentes.
      cliente.invalidateQueries({ queryKey: claves.recomendaciones })
    },
  })
}

export function useRecomendaciones() {
  return useQuery({
    queryKey: claves.recomendaciones,
    queryFn: () => pedir<Recomendaciones>('/umbrales/recomendaciones'),
  })
}

export function useAplicarRecomendaciones() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (clavesAplicar: string[]) =>
      pedir<ResultadoAplicar>('/umbrales/aplicar', {
        metodo: 'POST',
        cuerpo: { claves: clavesAplicar },
      }),
    onSuccess: (datos) => {
      cliente.setQueryData(claves.umbrales, datos.umbrales)
      cliente.invalidateQueries({ queryKey: claves.recomendaciones })
    },
  })
}

// ============================================================================
// EXPORTACIÓN
// ============================================================================

const EXTENSION: Record<FormatoExport, string> = {
  latex: 'tex',
  markdown: 'md',
  ipynb: 'ipynb',
  graphify: 'json',
}

export function useExportar() {
  return useMutation({
    mutationFn: ({
      documentoId,
      titulo,
      formato,
      idioma,
    }: {
      documentoId: string
      titulo: string
      formato: FormatoExport
      /** Sin idioma se descarga el original. */
      idioma?: string
    }) => {
      const base = titulo.replace(/\.pdf$/i, '') || 'documento'
      const sufijo = idioma ? `.${idioma}` : ''
      const parametro = idioma ? `&idioma=${encodeURIComponent(idioma)}` : ''
      return descargar(
        `/documentos/${documentoId}/export?formato=${formato}${parametro}`,
        `${base}${sufijo}.${EXTENSION[formato]}`,
      )
    },
  })
}

// ============================================================================
// BORRADO
// ============================================================================

export function useEliminarDocumento() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (documentoId: string) =>
      pedir<void>(`/documentos/${documentoId}`, { metodo: 'DELETE' }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: ['documentos'] }),
  })
}

// ============================================================================
// TRADUCCIÓN
// ============================================================================

export function useTraducciones(documentoId: string) {
  return useQuery({
    queryKey: claves.traducciones(documentoId),
    queryFn: () => pedir<Traduccion[]>(`/documentos/${documentoId}/traducciones`),
    // Mientras alguna esté en curso conviene sondear; traducir son minutos.
    refetchInterval: (consulta) => {
      const datos = consulta.state.data
      const enCurso = datos?.some((t) => t.estado === 'en_cola' || t.estado === 'traduciendo')
      return enCurso ? 3000 : false
    },
  })
}

/** Términos frecuentes del documento, para fijar antes de traducir. */
export function useSugerenciasGlosario(documentoId: string, activo: boolean) {
  return useQuery({
    queryKey: claves.glosario(documentoId),
    queryFn: () =>
      pedir<{ sugerencias: TerminoSugerido[] }>(
        `/documentos/${documentoId}/glosario/sugerencias`,
      ),
    enabled: activo,
  })
}

export function usePedirTraduccion(documentoId: string) {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (pedido: PedidoTraduccion) =>
      pedir<Traduccion>(`/documentos/${documentoId}/traducciones`, {
        metodo: 'POST',
        cuerpo: pedido,
      }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: claves.traducciones(documentoId) }),
  })
}

export function useBorrarTraduccion(documentoId: string) {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (idioma: string) =>
      pedir<void>(`/documentos/${documentoId}/traducciones/${encodeURIComponent(idioma)}`, {
        metodo: 'DELETE',
      }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: claves.traducciones(documentoId) }),
  })
}

// ============================================================================
// ADMINISTRACIÓN
// ============================================================================

export function useResumenAdmin() {
  return useQuery({
    queryKey: claves.resumenAdmin,
    queryFn: () => pedir<ResumenAdmin>('/admin/resumen'),
  })
}

export function useConfiguracionMotorIA() {
  return useQuery({
    queryKey: claves.motorIA,
    queryFn: () => pedir<ConfiguracionMotorIA>('/admin/motor-ia'),
  })
}

export function useGuardarMotorIA() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (cambios: ActualizacionMotorIA) =>
      pedir<ConfiguracionMotorIA>('/admin/motor-ia', { metodo: 'PUT', cuerpo: cambios }),
    onSuccess: (datos) => cliente.setQueryData(claves.motorIA, datos),
  })
}

/** Cuántos documentos procesa el pipeline a la vez, ahora mismo. */
export function useConfiguracionProcesamiento() {
  return useQuery({
    queryKey: claves.procesamiento,
    queryFn: () => pedir<ConfiguracionProcesamiento>('/admin/procesamiento'),
  })
}

/** Sube o baja el paralelismo en caliente. Lo que ya estaba corriendo o
 * esperando lugar bajo el límite anterior termina igual. */
export function useGuardarProcesamiento() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (max_paralelo: number) =>
      pedir<ConfiguracionProcesamiento>('/admin/procesamiento', {
        metodo: 'PUT',
        cuerpo: { max_paralelo },
      }),
    onSuccess: (datos) => cliente.setQueryData(claves.procesamiento, datos),
  })
}

/** Qué checkpoint de pix2tex reconoce las fórmulas, y cuáles hay para elegir. */
export function useModeloMatematico() {
  return useQuery({
    queryKey: claves.modeloMatematico,
    queryFn: () => pedir<ConfiguracionModeloMatematico>('/admin/modelo-matematico'),
  })
}

/** Cambia el checkpoint en caliente. `null` vuelve a los pesos pre-entrenados.
 * Rige para lo que se suba de acá en más: un documento a mitad del pipeline
 * termina con el modelo que ya tenía cargado. */
export function useGuardarModeloMatematico() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (checkpoint: string | null) =>
      pedir<ConfiguracionModeloMatematico>('/admin/modelo-matematico', {
        metodo: 'PUT',
        cuerpo: { checkpoint },
      }),
    onSuccess: (datos) => cliente.setQueryData(claves.modeloMatematico, datos),
  })
}

/** Estado de la clave de acceso de la instancia (nunca la trae en claro). */
export function useClaveAcceso() {
  return useQuery({
    queryKey: claves.claveAcceso,
    queryFn: () => pedir<EstadoClaveAcceso>('/admin/clave-acceso'),
  })
}

/** Genera una clave nueva y cierra las sesiones ya abiertas — incluida la
 * propia: el próximo pedido detrás de `exigir_acceso` da 401. A propósito no
 * se invalida acá la query de `acceso`: haría que `Armazon`/`Guard` manden a
 * la pantalla de entrada antes de que la persona llegue a copiar la clave que
 * esta misma respuesta muestra una única vez. La sesión igual se corta sola
 * en el próximo pedido protegido (por ejemplo, al navegar). */
export function useRotarClaveAcceso() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: () => pedir<ClaveAccesoRotada>('/admin/clave-acceso/rotar', { metodo: 'POST' }),
    onSuccess: (datos) => cliente.setQueryData(claves.claveAcceso, datos),
  })
}

/** Quita la clave administrada desde el panel (vuelve al entorno, si hay algo
 * ahí configurado) y cierra las sesiones ya abiertas, incluida la propia. */
export function useRevocarClaveAcceso() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: () => pedir<void>('/admin/clave-acceso', { metodo: 'DELETE' }),
    onSuccess: () => {
      cliente.invalidateQueries({ queryKey: claves.claveAcceso })
      cliente.invalidateQueries({ queryKey: claves.acceso })
    },
  })
}
