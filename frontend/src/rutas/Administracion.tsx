/** Panel de administración: resumen del despliegue y proveedor de IA.
 *
 * Existe porque el proyecto es open source y se auto-hospeda: quien lo levanta
 * necesita elegir de dónde sale la inteligencia de la Capa 5 sin editar
 * variables de entorno ni reiniciar el proceso. Sin cuentas no hay "quién puede
 * tocar esto": esta pantalla queda detrás del mismo acceso que el resto de la
 * instancia (la clave única, si el operador configuró una).
 */

import { useEffect, useState } from 'react'

import {
  useClaveAcceso,
  useConfiguracionMotorIA,
  useGuardarMotorIA,
  useResumenAdmin,
  useRevocarClaveAcceso,
  useRotarClaveAcceso,
} from '../api/consultas'
import { FalloApi } from '../api/cliente'
import type { ProveedorMotorIA } from '../api/tipos'
import { IconoAlerta, IconoLlave, IconoRobot } from '../componentes/Iconos'

const PROVEEDORES: { valor: ProveedorMotorIA; titulo: string; bajada: string }[] = [
  {
    valor: 'anthropic',
    titulo: 'API de Anthropic',
    bajada: 'La integración original: modelos Claude con visión, vía el SDK oficial.',
  },
  {
    valor: 'openai_compatible',
    titulo: 'Cualquier API compatible con OpenAI',
    bajada:
      'Por URL y clave: sirve para OpenAI, un gateway propio, o un servidor auto-hospedado (vLLM, Ollama, LM Studio...).',
  },
  {
    valor: 'local',
    titulo: 'Modelo local propio',
    bajada:
      'Pendiente: todavía no existe un modelo propio entrenado para OCR matemático. El motor sigue siendo el determinista de siempre — esto queda para cuando ese modelo exista.',
  },
]

function TarjetaKpi({ titulo, valor }: { titulo: string; valor: string | number }) {
  return (
    <div className="tarjeta kpi">
      <span className="etiqueta">{titulo}</span>
      <span className="valor num">{valor}</span>
    </div>
  )
}

function SeccionResumen() {
  const resumen = useResumenAdmin()

  return (
    <div className="columna" style={{ gap: 12 }}>
      <div className="columna" style={{ gap: 3 }}>
        <span className="etiqueta">Resumen del despliegue</span>
        <span className="chico apagado">Números de toda la instancia.</span>
      </div>

      {resumen.isPending ? (
        <div className="esqueleto" style={{ width: '50%', height: 60 }} />
      ) : resumen.error ? (
        <div className="aviso aviso-error">
          <IconoAlerta />
          <span>{(resumen.error as Error).message}</span>
        </div>
      ) : (
        <div className="rejilla-kpi">
          <TarjetaKpi titulo="Documentos procesados" valor={resumen.data?.documentos_totales ?? 0} />
          <TarjetaKpi
            titulo="Costo LLM acumulado"
            valor={`$${(resumen.data?.costo_llm_usd_total ?? 0).toFixed(4)}`}
          />
        </div>
      )}
    </div>
  )
}

/** Origen de la clave vigente, para que el operador sepa si tocar "revocar"
 * la apaga del todo o sólo la devuelve a lo que dice el entorno. */
const TEXTO_ORIGEN: Record<'panel' | 'entorno', string> = {
  panel: 'Rotada desde este panel.',
  entorno: 'Viene de MOTOR_OCR_CLAVE_ACCESO en el entorno del proceso.',
}

