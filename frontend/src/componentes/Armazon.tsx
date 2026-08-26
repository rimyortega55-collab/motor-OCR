/** Layout principal: barra lateral y guard de acceso.
 *
 * El guard vive acá y no en cada ruta para que exista un solo lugar donde se
 * decide si hay acceso: repartir esa decisión es lo que hace que una pantalla
 * se escape sin protección.
 */

import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'

import { useEstadoAcceso, useSalir } from '../api/consultas'
import { esNoAutenticado } from '../api/cliente'
import {
  IconoAlerta,
  IconoDocumento,
  IconoEngranaje,
  IconoGrafico,
  IconoDeslizadores,
  IconoSalir,
  IconoSubir,
} from './Iconos'

function Cargando() {
  return (
    <div style={{ padding: 40, display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 420 }}>
      <div className="esqueleto" style={{ width: '40%', height: 20 }} />
      <div className="esqueleto" style={{ width: '85%' }} />
      <div className="esqueleto" style={{ width: '70%' }} />
    </div>
  )
}

export default function Armazon() {
  const { data: acceso, isPending, error } = useEstadoAcceso()
  const salir = useSalir()
  const ubicacion = useLocation()

  if (isPending) return <Cargando />

  if (esNoAutenticado(error) || (acceso && !acceso.desbloqueado)) {
    // `state` guarda a dónde quería ir, para volver ahí después de destrabarla.
    return <Navigate to="/entrar" replace state={{ destino: ubicacion.pathname }} />
  }

  if (error) {
    return (
      <div style={{ padding: 40, maxWidth: 520 }}>
        <div className="aviso aviso-error">
          <IconoAlerta />
          <span>{(error as Error).message}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="armazon">
      <aside className="barra-lateral">
        <div className="marca">
          <IconoDocumento tam={19} />
          <span>motor-OCR</span>
        </div>

        <nav className="menu">
          <NavLink to="/documentos" className={({ isActive }) => (isActive ? 'activo' : '')}>
            <IconoDocumento /> Documentos
          </NavLink>
          <NavLink to="/subir" className={({ isActive }) => (isActive ? 'activo' : '')}>
            <IconoSubir /> Subir y procesar
          </NavLink>
          <NavLink to="/consumo" className={({ isActive }) => (isActive ? 'activo' : '')}>
            <IconoGrafico /> Consumo
          </NavLink>
          <NavLink to="/umbrales" className={({ isActive }) => `pendiente ${isActive ? 'activo' : ''}`}>
            <IconoDeslizadores /> Umbrales
          </NavLink>
        </nav>

        <span className="etiqueta etiqueta-menu">Administración</span>
        <nav className="menu">
          <NavLink to="/admin" className={({ isActive }) => (isActive ? 'activo' : '')}>
            <IconoEngranaje /> Motor IA y resumen
          </NavLink>
        </nav>

        {acceso?.requiere_clave && (
          <div className="pie-lateral">
            <button
              type="button"
              className="boton boton-chico"
              onClick={() => salir.mutate()}
              disabled={salir.isPending}
            >
              <IconoSalir tam={14} />
              {salir.isPending ? 'Cerrando…' : 'Cerrar acceso'}
            </button>
          </div>
        )}
      </aside>

      <main className="contenido">
        <Outlet />
      </main>
    </div>
  )
}
