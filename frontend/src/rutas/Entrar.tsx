/** Entrar y crear cuenta.
 *
 * Los dos modos comparten pantalla porque comparten casi todo: cambia un campo y
 * el destino del envío. Separarlos en dos rutas duplicaría el panel de marca y
 * el manejo de errores sin ganar nada.
 */

import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { FalloApi } from '../api/cliente'
import { useEntrar, useRegistrar, useSesion } from '../api/consultas'
import { IconoAlerta, IconoDocumento, IconoLlave } from '../componentes/Iconos'

const LARGO_MINIMO = 12

type Modo = 'entrar' | 'registro'

/** La clave recién creada se muestra una vez y no vuelve nunca. */
function ClaveNueva({ clave, alSeguir }: { clave: string; alSeguir: () => void }) {
  const [copiada, setCopiada] = useState(false)

  return (
    <div className="formulario">
      <div className="columna" style={{ gap: 6 }}>
        <h1>Tu cuenta está lista</h1>
        <p className="apagado chico" style={{ margin: 0 }}>
          Ésta es tu primera API key. Es la única vez que se muestra: en la base sólo queda
          su hash, así que no hay forma de recuperarla.
        </p>
      </div>

      <div className="aviso aviso-acento" style={{ flexDirection: 'column', gap: 10 }}>
        <span className="etiqueta" style={{ color: 'var(--acento)' }}>
          <IconoLlave tam={13} /> Guardala ahora
        </span>
        <code
          style={{
            fontSize: 12.5,
            wordBreak: 'break-all',
            background: 'var(--superficie)',
            border: '1px solid var(--acento-linea)',
            borderRadius: 'var(--radio-chico)',
            padding: '10px 12px',
          }}
        >
          {clave}
        </code>
        <button
          type="button"
          className="boton boton-chico"
          onClick={() => {
            navigator.clipboard?.writeText(clave).then(
              () => setCopiada(true),
              () => setCopiada(false),
            )
          }}
        >
          {copiada ? 'Copiada' : 'Copiar'}
        </button>
      </div>

      <button type="button" className="boton boton-primario" onClick={alSeguir}>
        Ya la guardé, entrar
      </button>
    </div>
  )
}

export default function Entrar() {
  const [modo, setModo] = useState<Modo>('entrar')
  const [nombre, setNombre] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [claveNueva, setClaveNueva] = useState<string | null>(null)

  const { data: usuario } = useSesion()
  const navegar = useNavigate()
  const ubicacion = useLocation()
  const destino = (ubicacion.state as { destino?: string } | null)?.destino ?? '/documentos'

  const entrar = useEntrar()
  const registrar = useRegistrar()
  const enCurso = entrar.isPending || registrar.isPending
  const fallo = (entrar.error ?? registrar.error) as FalloApi | null

  // Ya hay sesión y todavía no hay una clave que mostrar: no tiene sentido
  // quedarse en esta pantalla.
  if (usuario && !claveNueva) return <Navigate to={destino} replace />

  function enviar(evento: React.FormEvent) {
    evento.preventDefault()

    if (modo === 'entrar') {
      entrar.mutate({ email, password }, { onSuccess: () => navegar(destino, { replace: true }) })
    } else {
      registrar.mutate(
        { nombre, email, password },
        { onSuccess: ({ api_key }) => setClaveNueva(api_key) },
      )
    }
  }

  function cambiarModo(nuevo: Modo) {
    setModo(nuevo)
    entrar.reset()
    registrar.reset()
  }

  const passwordCorta = modo === 'registro' && password.length > 0 && password.length < LARGO_MINIMO

  return (
    <div className="portada">
      <section className="panel-marca">
        <div className="fila" style={{ gap: 10 }}>
          <IconoDocumento tam={20} />
          <strong>motor-OCR</strong>
        </div>

        <h1>OCR para documentos matemáticos, con la revisión humana incluida.</h1>

        <p>
          Siete capas deterministas: triage, segmentación, OCR especializado por tipo de
          bloque, corrección, escalación selectiva al modelo y feedback loop de umbrales.
          Vos sólo revisás lo que el motor no pudo resolver.
        </p>

        <ul className="columna" style={{ gap: 10, listStyle: 'none', padding: 0, margin: 0 }}>
          {[
            'Fórmulas a LaTeX con pix2tex, tablas con docTR',
            'El modelo sólo entra en lo ambiguo — costo medido por bloque',
            'Salida indexable como grafo de bloques',
          ].map((texto, i) => (
            <li key={texto} className="fila" style={{ gap: 11 }}>
              <span
                className="num"
                style={{
                  flex: '0 0 auto',
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  border: '1px solid #6b655c',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 11,
                }}
              >
                {i + 1}
              </span>
              <span style={{ fontSize: 13.5, color: '#d6d0c6' }}>{texto}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel-formulario">
        {claveNueva ? (
          <ClaveNueva clave={claveNueva} alSeguir={() => navegar('/documentos', { replace: true })} />
        ) : (
          <form className="formulario" onSubmit={enviar}>
            <div className="columna" style={{ gap: 5 }}>
              <h1>{modo === 'entrar' ? 'Entrar' : 'Crear cuenta'}</h1>
              <span className="apagado chico">
                Sesión de navegador · la API key es para máquinas
              </span>
            </div>

            {fallo && (
              <div className="aviso aviso-error" role="alert">
                <IconoAlerta />
                <span>{fallo.message}</span>
              </div>
            )}

            {modo === 'registro' && (
              <label className="campo">
                <span className="etiqueta">Nombre</span>
                <input
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  autoComplete="name"
                  required
                />
              </label>
            )}

            <label className="campo">
              <span className="etiqueta">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </label>

            <label className="campo">
              <span className="etiqueta">Contraseña</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={modo === 'entrar' ? 'current-password' : 'new-password'}
                minLength={modo === 'registro' ? LARGO_MINIMO : undefined}
                required
              />
              {modo === 'registro' && (
                <span className="ayuda" style={{ color: passwordCorta ? 'var(--alerta)' : undefined }}>
                  Mínimo {LARGO_MINIMO} caracteres.
                  {passwordCorta && ` Te faltan ${LARGO_MINIMO - password.length}.`}
                </span>
              )}
            </label>

            <button type="submit" className="boton boton-primario" disabled={enCurso}>
              {enCurso
                ? 'Un momento…'
                : modo === 'entrar'
                  ? 'Entrar'
                  : 'Crear cuenta y generar mi primera API key'}
            </button>

            <div className="fila" style={{ justifyContent: 'center', gap: 6 }}>
              <span className="apagado chico">
                {modo === 'entrar' ? '¿No tenés cuenta?' : '¿Ya tenés cuenta?'}
              </span>
              <button
                type="button"
                onClick={() => cambiarModo(modo === 'entrar' ? 'registro' : 'entrar')}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  font: 'inherit',
                  fontSize: 12.5,
                  color: 'var(--acento)',
                  cursor: 'pointer',
                }}
              >
                {modo === 'entrar' ? 'Crear una' : 'Entrar'}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  )
}
