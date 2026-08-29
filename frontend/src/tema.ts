/** Preferencia de tema: clara u oscura.
 *
 * El tema oscuro es el que vive en `:root` a secas (ver estilos.css), así que
 * "oscuro" es ausencia de atributo y sólo "claro" escribe `data-theme`.
 *
 * La primera visita arranca en el tema que la persona tiene puesto en su
 * sistema operativo. No es una tercera opción del control —no hay modo
 * "sistema", y en cuanto toca el toggle la elección manda para siempre—, es
 * sólo de dónde sale la posición inicial en vez de imponer una a ciegas.
 */

export type Preferencia = 'claro' | 'oscuro'

export const PREFERENCIAS: { valor: Preferencia; nombre: string }[] = [
  { valor: 'claro', nombre: 'Claro' },
  { valor: 'oscuro', nombre: 'Oscuro' },
]

export const CLAVE_TEMA = 'motor-ocr:tema'

function esPreferencia(valor: unknown): valor is Preferencia {
  return valor === 'claro' || valor === 'oscuro'
}

/** La preferencia guardada; si no hay ninguna, la del sistema.
 *
 * `localStorage` puede tirar excepción —modo privado, almacenamiento
 * bloqueado—, y quedarse sin tema por eso sería absurdo: ante cualquier falla
 * se cae al tema oscuro, que es el de `:root`.
 */
export function leerPreferencia(): Preferencia {
  try {
    const guardada = window.localStorage.getItem(CLAVE_TEMA)
    if (esPreferencia(guardada)) return guardada
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'claro' : 'oscuro'
  } catch {
    return 'oscuro'
  }
}

export function guardarPreferencia(preferencia: Preferencia): void {
  try {
    window.localStorage.setItem(CLAVE_TEMA, preferencia)
  } catch {
    /* la elección vale para esta sesión aunque no se pueda persistir */
  }
}

export function aplicarTema(preferencia: Preferencia): void {
  if (preferencia === 'claro') document.documentElement.setAttribute('data-theme', 'light')
  else document.documentElement.removeAttribute('data-theme')
}