function SeccionClaveAcceso() {
  const estado = useClaveAcceso()
  const rotar = useRotarClaveAcceso()
  const revocar = useRevocarClaveAcceso()
  const [confirmandoRevocar, setConfirmandoRevocar] = useState(false)

  const claveNueva = rotar.data?.clave

  return (
    <div className="tarjeta" style={{ padding: '18px 20px' }}>
      <div className="columna" style={{ gap: 16 }}>
        <div className="columna" style={{ gap: 3 }}>
          <span className="etiqueta">
            <IconoLlave tam={13} /> Clave de acceso de la instancia
          </span>
          <span className="chico apagado">
            La clave única que pide la pantalla de entrada. Rotarla genera una nueva y cierra de
            inmediato cualquier sesión ya abierta en otros navegadores.
          </span>
        </div>

        {estado.error && (
          <div className="aviso aviso-error">
            <IconoAlerta />
            <span>{(estado.error as Error).message}</span>
          </div>
        )}

        {estado.isPending ? (
          <div className="esqueleto" style={{ width: '40%', height: 20 }} />
        ) : (
          <div className="fila" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            {estado.data?.requiere_clave ? (
              <span className="pildora pildora-acento">Instancia protegida</span>
            ) : (
              <span className="pildora">Instancia abierta — sin clave</span>
            )}
            {estado.data?.origen && (
              <span className="chico apagado">{TEXTO_ORIGEN[estado.data.origen]}</span>
            )}
            {estado.data?.rotada_en && (
              <span className="chico apagado">
                última rotación {new Date(estado.data.rotada_en).toLocaleString('es')}
              </span>
            )}
          </div>
        )}

        {claveNueva && (
          <div className="aviso aviso-acento columna" style={{ gap: 8, alignItems: 'stretch' }}>
            <span className="chico">
              Clave nueva — copiala ahora, no se vuelve a mostrar. Esta sesión también quedó
              invalidada: al navegar vas a tener que volver a entrar con ella.
            </span>
            <code
              className="mono chico"
              style={{
                padding: '8px 10px',
                background: 'var(--superficie)',
                border: '1px solid var(--linea)',
                borderRadius: 'var(--radio-chico)',
                wordBreak: 'break-all',
              }}
            >
              {claveNueva}
            </code>
          </div>
        )}

        {rotar.error && (
          <div className="aviso aviso-error">
            <IconoAlerta />
            <span>{(rotar.error as FalloApi).message}</span>
          </div>
        )}

        <div className="fila" style={{ gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="boton boton-primario"
            disabled={rotar.isPending}
            onClick={() => rotar.mutate()}
          >
            {rotar.isPending ? 'Rotando…' : 'Rotar clave'}
          </button>

          {estado.data?.requiere_clave &&
            (confirmandoRevocar ? (
              <div className="fila" style={{ gap: 6, alignItems: 'center' }}>
                <span className="chico apagado">
                  {estado.data.origen === 'entorno'
                    ? '¿Revocar? Vuelve a la clave del entorno.'
                    : '¿Revocar? La instancia queda abierta.'}
                </span>
                <button
                  type="button"
                  className="boton boton-chico boton-peligro"
                  disabled={revocar.isPending}
                  onClick={() => {
                    revocar.mutate()
                    setConfirmandoRevocar(false)
                  }}
                >
                  {revocar.isPending ? 'Revocando…' : 'Sí'}
                </button>
                <button
                  type="button"
                  className="boton boton-chico"
                  onClick={() => setConfirmandoRevocar(false)}
                >
                  No
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="boton boton-peligro"
                onClick={() => setConfirmandoRevocar(true)}
              >
                Revocar
              </button>
            ))}
        </div>

        {revocar.error && (
          <div className="aviso aviso-error">
            <IconoAlerta />
            <span>{(revocar.error as FalloApi).message}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function SeccionMotorIA() {
  const config = useConfiguracionMotorIA()
  const guardar = useGuardarMotorIA()

  const [proveedor, setProveedor] = useState<ProveedorMotorIA>('anthropic')
  const [modelo, setModelo] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [cargado, setCargado] = useState(false)

  useEffect(() => {
    if (config.data && !cargado) {
      setProveedor(config.data.proveedor)
      setModelo(config.data.modelo)
      setBaseUrl(config.data.base_url ?? '')
      setCargado(true)
    }
  }, [config.data, cargado])

  function guardarCambios(evento: React.FormEvent) {
    evento.preventDefault()
    guardar.mutate({
      proveedor,
      modelo: modelo.trim() || undefined,
      base_url: proveedor === 'openai_compatible' ? baseUrl.trim() || null : null,
      // Vacío = no tocar la clave guardada; así no hace falta reescribirla en
      // cada guardado sólo para cambiar el modelo.
      api_key: apiKey.trim() || undefined,
    })
    setApiKey('')
  }

  const esLocal = proveedor === 'local'

  return (
    <div className="tarjeta" style={{ padding: '18px 20px' }}>
      <form onSubmit={guardarCambios} className="columna" style={{ gap: 18 }}>
        <div className="fila" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div className="columna" style={{ gap: 3 }}>
            <span className="etiqueta">
              <IconoRobot tam={13} /> Proveedor de IA (Capa 5, escalación)
            </span>
            <span className="chico apagado">
              A dónde se manda un bloque cuando el OCR determinista no llega a la confianza mínima.
            </span>
          </div>
          {config.data?.actualizado_en && (
            <span className="chico apagado">
              editado {new Date(config.data.actualizado_en).toLocaleString('es')}
            </span>
          )}
        </div>

        {config.error && (
          <div className="aviso aviso-error">
            <IconoAlerta />
            <span>{(config.error as Error).message}</span>
          </div>
        )}

        <div className="columna" style={{ gap: 10 }}>
          {PROVEEDORES.map((p) => (
            <label
              key={p.valor}
              className="fila"
              style={{
                gap: 12,
                alignItems: 'flex-start',
                padding: '12px 14px',
                border: '1px solid var(--linea)',
                borderRadius: 'var(--radio-chico)',
                background: proveedor === p.valor ? 'var(--acento-tinte)' : 'transparent',
                cursor: 'pointer',
              }}
            >
              <input
                type="radio"
                name="proveedor"
                value={p.valor}
                checked={proveedor === p.valor}
                onChange={() => setProveedor(p.valor)}
                style={{ marginTop: 3 }}
              />
              <div className="columna" style={{ gap: 2 }}>
                <strong style={{ fontSize: 13.5 }}>{p.titulo}</strong>
                <span className="chico apagado">{p.bajada}</span>
              </div>
            </label>
          ))}
        </div>

        {esLocal ? (
          <div className="aviso">
            <IconoAlerta />
            <span className="chico">
              Con "modelo local" elegido, la escalación queda deshabilitada hasta que exista un
              modelo propio: los bloques de baja confianza van directo a revisión humana, sin
              gastar en ningún proveedor externo.
            </span>
          </div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: 14,
            }}
          >
            <label className="campo">
              <span className="etiqueta">Modelo</span>
              <input
                value={modelo}
                onChange={(e) => setModelo(e.target.value)}
                placeholder={proveedor === 'anthropic' ? 'claude-opus-5' : 'gpt-4o'}
              />
            </label>

            {proveedor === 'openai_compatible' && (
              <label className="campo">
                <span className="etiqueta">URL base</span>
                <input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://api.midominio.com/v1"
                />
              </label>
            )}

            <label className="campo">
              <span className="etiqueta">Clave de API</span>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  config.data?.api_key_configurada
                    ? `guardada, termina en ${config.data.api_key_sufijo}`
                    : 'sin configurar'
                }
              />
              <span className="ayuda">Se guarda en el servidor; nunca vuelve a mostrarse acá.</span>
            </label>
          </div>
        )}

        <div className="fila" style={{ gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="submit" className="boton boton-primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
          <span className="chico apagado">Se aplica de inmediato, sin reiniciar el servidor.</span>
        </div>

        {guardar.error && (
          <div className="aviso aviso-error">
            <IconoAlerta />
            <span>{(guardar.error as FalloApi).message}</span>
          </div>
        )}
        {guardar.isSuccess && (
          <span className="chico" style={{ color: 'var(--bien, inherit)' }}>
            Configuración guardada.
          </span>
        )}
      </form>
    </div>
  )
}

export default function Administracion() {
  return (
    <>
      <div className="cabecera-pagina">
        <h1>Administración</h1>
      </div>

      <div className="columna" style={{ gap: 24 }}>
        <SeccionResumen />
        <SeccionClaveAcceso />
        <SeccionMotorIA />
      </div>
    </>
  )
}
