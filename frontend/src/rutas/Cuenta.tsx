/** Cuenta y API keys: alta, listado y revocación. */

import { useState } from 'react'

import { FalloApi } from '../api/cliente'
import {
  useApiKeys,
  useConsumo,
  useCrearApiKey,
  useRevocarApiKey,
  useSesion,
} from '../api/consultas'
import type { ApiKey } from '../api/tipos'
import { IconoAlerta, IconoLlave, IconoMas } from '../componentes/Iconos'

function desde(iso: string | null): string {
  if (!iso) return 'nunca'
  const minutos = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutos < 1) return 'recién'
  if (minutos < 60) return `hace ${minutos} min`
  const horas = Math.floor(minutos / 60)
  if (horas < 24) return `hace ${horas} h`
  const dias = Math.floor(horas / 24)
  return dias === 1 ? 'ayer' : `hace ${dias} días`
}

function ClaveEnClaro({ clave, alCerrar }: { clave: string; alCerrar: () => void }) {
  const [copiada, setCopiada] = useState(false)

  return (
    <div className="aviso aviso-acento" style={{ flexDirection: 'column', gap: 10 }}>
      <span className="etiqueta" style={{ color: 'var(--acento)' }}>
        <IconoLlave tam={13} /> Clave recién creada — se muestra una sola vez
      </span>

      <div className="fila" style={{ gap: 10, flexWrap: 'wrap' }}>
        <code
          style={{
            flexGrow: 1,
            minWidth: 240,
            fontSize: 12.5,
            wordBreak: 'break-all',
            background: 'var(--superficie)',
            border: '1px solid var(--acento-linea)',
            borderRadius: 'var(--radio-chico)',
            padding: '9px 11px',
          }}
        >
          {clave}
        </code>
        <button
          type="button"
          className="boton boton-chico"
          onClick={() =>
            navigator.clipboard?.writeText(clave).then(
              () => setCopiada(true),
              () => setCopiada(false),
            )
          }
        >
          {copiada ? 'Copiada' : 'Copiar'}
        </button>
        <button type="button" className="boton boton-chico" onClick={alCerrar}>
          Ya la guardé
        </button>
      </div>

      <span className="chico apagado">
        En la base sólo queda su hash SHA-256, así que no hay forma de volver a mostrarla.
        Si se pierde, revocala y creá otra.
      </span>
    </div>
  )
}

function Fila({ clave }: { clave: ApiKey }) {
  const revocar = useRevocarApiKey()
  const revocada = clave.revocada_en !== null

  return (
    <tr style={revocada ? { opacity: 0.55 } : undefined}>
      <td>{clave.nombre}</td>
      <td>
        <code className="apagado" style={{ fontSize: 12.5 }}>
          {clave.prefijo}…
        </code>
      </td>
      <td className="apagado num">{desde(clave.creada_en)}</td>
      <td className="apagado num">{revocada ? 'revocada' : desde(clave.ultimo_uso_en)}</td>
      <td style={{ textAlign: 'right' }}>
        {!revocada && (
          <button
            type="button"
            className="boton boton-chico boton-peligro"
            onClick={() => revocar.mutate(clave.id)}
            disabled={revocar.isPending}
          >
            {revocar.isPending ? 'Revocando…' : 'Revocar'}
          </button>
        )}
      </td>
    </tr>
  )
}

