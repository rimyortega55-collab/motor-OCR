/** Listado de documentos: filtros, búsqueda y paginación por cursor. */

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useDocumentos } from '../api/consultas'
import type { DocumentoResumen, EstadoDocumento, FiltrosDocumentos } from '../api/tipos'
import { IconoAlerta, IconoBuscar, IconoDocumento, IconoSubir } from '../componentes/Iconos'

const ESTADOS: { valor?: EstadoDocumento; etiqueta: string }[] = [
  { valor: undefined, etiqueta: 'Todos' },
  { valor: 'completado', etiqueta: 'Completados' },
  { valor: 'procesando', etiqueta: 'Procesando' },
  { valor: 'error', etiqueta: 'Con error' },
]

function fecha(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const hoy = new Date()
  const mismoDia = d.toDateString() === hoy.toDateString()
  const hora = d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })
  return mismoDia ? `hoy ${hora}` : `${d.toLocaleDateString('es', { day: 'numeric', month: 'short' })} ${hora}`
}

function Estado({ documento }: { documento: DocumentoResumen }) {
  if (documento.estado === 'error') return <span className="pildora pildora-alerta">error</span>
  if (documento.estado === 'procesando' || documento.estado === 'en_cola') {
    return <span className="pildora">{documento.estado === 'en_cola' ? 'en cola' : 'procesando'}</span>
  }
  if (documento.necesita_revision) return <span className="pildora pildora-alerta">revisar</span>
  return <span className="pildora pildora-bien">completado</span>
}

function FilaEsqueleto() {
  return (
    <tr>
      {Array.from({ length: 7 }).map((_, i) => (
        <td key={i}>
          <div className="esqueleto" style={{ width: `${45 + ((i * 17) % 45)}%` }} />
        </td>
      ))}
    </tr>
  )
}

