/** Hooks de TanStack Query. Toda la comunicación con la API pasa por acá. */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { descargar, esNoAutenticado, pedir, subir } from './cliente'
import type {
  ApiKey,
  ApiKeyCreada,
  Consumo,
  Bloque,
  FormatoExport,
  Recomendaciones,
  ResultadoAplicar,
  Umbrales,
  Decision,
  DocumentoResumen,
  EstadoProceso,
  PaginaInfo,
  ResultadoDecision,
  FiltrosDocumentos,
  Pagina,
  TrabajoEncolado,
  Usuario,
} from './tipos'

export const claves = {
  yo: ['yo'] as const,
  apiKeys: ['api-keys'] as const,
  consumo: ['consumo'] as const,
  documentos: (filtros: FiltrosDocumentos) => ['documentos', filtros] as const,
  estado: (id: string) => ['documento-estado', id] as const,
  cola: (id: string) => ['cola', id] as const,
  bloque: (doc: string, id: string) => ['bloque', doc, id] as const,
  bloquesPagina: (doc: string, pagina: number) => ['bloques-pagina', doc, pagina] as const,
  paginas: (id: string) => ['paginas', id] as const,
  umbrales: ['umbrales'] as const,
  recomendaciones: ['umbrales', 'recomendaciones'] as const,
}

// ============================================================================
// SESIÓN
// ============================================================================

export function useSesion() {
  return useQuery({
    queryKey: claves.yo,
    queryFn: () => pedir<Usuario>('/auth/yo'),
    // Un 401 es la respuesta correcta cuando no hay sesión, no una falla de red:
    // reintentarlo sólo demora la pantalla de login.
    retry: (intentos, error) => !esNoAutenticado(error) && intentos < 2,
    staleTime: 5 * 60 * 1000,
  })
}

export function useEntrar() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (credenciales: { email: string; password: string }) =>
      pedir<{ usuario: Usuario }>('/auth/login', {
        metodo: 'POST',
        cuerpo: credenciales,
      }),
    onSuccess: ({ usuario }) => cliente.setQueryData(claves.yo, usuario),
  })
}

export function useRegistrar() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (alta: { nombre: string; email: string; password: string }) =>
      pedir<{ usuario: Usuario; api_key: string }>('/auth/registro', {
        metodo: 'POST',
        cuerpo: alta,
      }),
    onSuccess: ({ usuario }) => cliente.setQueryData(claves.yo, usuario),
  })
}

export function useSalir() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: () => pedir<void>('/auth/logout', { metodo: 'POST' }),
    // Se limpia todo y no sólo la sesión: cualquier dato en caché es del
    // usuario que se acaba de ir.
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
  })
}

export function useProcesar() {
  const cliente = useQueryClient()
  return useMutation({
    // `paginas` viaja vacío cuando se quiere el documento entero; el servidor lo
    // interpreta como "todas" y evita recortar el PDF sin necesidad.
    mutationFn: ({ archivo, paginas }: { archivo: File; paginas?: string }) =>
      subir<TrabajoEncolado>('/procesar', archivo, paginas ? { paginas } : {}),
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
// API KEYS
// ============================================================================

export function useApiKeys() {
  return useQuery({
    queryKey: claves.apiKeys,
    queryFn: () => pedir<ApiKey[]>('/api-keys'),
  })
}

export function useCrearApiKey() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (nombre: string) =>
      pedir<ApiKeyCreada>('/api-keys', { metodo: 'POST', cuerpo: { nombre } }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: claves.apiKeys }),
  })
}

export function useRevocarApiKey() {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => pedir<void>(`/api-keys/${id}`, { metodo: 'DELETE' }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: claves.apiKeys }),
  })
}

// ============================================================================
// CONSUMO
// ============================================================================

export function useConsumo() {
  return useQuery({
    queryKey: claves.consumo,
    queryFn: () => pedir<Consumo>('/consumo'),
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
    }: {
      documentoId: string
      titulo: string
      formato: FormatoExport
    }) => {
      const base = titulo.replace(/\.pdf$/i, '') || 'documento'
      return descargar(
        `/documentos/${documentoId}/export?formato=${formato}`,
        `${base}.${EXTENSION[formato]}`,
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
