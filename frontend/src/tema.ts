/** Preferencia de tema, con tres estados y no dos.
 *
 * "Sistema" existe porque es lo que la persona ya eligió una vez en su sistema
 * operativo: un toggle de dos posiciones obliga a repetir esa decisión acá y,
 * peor, la congela — si después cambia el modo del sistema, la app se queda en
 * el que quedó pegado. Con tres estados el default no decide nada por su cuenta
 * y elegir explícito sigue siendo un clic.
 *
 * El tema oscuro es el que vive en `:root` a secas (ver estilos.css), así que
 * "oscuro" es ausencia de atributo y sólo "claro" escribe `data-theme`.
 */

export type Preferencia = 'sistema' | 'claro' | 'oscuro'

export const PREFERENCIAS: { valor: Preferencia; nombre: string }[] = [
  { valor: 'sistema', nombre: 'Sistema' },
  { valor: 'claro', nombre: 'Claro' },
  { valor: 'oscuro', nombre: 'Oscuro' },
]

export const CLAVE_TEMA = 'motor-ocr:tema'

const CONSULTA_CLARO = '(prefers-color-scheme: light)'

function esPreferencia(valor: unknown): valor is Preferencia {
  return valor === 'sistema' || valor === 'claro' || valor === 'oscuro'
}

/** Lee la preferencia guardada. `localStorage` puede tirar excepción —modo
 * privado, cookies de terceros bloqueadas—, y quedarse sin tema por eso sería
 * absurdo: ante cualquier falla, "sistema". */
export function leerPreferencia(): Preferencia {
  try {
    const guardada = window.localStorage.getItem(CLAVE_TEMA)
    if (esPreferencia(guardada)) return guardada
  } catch {
    /* sin almacenamiento: se usa el default */
  }
  return 'sistema'
}

export function guardarPreferencia(preferencia: Preferencia): void {
  try {
    window.localStorage.setItem(CLAVE_TEMA, preferencia)
  } catch {
    /* la elección vale para esta sesión aunque no se pueda persistir */
  }
}

/** Resuelve la preferencia contra el sistema y la escribe en el `<html>`. */
export function aplicarTema(preferencia: Preferencia): void {
  const claro =
    preferencia === 'claro' ||
    (preferencia === 'sistema' && window.matchMedia(CONSULTA_CLARO).matches)

  if (claro) document.documentElement.setAttribute('data-theme', 'light')
  else document.documentElement.removeAttribute('data-theme')
}

/** Avisa cuando cambia el tema del sistema, para que "sistema" siga al sistema
 * en vivo y no sólo al cargar la página. Devuelve la baja de la suscripción. */
export function escucharSistema(alCambiar: () => void): () => void {
  const consulta = window.matchMedia(CONSULTA_CLARO)
  consulta.addEventListener('change', alCambiar)
  return () => consulta.removeEventListener('change', alCambiar)
}
