/** Pantalla para lo que todavía no se puede construir.
 *
 * Existe para que la navegación no mienta: el ítem está en el menú porque la
 * pantalla está diseñada, y acá se dice exactamente qué falta del backend en vez
 * de mostrar una maqueta con datos inventados.
 */

import { IconoAlerta } from '../componentes/Iconos'

type Props = {
  titulo: string
  descripcion: string
  bloqueadoPor: string[]
  paso: string
}

export default function Pendiente({ titulo, descripcion, bloqueadoPor, paso }: Props) {
  return (
    <>
      <div className="cabecera-pagina">
        <h1>{titulo}</h1>
        <span className="pildora pildora-alerta">pendiente</span>
      </div>

      <div className="tarjeta" style={{ padding: '30px 32px', maxWidth: 640 }}>
        <div className="columna" style={{ gap: 18 }}>
          <p className="apagado" style={{ margin: 0 }}>{descripcion}</p>

          <div className="columna" style={{ gap: 9 }}>
            <span className="etiqueta">Falta en la API</span>
            {bloqueadoPor.map((endpoint) => (
              <div
                key={endpoint}
                className="fila"
                style={{
                  gap: 10,
                  padding: '9px 12px',
                  border: '1px solid var(--linea)',
                  borderRadius: 'var(--radio-chico)',
                  background: 'var(--superficie-2)',
                }}
              >
                <span style={{ color: 'var(--alerta)', display: 'flex' }}>
                  <IconoAlerta tam={14} />
                </span>
                <code style={{ fontSize: 12.5 }}>{endpoint}</code>
              </div>
            ))}
          </div>

          <span className="chico apagado" style={{ borderTop: '1px solid var(--linea)', paddingTop: 14 }}>
            {paso} · el detalle está en <code>docs/CONTRATO_API_FRONTEND.md</code> y el
            wireframe de esta pantalla, en <code>design/wireframes/</code>.
          </span>
        </div>
      </div>
    </>
  )
}
