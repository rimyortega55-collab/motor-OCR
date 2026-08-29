/** Elección de tema, en el pie de la barra lateral. */

import { useEffect, useState } from 'react'

import {
  PREFERENCIAS,
  type Preferencia,
  aplicarTema,
  escucharSistema,
  guardarPreferencia,
  leerPreferencia,
} from '../tema'

export default function SelectorTema() {
  const [preferencia, setPreferencia] = useState<Preferencia>(leerPreferencia)

  // El tema ya lo dejó puesto el script de index.html antes del primer pintado;
  // esto lo vuelve a aplicar cuando cambia la elección, y mientras esté en
  // "sistema" sigue los cambios del sistema en vivo.
  useEffect(() => {
    aplicarTema(preferencia)
    if (preferencia !== 'sistema') return
    return escucharSistema(() => aplicarTema('sistema'))
  }, [preferencia])

  function elegir(valor: Preferencia) {
    setPreferencia(valor)
    guardarPreferencia(valor)
  }

  return (
    <div className="columna" style={{ gap: 6 }}>
      <span className="etiqueta">Tema</span>
      <div className="fila" style={{ gap: 5, flexWrap: 'wrap' }} role="group" aria-label="Tema">
        {PREFERENCIAS.map((opcion) => (
          <button
            key={opcion.valor}
            type="button"
            className={`pildora ${preferencia === opcion.valor ? 'pildora-activa' : ''}`}
            aria-pressed={preferencia === opcion.valor}
            onClick={() => elegir(opcion.valor)}
          >
            {opcion.nombre}
          </button>
        ))}
      </div>
    </div>
  )
}
