/** Traducción del documento, con el contexto que decide el usuario.
 *
 * Traducir es el paso más caro del motor: sobre un documento de 213 páginas
 * cuesta más que todo el OCR junto. Por eso la pantalla insiste en el contexto
 * antes que en el botón — describir el documento y fijar el glosario es lo que
 * separa una traducción técnica utilizable de una literal, y rehacerla porque
 * salió mal se paga dos veces.
 *
 * Las fórmulas y el código nunca se traducen. No es una opción que se pueda
 * desmarcar: traducir una fórmula la destruye.
 */

import { useState } from 'react'

import {
  useBorrarTraduccion,
  usePedirTraduccion,
  useSugerenciasGlosario,
  useTraducciones,
} from '../api/consultas'
import { useExportar } from '../api/consultas'
import type { FormatoExport } from '../api/tipos'
import { IconoAlerta } from './Iconos'

const IDIOMAS = ['español', 'inglés', 'portugués', 'francés', 'alemán', 'italiano']

/** Tipos que el usuario puede elegir traducir o no. Sin fórmulas ni código. */
const TIPOS_ELEGIBLES = [
  ['parrafo', 'Párrafos'],
  ['teorema', 'Teoremas'],
  ['demostracion', 'Demostraciones'],
  ['definicion', 'Definiciones'],
  ['encabezado', 'Títulos'],
  ['caption', 'Epígrafes'],
] as const