export default function Cuenta() {
  const { data: usuario } = useSesion()
  const claves = useApiKeys()
  const consumo = useConsumo()
  const crear = useCrearApiKey()

  const [nombre, setNombre] = useState('')
  const [recienCreada, setRecienCreada] = useState<string | null>(null)

  const activas = claves.data?.filter((c) => c.revocada_en === null).length ?? 0

  function crearClave(evento: React.FormEvent) {
    evento.preventDefault()
    crear.mutate(nombre.trim() || 'sin nombre', {
      onSuccess: ({ api_key }) => {
        setRecienCreada(api_key)
        setNombre('')
      },
    })
  }

  return (
    <>
      <div className="cabecera-pagina">
        <h1>Cuenta y API</h1>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) 300px',
          gap: 20,
          alignItems: 'start',
        }}
      >
        <div className="columna" style={{ gap: 18 }}>
          {recienCreada && (
            <ClaveEnClaro clave={recienCreada} alCerrar={() => setRecienCreada(null)} />
          )}

          <div className="tarjeta">
            <div
              className="fila"
              style={{ padding: '15px 16px', borderBottom: '1px solid var(--linea)' }}
            >
              <span className="etiqueta">API keys</span>
              <span className="pildora">{activas} {activas === 1 ? 'activa' : 'activas'}</span>
              <div className="crece" />
              <form className="fila" onSubmit={crearClave} style={{ gap: 8 }}>
                <input
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  placeholder="notebook local"
                  aria-label="Nombre de la clave nueva"
                  style={{
                    font: 'inherit',
                    fontSize: 13,
                    padding: '6px 10px',
                    border: '1px solid var(--linea)',
                    borderRadius: 'var(--radio-chico)',
                    background: 'var(--superficie)',
                    color: 'var(--tinta)',
                    width: 170,
                  }}
                />
                <button
                  type="submit"
                  className="boton boton-chico boton-primario"
                  disabled={crear.isPending}
                >
                  <IconoMas tam={13} />
                  {crear.isPending ? 'Creando…' : 'Crear clave'}
                </button>
              </form>
            </div>

            {crear.error && (
              <div className="aviso aviso-error" style={{ margin: 14, border: 'none' }}>
                <IconoAlerta />
                <span>{(crear.error as FalloApi).message}</span>
              </div>
            )}

            <div className="marco-tabla">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: '30%' }}>Nombre</th>
                    <th>Clave</th>
                    <th>Creada</th>
                    <th>Último uso</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {claves.isPending ? (
                    <tr>
                      <td colSpan={5}>
                        <div className="esqueleto" style={{ width: '60%' }} />
                      </td>
                    </tr>
                  ) : (
                    claves.data?.map((c) => <Fila key={c.id} clave={c} />)
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="tarjeta" style={{ padding: '16px 18px' }}>
            <div className="columna" style={{ gap: 12 }}>
              <span className="etiqueta">Usar la API</span>
              <pre
                style={{
                  margin: 0,
                  background: 'var(--tinta)',
                  color: 'var(--papel)',
                  borderRadius: 'var(--radio-chico)',
                  padding: '13px 15px',
                  overflowX: 'auto',
                  fontSize: 12.5,
                  lineHeight: 1.65,
                }}
              >
                <code>
                  {`curl -X POST ${window.location.origin}/api/procesar \\\n`}
                  {`  -H "X-API-Key: ${claves.data?.[0]?.prefijo ?? 'moc_'}…" \\\n`}
                  {`  -F "file=@c7.pdf"`}
                </code>
              </pre>
              <span className="chico apagado">
                Las claves sirven para los endpoints de datos. Administrarlas —crear o
                revocar— exige sesión de navegador: si una clave filtrada pudiera emitir
                claves nuevas, revocarla no serviría de nada.
              </span>
            </div>
          </div>
        </div>

        <div className="columna" style={{ gap: 16 }}>
          <div className="tarjeta" style={{ padding: '16px 18px' }}>
            <div className="columna" style={{ gap: 12 }}>
              <span className="etiqueta">Perfil</span>
              <div className="columna" style={{ gap: 3 }}>
                <strong style={{ fontSize: 15 }}>{usuario?.nombre}</strong>
                <span className="chico apagado">{usuario?.email ?? 'sin email'}</span>
              </div>
              <div className="fila">
                <span className="chico">Plan</span>
                <div className="crece" />
                <span className="pildora">{usuario?.plan}</span>
              </div>
            </div>
          </div>

          <div className="tarjeta" style={{ padding: '16px 18px' }}>
            <div className="columna" style={{ gap: 12 }}>
              <span className="etiqueta">Consumo acumulado</span>
              {consumo.isPending ? (
                <div className="esqueleto" style={{ width: '70%' }} />
              ) : (
                <div className="columna" style={{ gap: 9 }}>
                  {[
                    ['Documentos', consumo.data?.totales.documentos ?? 0],
                    ['Páginas', consumo.data?.totales.paginas ?? 0],
                    ['Llamadas al modelo', consumo.data?.totales.llamadas_llm ?? 0],
                    ['Costo', `$${(consumo.data?.totales.costo_llm_usd ?? 0).toFixed(4)}`],
                  ].map(([etiqueta, valor]) => (
                    <div className="fila" key={etiqueta as string}>
                      <span className="chico">{etiqueta}</span>
                      <div
                        className="crece"
                        style={{ borderBottom: '1px dotted var(--linea)', height: 1 }}
                      />
                      <span className="chico num">{valor}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
