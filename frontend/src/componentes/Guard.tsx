/** Guard de acceso sin barra lateral.
 *
 * El visor de revisión ocupa la pantalla entera —cola, página y panel de
 * decisión no entran con una barra lateral al costado—, pero necesita la misma
 * protección que el resto. Esto es lo que `Armazon` hace antes de dibujar su
 * layout, sin el layout.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { esNoAutenticado } from '../api/cliente'
import { useEstadoAcceso } from '../api/consultas'

export default function Guard() {
  const { data: acceso, isPending, error } = useEstadoAcceso()
  const ubicacion = useLocation()

  if (isPending) {
    return (
      <div style={{ padding: 40, display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 420 }}>
        <div className="esqueleto" style={{ width: '40%', height: 20 }} />
        <div className="esqueleto" style={{ width: '85%' }} />
      </div>
    )
  }

  if (esNoAutenticado(error) || (acceso && !acceso.desbloqueado)) {
    return <Navigate to="/entrar" replace state={{ destino: ubicacion.pathname }} />
  }

  return <Outlet />
}