export default function Traducir({
  documentoId,
  titulo,
}: {
  documentoId: string
  titulo: string
}) {
  const traducciones = useTraducciones(documentoId)
  const pedir = usePedirTraduccion(documentoId)
  const borrar = useBorrarTraduccion(documentoId)
  const exportar = useExportar()

  const [abierto, setAbierto] = useState(false)
  const [idioma, setIdioma] = useState('español')
  const [descripcion, setDescripcion] = useState('')
  const [tono, setTono] = useState<'academico' | 'accesible'>('academico')
  const [tipos, setTipos] = useState<string[]>([])
  const [glosario, setGlosario] = useState<Record<string, string>>({})

  const sugerencias = useSugerenciasGlosario(documentoId, abierto)

  const alternarTipo = (tipo: string) =>
    setTipos((previos) =>
      previos.includes(tipo) ? previos.filter((t) => t !== tipo) : [...previos, tipo],
    )

  const fijarTermino = (termino: string, valor: string) =>
    setGlosario((previo) => {
      const siguiente = { ...previo }
      if (valor.trim()) siguiente[termino] = valor.trim()
      else delete siguiente[termino]
      return siguiente
    })

  const enviar = () => {
    pedir.mutate(
      {
        idioma,
        descripcion,
        tono,
        glosario,
        seleccion: { paginas: [], tipos },
      },
      { onSuccess: () => setAbierto(false) },
    )
  }

  const listas = (traducciones.data ?? []).filter((t) => t.estado === 'completada')
  const enCurso = (traducciones.data ?? []).filter(
    (t) => t.estado === 'en_cola' || t.estado === 'traduciendo',
  )

  return (
    <div className="tarjeta" style={{ padding: '18px 20px' }}>
      <div className="columna" style={{ gap: 14 }}>
        <div className="fila" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div className="columna" style={{ gap: 3 }}>
            <span className="etiqueta">Traducir</span>
            <span className="chico apagado">
              Las fórmulas y el código quedan intactos.
            </span>
          </div>
          {!abierto && (
            <button type="button" className="boton boton-chico" onClick={() => setAbierto(true)}>
              Nueva traducción
            </button>
          )}
        </div>

        {/* ---- traducciones ya hechas ---- */}
        {enCurso.map((t) => (
          <div className="columna" style={{ gap: 5 }} key={t.id}>
            <div className="fila" style={{ gap: 10, alignItems: 'baseline' }}>
              <span className="pildora">{t.idioma}</span>
              <span className="chico apagado crece">
                traduciendo {t.bloques_traducidos} de {t.bloques_totales}
              </span>
              <span className="chico num">${t.costo_usd.toFixed(4)}</span>
            </div>
            <div style={{ height: 4, borderRadius: 2, background: 'var(--linea)' }}>
              <div
                style={{
                  width: `${t.bloques_totales ? (t.bloques_traducidos / t.bloques_totales) * 100 : 0}%`,
                  height: '100%',
                  borderRadius: 2,
                  background: 'var(--acento)',
                }}
              />
            </div>
          </div>
        ))}

        {listas.map((t) => (
          <div
            className="fila"
            style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
            key={t.id}
          >
            <span className="pildora pildora-bien">{t.idioma}</span>
            <span className="chico apagado">
              {t.bloques_traducidos} bloques · ${t.costo_usd.toFixed(4)}
            </span>
            {t.error && (
              <span className="chico" style={{ color: 'var(--alerta)' }}>
                {t.error}
              </span>
            )}
            <div className="crece" />
            {(['latex', 'markdown'] as FormatoExport[]).map((formato) => (
              <button
                key={formato}
                type="button"
                className="boton boton-chico"
                disabled={exportar.isPending}
                onClick={() =>
                  exportar.mutate({ documentoId, titulo, formato, idioma: t.idioma })
                }
              >
                {formato === 'latex' ? '.tex' : '.md'}
              </button>
            ))}
            <button
              type="button"
              className="boton boton-chico"
              onClick={() => borrar.mutate(t.idioma)}
            >
              Borrar
            </button>
          </div>
        ))}

        {!abierto && listas.length === 0 && enCurso.length === 0 && (
          <span className="apagado chico">Todavía no tradujiste este documento.</span>
        )}

        {/* ---- formulario de contexto ---- */}
        {abierto && (
          <div className="columna" style={{ gap: 16, paddingTop: 4 }}>
            <div className="columna" style={{ gap: 5 }}>
              <span className="chico">Idioma</span>
              <div className="fila" style={{ gap: 6, flexWrap: 'wrap' }}>
                {IDIOMAS.map((i) => (
                  <button
                    key={i}
                    type="button"
                    className={`pildora ${idioma === i ? 'pildora-activa' : ''}`}
                    onClick={() => setIdioma(i)}
                  >
                    {i}
                  </button>
                ))}
              </div>
            </div>

            <div className="columna" style={{ gap: 5 }}>
              <span className="chico">De qué trata y para quién</span>
              <textarea
                className="campo"
                rows={2}
                placeholder="Libro de álgebra de posgrado, para alguien que ya cursó teoría de grupos"
                value={descripcion}
                onChange={(e) => setDescripcion(e.target.value)}
                style={{ resize: 'vertical', fontFamily: 'inherit' }}
              />
              <span className="chico apagado">
                Es lo que más cambia el resultado: sin esto, el modelo traduce
                término por término sin saber de qué campo se trata.
              </span>
            </div>

            <div className="columna" style={{ gap: 5 }}>
              <span className="chico">Tono</span>
              <div className="fila" style={{ gap: 6 }}>
                {(
                  [
                    ['academico', 'Académico', 'Como un paper o un libro de texto'],
                    ['accesible', 'Accesible', 'Didáctico, para quien está aprendiendo'],
                  ] as const
                ).map(([valor, nombre, ayuda]) => (
                  <button
                    key={valor}
                    type="button"
                    title={ayuda}
                    className={`pildora ${tono === valor ? 'pildora-activa' : ''}`}
                    onClick={() => setTono(valor)}
                  >
                    {nombre}
                  </button>
                ))}
              </div>
            </div>

            <div className="columna" style={{ gap: 5 }}>
              <span className="chico">Qué partes</span>
              <div className="fila" style={{ gap: 6, flexWrap: 'wrap' }}>
                {TIPOS_ELEGIBLES.map(([valor, nombre]) => (
                  <button
                    key={valor}
                    type="button"
                    className={`pildora ${tipos.includes(valor) ? 'pildora-activa' : ''}`}
                    onClick={() => alternarTipo(valor)}
                  >
                    {nombre}
                  </button>
                ))}
              </div>
              <span className="chico apagado">
                {tipos.length === 0
                  ? 'Sin elegir nada se traduce todo lo traducible.'
                  : `Sólo ${tipos.length} tipo(s). Lo demás queda en el idioma original.`}
              </span>
            </div>

            {/* ---- glosario ---- */}
            <div className="columna" style={{ gap: 7 }}>
              <span className="chico">Glosario</span>
              <span className="chico apagado">
                Cada llamada al modelo ve sólo un fragmento, así que sin esto el mismo
                término puede salir distinto en cada capítulo.
              </span>

              {sugerencias.isPending ? (
                <div className="esqueleto" style={{ width: '60%' }} />
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                    gap: 8,
                    maxHeight: 200,
                    overflowY: 'auto',
                  }}
                >
                  {(sugerencias.data?.sugerencias ?? []).slice(0, 16).map((t) => (
                    <div
                      className="fila"
                      style={{ gap: 6, alignItems: 'center' }}
                      key={t.termino}
                    >
                      <span
                        className="chico num"
                        style={{ minWidth: 96, overflow: 'hidden', textOverflow: 'ellipsis' }}
                        title={`${t.apariciones} apariciones`}
                      >
                        {t.termino}
                      </span>
                      <span className="apagado">→</span>
                      <input
                        className="campo"
                        style={{ flex: 1, minWidth: 0, padding: '4px 7px', fontSize: 12 }}
                        placeholder="dejar como está"
                        aria-label={`Traducción de ${t.termino}`}
                        value={glosario[t.termino] ?? ''}
                        onChange={(e) => fijarTermino(t.termino, e.target.value)}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>

            {pedir.error && (
              <div className="aviso aviso-error" role="alert">
                <IconoAlerta />
                <span>{(pedir.error as Error).message}</span>
              </div>
            )}

            <div className="fila" style={{ gap: 10, alignItems: 'center' }}>
              <button
                type="button"
                className="boton boton-primario"
                disabled={pedir.isPending}
                onClick={enviar}
              >
                {pedir.isPending ? 'Encolando…' : `Traducir al ${idioma}`}
              </button>
              <button type="button" className="boton boton-chico" onClick={() => setAbierto(false)}>
                Cancelar
              </button>
              <span className="chico apagado">
                Se cobra por lo traducido. Podés seguir usando el motor mientras corre.
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
