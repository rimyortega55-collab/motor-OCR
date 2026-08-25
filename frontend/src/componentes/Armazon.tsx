/** Layout autenticado: barra lateral y guard de sesión.
 *
 * El guard vive acá y no en cada ruta para que exista un solo lugar donde se
 * decide si hay sesión: repartir esa decisión es lo que hace que una pantalla se
 * escape sin protección.
 */

import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'

import { useSalir, useSesion } from '../api/consultas'
import { esNoAutenticado } from '../api/cliente'
import {
  IconoAlerta,
  IconoDocumento,
  IconoGrafico,
  IconoDeslizadores,
  IconoLlave,
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
  const { data: usuario, isPending, error } = useSesion()
  const salir = useSalir()
  const ubicacion = useLocation()

  if (isPending) return <Cargando />

  if (esNoAutenticado(error) || !usuario) {
    // `state` guarda a dónde quería ir, para volver ahí después de entrar.
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
          <NavLink to="/cuenta" className={({ isActive }) => (isActive ? 'activo' : '')}>
            <IconoLlave /> Cuenta y API
          </NavLink>
        </nav>

        <div className="pie-lateral">
          <div className="columna" style={{ gap: 12 }}>
            <div className="columna" style={{ gap: 2 }}>
              <span style={{ fontSize: 13 }}>{usuario.nombre}</span>
              <span className="etiqueta">plan {usuario.plan}</span>
            </div>
            <button
              type="button"
              className="boton boton-chico"
              onClick={() => salir.mutate()}
              disabled={salir.isPending}
            >
              <IconoSalir tam={14} />
              {salir.isPending ? 'Saliendo…' : 'Salir'}
            </button>
          </div>
        </div>
      </aside>

      <main className="contenido">
        <Outlet />
      </main>
    </div>
  )
}
