/** Constantes compartidas entre componentes. Separado de los componentes
 * mismos para no romper el fast-refresh (un archivo que sólo exporta
 * componentes se recarga en caliente; uno que mezcla componentes y
 * constantes, no). */

import type { ModoMotor } from './api/tipos'

/** Los dos modos de reconocimiento que ofrece la instancia, con la explicación
 * que se muestra al elegirlos. El texto está pensado para quien no programa:
 * dice qué gana y qué pierde con cada uno, no cómo está implementado. */
export const MODOS_MOTOR: {
  valor: ModoMotor
  nombre: string
  resumen: string
  detalle: string
}[] = [
  {
    valor: 'hibrido',
    nombre: 'Híbrido',
    resumen: 'Recomendado',
    detalle:
      'El motor lee el texto directamente del PDF —exacto y sin costo— y le pasa al modelo de IA sólo los recortes de fórmula. Es el modo más rápido y el más fiel en documentos con capa de texto.',
  },
  {
    valor: 'solo_ia',
    nombre: 'Sólo modelo de IA',
    resumen: 'Más lento',
    detalle:
      'Todos los bloques van al modelo de IA, incluida la prosa que el PDF ya traía escrita. Sirve para medir al modelo solo, o para PDFs cuya capa de texto está rota. Tarda bastante más y el modelo está afinado para fórmulas, no para párrafos.',
  },
]

/** Vocabulario de idiomas de la instancia: el mismo para "de qué idioma sale
 * el documento" (Subir) y "a qué idioma se traduce" (Traducir). */
export const IDIOMAS = ['español', 'inglés', 'portugués', 'francés', 'alemán', 'italiano']
