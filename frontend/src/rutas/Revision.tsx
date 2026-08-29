/** Visor de revisión bloque a bloque — la Capa 6, que hasta ahora era una CLI.
 *
 * Tres columnas: la cola de lo que quedó por debajo del umbral, la página con el
 * overlay de bloques, y el panel de decisión. El bbox viene normalizado a [0,1],
 * así que el overlay se posiciona en porcentajes y no necesita saber el DPI con
 * que se renderizó la imagen.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { FalloApi } from '../api/cliente'
import {
  useBloque,
  useBloquesDePagina,
  useCola,
  useDecidir,
  usePaginas,
} from '../api/consultas'
import type { Bloque, Decision } from '../api/tipos'
import { IconoAlerta, IconoDocumento } from '../componentes/Iconos'

const ATAJOS: Record<string, Decision> = { a: 'aceptar', e: 'editar', r: 'rechazar', x: 'escalar' }

function color(confianza: number | null): string {
  if (confianza === null) return 'var(--tenue)'
  if (confianza < 0.7) return 'var(--alerta)'
  return 'var(--tinta)'
}

function Confianza({ valor }: { valor: number | null }) {
  if (valor === null) return <span className="chico tenue">—</span>

  return (
    <span className="fila" style={{ gap: 7 }}>
      <span style={{ width: 46, height: 6, borderRadius: 3, background: 'var(--linea-suave)' }}>
        <span
          style={{
            display: 'block',
            width: `${valor * 100}%`,
            height: '100%',
            borderRadius: 3,
            background: color(valor),
          }}
        />
      </span>
      <span className="chico num">{valor.toFixed(2)}</span>
    </span>
  )
}

function Cola({
  bloques,
  activo,
  alElegir,
}: {
  bloques: Bloque[]
  activo: string | null
  alElegir: (id: string) => void
}) {
  return (
    <div className="columna" style={{ gap: 8, padding: 12, overflowY: 'auto' }}>
      {bloques.map((b) => {
        const seleccionado = b.id === activo
        return (
          <button
            key={b.id}
            type="button"
            onClick={() => alElegir(b.id)}
            style={{
              font: 'inherit',
              textAlign: 'left',
              cursor: 'pointer',
              border: `1px solid ${seleccionado ? 'var(--acento)' : 'var(--linea)'}`,
              borderWidth: seleccionado ? 2 : 1,
              borderRadius: 'var(--radio-chico)',
              background: seleccionado ? 'var(--acento-tinte)' : 'var(--superficie)',
              padding: '9px 11px',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <span className="fila" style={{ gap: 7 }}>
              <span className="etiqueta">p.{b.pagina + 1}</span>
              <span className="pildora" style={{ fontSize: 10 }}>{b.tipo}</span>
              <span className="crece" />
              <Confianza valor={b.confianza_global} />
            </span>
            {b.texto_plano && (
              <span
                className="chico apagado"
                style={{
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  lineHeight: 1.4,
                }}
              >
                {b.texto_plano}
              </span>
            )}
            {b.escalacion?.requirio_escalacion && (
              <span className="chico" style={{ color: 'var(--acento)' }}>escalado al modelo</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

function Pagina({
  documentoId,
  pagina,
  resaltado,
  alElegir,
  aspecto,
}: {
  documentoId: string
  pagina: number
  resaltado: string | null
  alElegir: (id: string) => void
  aspecto: number
}) {
  const { data } = useBloquesDePagina(documentoId, pagina)

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        // Reserva el alto antes de que cargue la imagen: sin esto la página
        // salta cuando el PNG llega.
        aspectRatio: String(aspecto),
        background: 'var(--superficie)',
        border: '1px solid var(--linea)',
        borderRadius: 'var(--radio-chico)',
        overflow: 'hidden',
        boxShadow: 'var(--sombra)',
      }}
    >
      <img
        src={`/api/documentos/${documentoId}/paginas/${pagina}?ancho=1100`}
        alt={`Página ${pagina + 1}`}
        style={{ width: '100%', height: '100%', display: 'block', objectFit: 'contain' }}
      />

      {data?.items.map((b) => {
        const activo = b.id === resaltado
        const pendiente = b.estado_revision === 'pendiente'
        if (!pendiente && !activo) return null

        return (
          <button
            key={b.id}
            type="button"
            onClick={() => alElegir(b.id)}
            title={`${b.tipo}${b.confianza_global !== null ? ` · ${b.confianza_global.toFixed(2)}` : ''}`}
            style={{
              position: 'absolute',
              // El bbox está normalizado, así que va directo a porcentajes.
              left: `${b.bbox.x0 * 100}%`,
              top: `${b.bbox.y0 * 100}%`,
              width: `${(b.bbox.x1 - b.bbox.x0) * 100}%`,
              height: `${(b.bbox.y1 - b.bbox.y0) * 100}%`,
              border: `2px solid ${activo ? 'var(--acento)' : 'var(--alerta)'}`,
              background: activo ? 'var(--acento-velo)' : 'transparent',
              borderRadius: 2,
              padding: 0,
              cursor: 'pointer',
            }}
          />
        )
      })}
    </div>
  )
}

function Panel({
  documentoId,
  bloqueId,
  alResolver,
  restantes,
  posicion,
}: {
  documentoId: string
  bloqueId: string
  alResolver: (siguiente: string | null) => void
  restantes: number
  posicion: number
}) {
  const { data: bloque, isPending } = useBloque(documentoId, bloqueId)
  const decidir = useDecidir(documentoId)

  const [contenido, setContenido] = useState('')
  const [confianza, setConfianza] = useState(0.9)
  const [comentarios, setComentarios] = useState('')

  // Cada bloque arranca con la mejor versión disponible: la del modelo si la
  // hay, y si no la del motor.
  useEffect(() => {
    if (!bloque) return
    setContenido(
      bloque.contenido_final ??
        bloque.escalacion?.contenido_llm ??
        bloque.latex ??
        bloque.texto_plano ??
        '',
    )
    setConfianza(0.9)
    setComentarios('')
  }, [bloque])

  const resolver = useCallback(
    (decision: Decision) => {
      if (!bloque) return
      decidir.mutate(
        {
          bloque_id: bloque.id,
          decision,
          contenido_final: decision === 'rechazar' ? (bloque.texto_plano ?? '') : contenido,
          confianza_usuario: confianza,
          comentarios,
        },
        { onSuccess: ({ siguiente_bloque_id }) => alResolver(siguiente_bloque_id) },
      )
    },
    [bloque, contenido, confianza, comentarios, decidir, alResolver],
  )

  // Los atajos son lo que hace que revisar cientos de bloques sea viable; se
  // desactivan mientras se escribe, para no disparar una decisión al tipear.
  useEffect(() => {
    function alTeclear(evento: KeyboardEvent) {
      const objetivo = evento.target as HTMLElement
      if (['INPUT', 'TEXTAREA'].includes(objetivo.tagName) || objetivo.isContentEditable) return
      if (evento.metaKey || evento.ctrlKey || evento.altKey) return

      const decision = ATAJOS[evento.key.toLowerCase()]
      if (decision) {
        evento.preventDefault()
        resolver(decision)
      }
    }

    window.addEventListener('keydown', alTeclear)
    return () => window.removeEventListener('keydown', alTeclear)
  }, [resolver])

  if (isPending || !bloque) {
    return (
      <div className="columna" style={{ padding: 16, gap: 10 }}>
        <div className="esqueleto" style={{ width: '55%', height: 16 }} />
        <div className="esqueleto" style={{ width: '90%' }} />
        <div className="esqueleto" style={{ width: '75%' }} />
      </div>
    )
  }

  const llm = bloque.escalacion
  const motor = bloque.latex ?? bloque.texto_plano ?? ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--linea)' }}>
        <div className="columna" style={{ gap: 7 }}>
          <div className="fila" style={{ gap: 8 }}>
            <strong style={{ fontSize: 14 }}>
              Bloque {posicion} de {restantes}
            </strong>
            <span className="pildora pildora-acento">{bloque.tipo}</span>
            <span className="crece" />
            <span className="etiqueta">pág. {bloque.pagina + 1}</span>
          </div>
          <span className="chico tenue mono">
            {bloque.id.slice(0, 8)}… · orden {bloque.orden_lectura}
            {bloque.micro_segmentos?.[0] && ` · ${bloque.micro_segmentos[0].engine_usado}`}
          </span>
        </div>
      </div>

      <div style={{ flexGrow: 1, overflowY: 'auto', padding: '14px 16px' }}>
        <div className="columna" style={{ gap: 14 }}>
          <div className="columna" style={{ gap: 6 }}>
            <div className="fila" style={{ gap: 8 }}>
              <span className="etiqueta">Lo que leyó el motor</span>
              <Confianza valor={bloque.confianza_global} />
            </div>
            <div
              className="mono"
              style={{
                border: '1px solid var(--linea)',
                borderRadius: 'var(--radio-chico)',
                background: 'var(--superficie-2)',
                padding: '10px 12px',
                fontSize: 12,
                lineHeight: 1.6,
                color: 'var(--apagado)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {motor || <em className="tenue">sin contenido</em>}
            </div>
          </div>

          {llm?.contenido_llm && (
            <div className="columna" style={{ gap: 6 }}>
              <div className="fila" style={{ gap: 8 }}>
                <span className="etiqueta" style={{ color: 'var(--acento)' }}>
                  Corrección del modelo
                </span>
                {llm.confianza_llm !== null && (
                  <span className="pildora pildora-acento">{llm.confianza_llm.toFixed(2)}</span>
                )}
              </div>
              <div
                className="mono"
                style={{
                  border: '1px solid var(--acento-linea)',
                  borderRadius: 'var(--radio-chico)',
                  background: 'var(--acento-tinte)',
                  padding: '10px 12px',
                  fontSize: 12,
                  lineHeight: 1.6,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {llm.contenido_llm}
              </div>
              {llm.razon_escalacion && (
                <span className="chico apagado">Razón: {llm.razon_escalacion}</span>
              )}
            </div>
          )}

          <div className="columna" style={{ gap: 6 }}>
            <span className="etiqueta">Contenido final</span>
            <textarea
              value={contenido}
              onChange={(e) => setContenido(e.target.value)}
              rows={6}
              spellCheck={false}
              style={{
                font: 'inherit',
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 12,
                lineHeight: 1.6,
                padding: '10px 12px',
                border: '2px solid var(--linea)',
                borderRadius: 'var(--radio-chico)',
                background: 'var(--superficie)',
                color: 'var(--tinta)',
                resize: 'vertical',
                width: '100%',
              }}
            />
          </div>

          <div className="columna" style={{ gap: 8 }}>
            <div className="fila" style={{ gap: 10 }}>
              <span className="etiqueta">Tu confianza</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={confianza}
                onChange={(e) => setConfianza(Number(e.target.value))}
                style={{ flexGrow: 1 }}
                aria-label="Tu confianza en esta decisión"
              />
              <span className="chico num">{confianza.toFixed(2)}</span>
            </div>
            <input
              value={comentarios}
              onChange={(e) => setComentarios(e.target.value)}
              placeholder="Comentario para el análisis de patrones (opcional)"
              style={{
                font: 'inherit',
                fontSize: 12.5,
                padding: '8px 11px',
                border: '1px solid var(--linea)',
                borderRadius: 'var(--radio-chico)',
                background: 'var(--superficie)',
                color: 'var(--tinta)',
                width: '100%',
              }}
            />
          </div>

          {decidir.error && (
            <div className="aviso aviso-error" role="alert">
              <IconoAlerta />
              <span>{(decidir.error as FalloApi).message}</span>
            </div>
          )}
        </div>
      </div>

      <div
        style={{
          padding: '13px 16px',
          borderTop: '1px solid var(--linea)',
          background: 'var(--superficie-2)',
        }}
      >
        <div className="columna" style={{ gap: 9 }}>
          <div className="fila" style={{ gap: 8 }}>
            <button
              type="button"
              className="boton boton-primario"
              style={{ flexGrow: 1 }}
              onClick={() => resolver('aceptar')}
              disabled={decidir.isPending}
            >
              Aceptar <kbd className="mono" style={{ opacity: 0.75, fontSize: 10 }}>A</kbd>
            </button>
            <button
              type="button"
              className="boton"
              style={{ flexGrow: 1 }}
              onClick={() => resolver('editar')}
              disabled={decidir.isPending}
            >
              Guardar edición <kbd className="mono" style={{ opacity: 0.6, fontSize: 10 }}>E</kbd>
            </button>
          </div>
          <div className="fila" style={{ gap: 8 }}>
            <button
              type="button"
              className="boton"
              style={{ flexGrow: 1 }}
              onClick={() => resolver('rechazar')}
              disabled={decidir.isPending}
            >
              Rechazar <kbd className="mono" style={{ opacity: 0.6, fontSize: 10 }}>R</kbd>
            </button>
            <button
              type="button"
              className="boton boton-peligro"
              style={{ flexGrow: 1 }}
              onClick={() => resolver('escalar')}
              disabled={decidir.isPending}
            >
              Escalar <kbd className="mono" style={{ opacity: 0.6, fontSize: 10 }}>X</kbd>
            </button>
          </div>
          <span className="chico tenue" style={{ textAlign: 'center' }}>
            Cada decisión alimenta el auto-ajuste de umbrales
          </span>
        </div>
      </div>
    </div>
  )
}

export default function Revision() {
  const { documentoId = '' } = useParams()
  const cola = useCola(documentoId)
  const paginas = usePaginas(documentoId)

  const [activo, setActivo] = useState<string | null>(null)
  const bloques = useMemo(() => cola.data?.items ?? [], [cola.data])

  // El primero de la cola apenas llega, y el siguiente cuando el actual se
  // resuelve y desaparece de la lista.
  useEffect(() => {
    if (bloques.length === 0) {
      setActivo(null)
      return
    }
    setActivo((previo) => (previo && bloques.some((b) => b.id === previo) ? previo : bloques[0].id))
  }, [bloques])

  const bloqueActivo = bloques.find((b) => b.id === activo) ?? null
  const posicion = bloqueActivo ? bloques.indexOf(bloqueActivo) + 1 : 0
  const infoPagina = paginas.data?.paginas.find((p) => p.pagina === bloqueActivo?.pagina)
  const aspecto = infoPagina ? infoPagina.ancho_px / infoPagina.alto_px : 0.7

  if (cola.isPending) {
    return (
      <div className="columna" style={{ padding: 40, gap: 12, maxWidth: 420 }}>
        <div className="esqueleto" style={{ width: '45%', height: 20 }} />
        <div className="esqueleto" style={{ width: '80%' }} />
      </div>
    )
  }

  if (cola.error) {
    return (
      <div style={{ padding: 40, maxWidth: 560 }}>
        <div className="aviso aviso-error" role="alert">
          <IconoAlerta />
          <span>{(cola.error as FalloApi).message}</span>
        </div>
      </div>
    )
  }

  if (bloques.length === 0) {
    return (
      <div className="tarjeta vacio" style={{ margin: 40, maxWidth: 560 }}>
        <span style={{ color: 'var(--tinta)' }}>
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} aria-hidden>
            <circle cx="12" cy="12" r="9" />
            <path d="M8 12.5l2.5 2.5L16 9.5" />
          </svg>
        </span>
        <h2>La cola está vacía</h2>
        <p>
          Ningún bloque de este documento quedó por debajo del umbral. No hace falta que
          revises nada.
        </p>
        <Link to="/documentos" className="boton">Volver a documentos</Link>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <header
        className="fila"
        style={{
          gap: 13,
          padding: '12px 20px',
          borderBottom: '1px solid var(--linea)',
          background: 'var(--superficie-2)',
          flexWrap: 'wrap',
        }}
      >
        <Link to="/documentos" className="fila" style={{ gap: 9, textDecoration: 'none', color: 'var(--tinta)' }}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          <IconoDocumento tam={16} />
        </Link>
        <strong style={{ fontSize: 14 }}>Revisión</strong>
        <span className="pildora pildora-alerta">capa 6</span>
        <span className="crece" />
        <span className="etiqueta">Pendientes</span>
        <span style={{ width: 140, height: 7, borderRadius: 4, background: 'var(--linea)' }}>
          <span
            style={{
              display: 'block',
              width: `${(posicion / bloques.length) * 100}%`,
              height: '100%',
              borderRadius: 4,
              background: 'var(--acento)',
            }}
          />
        </span>
        <span className="chico num">{posicion} / {bloques.length}</span>
      </header>

      <div style={{ flexGrow: 1, display: 'grid', gridTemplateColumns: '268px minmax(0, 1fr) 400px', overflow: 'hidden' }}>
        <section style={{ borderRight: '1px solid var(--linea)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--linea)' }}>
            <span className="etiqueta">Cola de revisión · {bloques.length}</span>
          </div>
          <Cola bloques={bloques} activo={activo} alElegir={setActivo} />
        </section>

        <section style={{ background: 'var(--superficie-2)', overflowY: 'auto', padding: 20 }}>
          {bloqueActivo && (
            <div style={{ maxWidth: 620, margin: '0 auto' }}>
              <div className="fila" style={{ gap: 9, marginBottom: 12 }}>
                <span className="etiqueta">Página {bloqueActivo.pagina + 1}</span>
                {paginas.data && (
                  <span className="chico tenue">de {paginas.data.total_paginas}</span>
                )}
              </div>
              {paginas.error ? (
                <div className="aviso aviso-error">
                  <IconoAlerta />
                  <span>{(paginas.error as FalloApi).message}</span>
                </div>
              ) : (
                <Pagina
                  documentoId={documentoId}
                  pagina={bloqueActivo.pagina}
                  resaltado={bloqueActivo.id}
                  alElegir={setActivo}
                  aspecto={aspecto}
                />
              )}
            </div>
          )}
        </section>

        <section style={{ borderLeft: '1px solid var(--linea)', overflow: 'hidden' }}>
          {activo && (
            <Panel
              key={activo}
              documentoId={documentoId}
              bloqueId={activo}
              restantes={bloques.length}
              posicion={posicion}
              alResolver={(siguiente) => setActivo(siguiente)}
            />
          )}
        </section>
      </div>
    </div>
  )
}
