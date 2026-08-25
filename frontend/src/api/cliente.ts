/** Cliente HTTP contra la API del motor.
 *
 * La sesión viaja en una cookie HttpOnly, así que no hay token que guardar ni
 * cabecera que agregar: alcanza con `same-origin`, que en desarrollo funciona
 * porque Vite proxea la API bajo el mismo origen y en producción porque el SPA
 * lo sirve el propio FastAPI.
 */

export type ErrorApi = {
  /** Código estable del contrato, para ramificar sin leer el mensaje. */
  codigo: string
  /** Texto ya redactado para mostrarle a la persona. */
  mensaje: string
  estado: number
}

export class FalloApi extends Error {
  codigo: string
  estado: number

  constructor({ codigo, mensaje, estado }: ErrorApi) {
    super(mensaje)
    this.name = 'FalloApi'
    this.codigo = codigo
    this.estado = estado
  }
}

/** Normaliza las tres formas de error que devuelve FastAPI a una sola. */
function interpretarError(estado: number, cuerpo: unknown): ErrorApi {
  const detalle = (cuerpo as { detail?: unknown } | null)?.detail

  // 1. Nuestro sobre uniforme: { detail: { codigo, detail } }
  if (detalle && typeof detalle === 'object' && !Array.isArray(detalle)) {
    const d = detalle as { codigo?: string; detail?: string }
    return {
      codigo: d.codigo ?? 'error_desconocido',
      mensaje: d.detail ?? 'Algo salió mal',
      estado,
    }
  }

  // 2. Errores de validación de Pydantic: { detail: [{ loc, msg, ... }] }
  if (Array.isArray(detalle)) {
    const primero = detalle[0] as { msg?: string } | undefined
    return {
      codigo: 'datos_invalidos',
      mensaje: primero?.msg ?? 'Los datos enviados no son válidos',
      estado,
    }
  }

  // 3. HTTPException con texto suelto, o nada.
  return {
    codigo: 'error_desconocido',
    mensaje: typeof detalle === 'string' ? detalle : `Error ${estado}`,
    estado,
  }
}

type Opciones = {
  metodo?: 'GET' | 'POST' | 'DELETE' | 'PUT'
  cuerpo?: unknown
  parametros?: Record<string, string | number | boolean | undefined>
}

/** Toda la API vive bajo /api.
 *
 * El prefijo evita que las rutas del SPA y las de la API se pisen: sin el,
 * `/documentos` seria a la vez la pantalla y el endpoint, y el navegador
 * recibiria JSON en vez de la aplicacion.
 */
const BASE = '/api'

export async function pedir<T>(ruta: string, opciones: Opciones = {}): Promise<T> {
  const { metodo = 'GET', cuerpo, parametros } = opciones

  const url = new URL(BASE + ruta, window.location.origin)
  for (const [clave, valor] of Object.entries(parametros ?? {})) {
    // `undefined` significa "sin filtro": mandarlo como texto haría que el
    // backend filtre por la cadena "undefined".
    if (valor !== undefined && valor !== '') url.searchParams.set(clave, String(valor))
  }

  let respuesta: Response
  try {
    respuesta = await fetch(url, {
      method: metodo,
      credentials: 'same-origin',
      headers: cuerpo === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    })
  } catch {
    throw new FalloApi({
      codigo: 'sin_conexion',
      mensaje: 'No se pudo contactar al motor. ¿Está corriendo la API?',
      estado: 0,
    })
  }

  if (respuesta.status === 204) return undefined as T

  const texto = await respuesta.text()
  const cuerpoJson = texto ? JSON.parse(texto) : null

  if (!respuesta.ok) throw new FalloApi(interpretarError(respuesta.status, cuerpoJson))

  return cuerpoJson as T
}

/** Un 401 no es un error a mostrar: es "todavía no entraste". */
export function esNoAutenticado(error: unknown): boolean {
  return error instanceof FalloApi && error.estado === 401
}

/** Sube un archivo. Va aparte de `pedir` porque el cuerpo es multipart y no JSON. */
export async function subir<T>(
  ruta: string,
  archivo: File,
  campos: Record<string, string> = {},
): Promise<T> {
  const formulario = new FormData()
  formulario.append('file', archivo)
  for (const [clave, valor] of Object.entries(campos)) formulario.append(clave, valor)

  let respuesta: Response
  try {
    // Sin Content-Type a mano: el navegador tiene que ponerlo con el boundary.
    respuesta = await fetch(BASE + ruta, {
      method: 'POST',
      credentials: 'same-origin',
      body: formulario,
    })
  } catch {
    throw new FalloApi({
      codigo: 'sin_conexion',
      mensaje: 'No se pudo contactar al motor. ¿Está corriendo la API?',
      estado: 0,
    })
  }

  const texto = await respuesta.text()
  const cuerpo = texto ? JSON.parse(texto) : null

  if (!respuesta.ok) throw new FalloApi(interpretarError(respuesta.status, cuerpo))

  return cuerpo as T
}

/** Descarga un archivo de la API y dispara el guardado en el navegador.
 *
 * No alcanza con un `<a href>`: la ruta necesita la cookie de sesión y devuelve
 * un 404 si el documento no es del usuario, así que hay que pedirla por fetch
 * para poder mostrar el error en vez de abrir una pestaña con un JSON de error.
 */
export async function descargar(ruta: string, nombreSugerido: string): Promise<void> {
  let respuesta: Response
  try {
    respuesta = await fetch(BASE + ruta, { credentials: 'same-origin' })
  } catch {
    throw new FalloApi({
      codigo: 'sin_conexion',
      mensaje: 'No se pudo contactar al motor. ¿Está corriendo la API?',
      estado: 0,
    })
  }

  if (!respuesta.ok) {
    const texto = await respuesta.text()
    throw new FalloApi(interpretarError(respuesta.status, texto ? JSON.parse(texto) : null))
  }

  // El nombre real lo manda el servidor en Content-Disposition; el sugerido es
  // el respaldo para cuando la cabecera no viaja.
  const disposicion = respuesta.headers.get('content-disposition') ?? ''
  const coincidencia = disposicion.match(/filename="([^"]+)"/)
  const nombre = coincidencia ? coincidencia[1] : nombreSugerido

  const blob = await respuesta.blob()
  const url = URL.createObjectURL(blob)
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = nombre
  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()
  // Liberar en el mismo tick cancela la descarga en algunos navegadores.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
