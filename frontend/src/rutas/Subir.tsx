/** Subida de PDFs con progreso por capa.
 *
 * El procesamiento corre en el servidor fuera del request, así que esta pantalla
 * puede cerrarse sin perder nada: al volver, el estado se lee de la base.
 */

import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { FalloApi } from '../api/cliente'
import { useEstadoDocumento, useProcesar } from '../api/consultas'
import type { CapaProgreso } from '../api/tipos'
import { IconoAlerta, IconoDocumento, IconoSubir } from '../componentes/Iconos'

const NOMBRES: Record<CapaProgreso['nombre'], string> = {
  triage: 'Triage',
  segmentacion: 'Segmentación',
  ocr: 'OCR especializado',
  correccion: 'Corrección determinista',
  escalacion: 'Escalación al modelo',
}

function Marca({ estado, numero }: { estado: CapaProgreso['estado']; numero: number }) {
  const base: React.CSSProperties = {
    flex: '0 0 auto',
    width: 24,
    height: 24,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 11,
    fontFamily: 'IBM Plex Mono, monospace',
    border: '1px solid var(--linea)',
  }

  if (estado === 'completada') {
    return (
      <span style={{ ...base, background: 'var(--tinta)', borderColor: 'var(--tinta)', color: 'var(--papel)' }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M5 12.5l5 5L19 7" />
        </svg>
      </span>
    )
  }

  if (estado === 'en_curso') {
    return <span style={{ ...base, borderColor: 'var(--acento)', borderWidth: 2, color: 'var(--acento)', fontWeight: 600 }}>{numero}</span>
  }

  if (estado === 'omitida') {
    return <span style={{ ...base, borderStyle: 'dashed', color: 'var(--alerta)', borderColor: 'var(--alerta-linea)' }}>–</span>
  }

  return <span style={{ ...base, color: 'var(--tenue)' }}>{numero}</span>
}

function Capa({ capa }: { capa: CapaProgreso }) {
  const activa = capa.estado === 'en_curso'
  const pendiente = capa.estado === 'pendiente'
  const avance = capa.progreso
  const porcentaje = avance && avance.total > 0 ? (avance.hechos / avance.total) * 100 : 0

  return (
    <div className="fila" style={{ gap: 13, alignItems: 'flex-start', opacity: pendiente ? 0.45 : 1 }}>
      <Marca estado={capa.estado} numero={capa.capa} />

      <div className="columna" style={{ gap: 5, flexGrow: 1, minWidth: 0 }}>
        <div className="fila" style={{ gap: 9 }}>
          <span style={{ fontSize: 13.5, fontWeight: activa ? 600 : 400, color: activa ? 'var(--acento)' : undefined }}>
            Capa {capa.capa} · {NOMBRES[capa.nombre] ?? capa.nombre}
          </span>
          <div className="crece" />
          {avance && (
            <span className="chico num" style={{ color: activa ? 'var(--acento)' : 'var(--apagado)' }}>
              {avance.hechos.toLocaleString('es')} / {avance.total.toLocaleString('es')}
            </span>
          )}
        </div>

        {activa && avance && avance.total > 0 && (
          <div style={{ height: 6, borderRadius: 3, background: 'var(--acento-tinte)', overflow: 'hidden' }}>
            <div
              style={{
                width: `${porcentaje}%`,
                height: '100%',
                background: 'var(--acento)',
                transition: 'width 0.4s ease',
              }}
            />
          </div>
        )}

        {capa.detalle && (
          <span className="chico" style={{ color: capa.estado === 'omitida' ? 'var(--alerta)' : 'var(--apagado)' }}>
            {capa.estado === 'omitida' ? `Omitida: ${capa.detalle}` : capa.detalle}
          </span>
        )}
      </div>
    </div>
  )
}

function Progreso({ documentoId }: { documentoId: string }) {
  const { data, error } = useEstadoDocumento(documentoId)

  if (error) {
    return (
      <div className="aviso aviso-error" role="alert">
        <IconoAlerta />
        <span>{(error as Error).message}</span>
      </div>
    )
  }

  if (!data) {
    return <div className="esqueleto" style={{ width: '60%', height: 18 }} />
  }

  const completas = data.capas.filter((c) => c.estado === 'completada' || c.estado === 'omitida').length
  const total = data.capas.length
  const termino = data.estado === 'completado' || data.estado === 'error'

  return (
    <div className="tarjeta" style={{ padding: '18px 20px' }}>
      <div className="columna" style={{ gap: 16 }}>
        <div className="fila" style={{ gap: 10, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--tenue)', display: 'flex' }}>
            <IconoDocumento tam={17} />
          </span>
          <strong style={{ fontSize: 14.5 }}>{data.titulo}</strong>
          {data.total_paginas > 0 && (
            <span className="pildora">{data.total_paginas} págs</span>
          )}
          <div className="crece" />
          {data.estado === 'completado' && <span className="pildora pildora-bien">completado</span>}
          {data.estado === 'error' && <span className="pildora pildora-alerta">error</span>}
          {!termino && (
            <span className="pildora pildora-acento">
              {data.estado === 'en_cola' ? 'en cola' : `capa ${completas + 1} de ${total}`}
            </span>
          )}
        </div>

        {data.error && (
          <div className="aviso aviso-error">
            <IconoAlerta />
            <div className="columna" style={{ gap: 5 }}>
              <span>No se pudo procesar el documento.</span>
              <code style={{ fontSize: 12 }}>{data.error}</code>
            </div>
          </div>
        )}

        <div style={{ height: 8, borderRadius: 4, background: 'var(--linea-suave)', overflow: 'hidden' }}>
          <div
            style={{
              width: `${(completas / total) * 100}%`,
              height: '100%',
              background: data.estado === 'error' ? 'var(--alerta)' : 'var(--acento)',
              transition: 'width 0.5s ease',
            }}
          />
        </div>

        <div className="columna" style={{ gap: 13 }}>
          {data.capas.map((c) => (
            <Capa key={c.capa} capa={c} />
          ))}
        </div>

        <div
          className="fila"
          style={{ gap: 10, borderTop: '1px solid var(--linea)', paddingTop: 13, flexWrap: 'wrap' }}
        >
          <span className="etiqueta">Gasto en el modelo</span>
          <span className="chico num">${data.costo_usd_parcial.toFixed(4)}</span>
          <div className="crece" />
          {data.estado === 'completado' && (
            <Link to="/documentos" className="boton boton-chico">
              Ver en documentos
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Subir() {
  const [arrastrando, setArrastrando] = useState(false)
  const [encolados, setEncolados] = useState<string[]>([])
  const entrada = useRef<HTMLInputElement>(null)
  const procesar = useProcesar()

  function enviar(archivos: FileList | null) {
    if (!archivos) return

    for (const archivo of Array.from(archivos)) {
      procesar.mutate(archivo, {
        // Se agrega adelante para que el último subido quede arriba.
        onSuccess: ({ documento_id }) => setEncolados((previos) => [documento_id, ...previos]),
      })
    }
  }

  return (
    <>
      <div className="cabecera-pagina">
        <h1>Subir y procesar</h1>
        <div className="crece" />
        <span className="etiqueta">
          El procesamiento corre en el servidor — podés cerrar esta pantalla
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 420px) minmax(0, 1fr)', gap: 22, alignItems: 'start' }}>
        <div className="columna" style={{ gap: 16 }}>
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setArrastrando(true)
            }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={(e) => {
              e.preventDefault()
              setArrastrando(false)
              enviar(e.dataTransfer.files)
            }}
            onClick={() => entrada.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                entrada.current?.click()
              }
            }}
            role="button"
            tabIndex={0}
            style={{
              border: `2px dashed ${arrastrando ? 'var(--acento)' : 'var(--linea)'}`,
              background: arrastrando ? 'var(--acento-tinte)' : 'var(--superficie-2)',
              borderRadius: 'var(--radio)',
              padding: '38px 24px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 11,
              cursor: 'pointer',
              textAlign: 'center',
              transition: 'border-color 0.15s ease, background 0.15s ease',
            }}
          >
            <span style={{ color: arrastrando ? 'var(--acento)' : 'var(--tenue)' }}>
              <IconoSubir tam={30} />
            </span>
            <strong style={{ fontSize: 14.5 }}>Arrastrá tus PDFs acá</strong>
            <span className="chico apagado">o hacé clic para elegirlos del disco</span>
            <input
              ref={entrada}
              type="file"
              accept="application/pdf,.pdf"
              multiple
              hidden
              onChange={(e) => {
                enviar(e.target.files)
                e.target.value = ''
              }}
            />
          </div>

          {procesar.error && (
            <div className="aviso aviso-error" role="alert">
              <IconoAlerta />
              <span>{(procesar.error as FalloApi).message}</span>
            </div>
          )}

          <div className="aviso">
            <span className="tenue" style={{ display: 'flex', flexShrink: 0 }}>
              <IconoAlerta />
            </span>
            <div className="columna" style={{ gap: 5 }}>
              <strong style={{ fontSize: 13 }}>Las opciones todavía no están</strong>
              <span className="apagado chico">
                El idioma, el DPI y el tope de gasto por documento están en el contrato
                pero no implementados: por ahora el motor usa el DPI que decide el triage
                y escala al modelo sin límite de gasto.
              </span>
            </div>
          </div>
        </div>

        <div className="columna" style={{ gap: 16 }}>
          {encolados.length === 0 ? (
            <div className="tarjeta vacio">
              <span style={{ color: 'var(--tenue)' }}>
                <IconoDocumento tam={30} />
              </span>
              <p>
                Acá vas a ver el avance capa por capa: triage, segmentación, OCR,
                corrección y escalación.
              </p>
            </div>
          ) : (
            <>
              <span className="etiqueta">En curso</span>
              {encolados.map((id) => (
                <Progreso key={id} documentoId={id} />
              ))}
            </>
          )}
        </div>
      </div>
    </>
  )
}
