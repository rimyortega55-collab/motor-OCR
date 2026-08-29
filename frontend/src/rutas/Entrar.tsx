/** Clave de acceso de la instancia.
 *
 * Sin cuentas: esta pantalla no es un login personal, es la clave única que el
 * operador de la instancia definió con `MOTOR_OCR_CLAVE_ACCESO` para no dejarla
 * completamente abierta en una red. Si no configuró ninguna, `useEstadoAcceso`
 * devuelve `desbloqueado: true` de entrada y nadie llega a ver esta pantalla.
 */

import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { FalloApi } from '../api/cliente'
import { useDesbloquear, useEstadoAcceso } from '../api/consultas'
import { IconoAlerta, IconoDocumento, IconoTilde } from '../componentes/Iconos'

export default function Entrar() {
  const [clave, setClave] = useState('')

  const { data: acceso } = useEstadoAcceso()
  const navegar = useNavigate()
  const ubicacion = useLocation()
  const destino = (ubicacion.state as { destino?: string } | null)?.destino ?? '/documentos'

  const desbloquear = useDesbloquear()
  const fallo = desbloquear.error as FalloApi | null

  // Ya está desbloqueada: no tiene sentido quedarse en esta pantalla.
  if (acceso && acceso.desbloqueado) return <Navigate to={destino} replace />

  function enviar(evento: React.FormEvent) {
    evento.preventDefault()
    desbloquear.mutate(clave, { onSuccess: () => navegar(destino, { replace: true }) })
  }

  return (
    <div className="portada">
      <section className="panel-marca">
        <div className="fila" style={{ gap: 10 }}>
          <IconoDocumento tam={20} />
          <strong>motor-OCR</strong>
        </div>

        <div className="columna" style={{ gap: 14 }}>
          <span className="etiqueta">Motor de OCR</span>
          <h1>OCR para documentos matemáticos, con la revisión humana incluida.</h1>
        </div>

        <p>
          Siete capas deterministas: triage, segmentación, OCR especializado por tipo de
          bloque, corrección, escalación selectiva a un modelo y feedback loop de umbrales.
          Sólo hace falta revisar lo que el motor no pudo resolver.
        </p>

        <ul className="lista-tilde">
          {[
            'Fórmulas a LaTeX con pix2tex, tablas con docTR',
            'El modelo sólo entra en lo ambiguo — costo medido por bloque',
            'Salida indexable como grafo de bloques',
          ].map((texto) => (
            <li key={texto}>
              <span className="tilde">
                <IconoTilde tam={13} />
              </span>
              <span>{texto}</span>
            </li>
          ))}
        </ul>

        {/* AGPL-3.0 exige ofrecer el código fuente a quien interactúa con la
            instancia por red (§13), y esta pantalla es lo primero que ve
            cualquiera que no llegó a desbloquearla. */}
        <a
          href="https://github.com/rimyortega55-collab/motor-OCR"
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 12.5 }}
        >
          Código fuente (AGPL-3.0)
        </a>
      </section>

      <section className="panel-formulario">
        <form className="formulario" onSubmit={enviar}>
          <div className="columna" style={{ gap: 5 }}>
            <h1>Clave de acceso</h1>
            <span className="apagado chico">
              Esta instancia está protegida. Pedile la clave a quien la administra.
            </span>
          </div>

          {fallo && (
            <div className="aviso aviso-error" role="alert">
              <IconoAlerta />
              <span>{fallo.message}</span>
            </div>
          )}

          <label className="campo">
            <span className="etiqueta">Clave</span>
            <input
              type="password"
              value={clave}
              onChange={(e) => setClave(e.target.value)}
              autoComplete="current-password"
              autoFocus
              required
            />
          </label>

          <button type="submit" className="boton boton-primario" disabled={desbloquear.isPending}>
            {desbloquear.isPending ? 'Verificando…' : 'Entrar'}
          </button>
        </form>
      </section>
    </div>
  )
}