export default function Documentos() {
  const [estado, setEstado] = useState<EstadoDocumento | undefined>()
  const [necesitaRevision, setNecesitaRevision] = useState(false)
  const [textoBuscado, setTextoBuscado] = useState('')
  const [buscar, setBuscar] = useState('')

  // Sin este retardo, cada tecla dispara un request y la lista parpadea.
  useEffect(() => {
    const id = setTimeout(() => setBuscar(textoBuscado.trim()), 300)
    return () => clearTimeout(id)
  }, [textoBuscado])

  const filtros: FiltrosDocumentos = useMemo(
    () => ({
      estado,
      buscar: buscar || undefined,
      necesita_revision: necesitaRevision || undefined,
      limite: 25,
    }),
    [estado, buscar, necesitaRevision],
  )

  const consulta = useDocumentos(filtros)
  const documentos = consulta.data?.pages.flatMap((p) => p.items) ?? []
  const total = consulta.data?.pages[0]?.total ?? 0
  const hayFiltro = Boolean(estado || buscar || necesitaRevision)

  return (
    <>
      <div className="cabecera-pagina">
        <h1>Documentos</h1>

        <label className="campo" style={{ maxWidth: 300, flexGrow: 1 }}>
          <span style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <span style={{ position: 'absolute', left: 11, color: 'var(--tenue)', display: 'flex' }}>
              <IconoBuscar tam={15} />
            </span>
            <input
              value={textoBuscado}
              onChange={(e) => setTextoBuscado(e.target.value)}
              placeholder="Buscar por título…"
              style={{ paddingLeft: 34 }}
              aria-label="Buscar documentos por título"
            />
          </span>
        </label>

        <div className="crece" />

        <Link to="/subir" className="boton boton-primario">
          <IconoSubir tam={15} /> Subir PDF
        </Link>
      </div>

      <div className="fila" style={{ flexWrap: 'wrap', marginBottom: 18 }}>
        {ESTADOS.map(({ valor, etiqueta }) => (
          <button
            key={etiqueta}
            type="button"
            className={`pildora ${estado === valor && !necesitaRevision ? 'pildora-activa' : ''}`}
            style={{ cursor: 'pointer' }}
            onClick={() => {
              setEstado(valor)
              setNecesitaRevision(false)
            }}
          >
            {etiqueta}
          </button>
        ))}
        <button
          type="button"
          className={`pildora ${necesitaRevision ? 'pildora-activa' : 'pildora-alerta'}`}
          style={{ cursor: 'pointer' }}
          onClick={() => {
            setNecesitaRevision((v) => !v)
            setEstado(undefined)
          }}
        >
          Necesitan revisión
        </button>

        <div className="crece" />
        {!consulta.isPending && (
          <span className="etiqueta">
            {total} {total === 1 ? 'documento' : 'documentos'}
            {hayFiltro ? ' en este filtro' : ''}
          </span>
        )}
      </div>

      {consulta.error && (
        <div className="aviso aviso-error" role="alert" style={{ marginBottom: 18 }}>
          <IconoAlerta />
          <span>{(consulta.error as Error).message}</span>
        </div>
      )}

      <div className="tarjeta">
        {!consulta.isPending && documentos.length === 0 ? (
          <div className="vacio">
            <span style={{ color: 'var(--tenue)' }}>
              <IconoDocumento tam={34} />
            </span>
            {hayFiltro ? (
              <>
                <h2>Ningún documento coincide</h2>
                <p>Probá con otro filtro o limpiá la búsqueda.</p>
                <button
                  type="button"
                  className="boton"
                  onClick={() => {
                    setEstado(undefined)
                    setNecesitaRevision(false)
                    setTextoBuscado('')
                  }}
                >
                  Limpiar filtros
                </button>
              </>
            ) : (
              <>
                <h2>Todavía no procesaste nada</h2>
                <p>
                  Subí un PDF y el motor lo segmenta en bloques, corre el OCR por tipo y te
                  arma la cola de lo que conviene que mires vos.
                </p>
                <Link to="/subir" className="boton boton-primario">
                  <IconoSubir tam={15} /> Subir mi primer PDF
                </Link>
              </>
            )}
          </div>
        ) : (
          <div className="marco-tabla">
            <table>
              <thead>
                <tr>
                  <th style={{ width: '34%' }}>Título</th>
                  <th>Estado</th>
                  <th>Páginas</th>
                  <th>Bloques</th>
                  <th>Inconsist.</th>
                  <th>Procesado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {consulta.isPending
                  ? Array.from({ length: 5 }).map((_, i) => <FilaEsqueleto key={i} />)
                  : documentos.map((d) => (
                      <tr key={d.documento_id}>
                        <td>
                          <div className="fila" style={{ gap: 9 }}>
                            <span className="tenue" style={{ display: 'flex' }}>
                              <IconoDocumento tam={15} />
                            </span>
                            <span>{d.titulo}</span>
                          </div>
                        </td>
                        <td><Estado documento={d} /></td>
                        <td className="num">{d.total_paginas || '—'}</td>
                        <td className="num">{d.total_bloques ? d.total_bloques.toLocaleString('es') : '—'}</td>
                        <td className="num">
                          {d.inconsistencias > 0 ? (
                            <span style={{ color: 'var(--alerta)' }}>{d.inconsistencias}</span>
                          ) : (
                            '0'
                          )}
                        </td>
                        <td className="apagado num">{fecha(d.creado_en)}</td>
                        <td style={{ textAlign: 'right' }}>
                          {d.necesita_revision && d.estado === 'completado' && (
                            <Link
                              to={`/documentos/${d.documento_id}/revision`}
                              className="boton boton-chico"
                              style={{ borderColor: 'var(--alerta-linea)', color: 'var(--alerta)' }}
                            >
                              Revisar
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {consulta.hasNextPage && (
        <div className="fila" style={{ justifyContent: 'center', marginTop: 18 }}>
          <button
            type="button"
            className="boton"
            onClick={() => consulta.fetchNextPage()}
            disabled={consulta.isFetchingNextPage}
          >
            {consulta.isFetchingNextPage ? 'Cargando…' : `Cargar más (${documentos.length} de ${total})`}
          </button>
        </div>
      )}
    </>
  )
}
