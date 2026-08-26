/** Descarga del documento convertido.
 *
 * LaTeX y Markdown van primero y con más peso visual porque son los formatos
 * principales del producto: quien convierte un paper matemático normalmente
 * quiere seguir trabajándolo, no sólo leerlo. El cuaderno queda como opción para
 * quien escribe código sobre lo convertido, y Graphify es la salida que consume
 * el indexador, no algo que alguien abra a mano.
 *
 * Lo que se descarga lleva aplicadas las correcciones de la revisión humana. Se
 * dice explícitamente: si no, no hay forma de saber si revisar sirvió de algo.
 */

import { useState } from 'react'

import { useExportar } from '../api/consultas'
import type { FormatoExport } from '../api/tipos'
import { IconoAlerta } from './Iconos'

type Opcion = {
  formato: FormatoExport
  nombre: string
  extension: string
  para: string
  principal: boolean
}

const OPCIONES: Opcion[] = [
  {
    formato: 'latex',
    nombre: 'LaTeX',
    extension: '.tex',
    para: 'Compilable, con los teoremas en sus entornos de amsthm.',
    principal: true,
  },
  {
    formato: 'markdown',
    nombre: 'Markdown',
    extension: '.md',
    para: 'Para Obsidian, un repositorio o cualquier editor de texto.',
    principal: true,
  },
  {
    formato: 'ipynb',
    nombre: 'Cuaderno Jupyter',
    extension: '.ipynb',
    para: 'Los bloques de código quedan como celdas ejecutables.',
    principal: false,
  },
  {
    formato: 'graphify',
    nombre: 'Graphify',
    extension: '.json',
    para: 'Los bloques con su metadata, para indexar el grafo.',
    principal: false,
  },
]

export default function Exportar({
  documentoId,
  titulo,
  listo,
}: {
  documentoId: string
  titulo: string
  /** Un documento a medio procesar no tiene todos sus bloques todavía. */
  listo: boolean
}) {
  const exportar = useExportar()
  const [ultimo, setUltimo] = useState<FormatoExport | null>(null)

  const descargar = (formato: FormatoExport) => {
    setUltimo(formato)
    exportar.mutate({ documentoId, titulo, formato })
  }

  const principales = OPCIONES.filter((o) => o.principal)
  const secundarias = OPCIONES.filter((o) => !o.principal)

  return (
    <div className="tarjeta" style={{ padding: '18px 20px' }}>
      <div className="columna" style={{ gap: 14 }}>
        <div className="columna" style={{ gap: 3 }}>
          <span className="etiqueta">Descargar</span>
          <span className="chico apagado">
            Incluye las correcciones que hayas hecho en la revisión.
          </span>
        </div>

        {!listo ? (
          <span className="apagado chico">
            Disponible cuando el documento termine de procesarse.
          </span>
        ) : (
          <>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                gap: 10,
              }}
            >
              {principales.map((o) => (
                <button
                  key={o.formato}
                  className="boton boton-primario"
                  disabled={exportar.isPending}
                  onClick={() => descargar(o.formato)}
                  style={{
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    gap: 3,
                    padding: '11px 14px',
                    height: 'auto',
                    textAlign: 'left',
                  }}
                >
                  <span style={{ fontWeight: 600 }}>
                    {exportar.isPending && ultimo === o.formato
                      ? 'Preparando…'
                      : `${o.nombre} ${o.extension}`}
                  </span>
                  <span className="chico" style={{ opacity: 0.85, fontWeight: 400 }}>
                    {o.para}
                  </span>
                </button>
              ))}
            </div>

            <div className="columna" style={{ gap: 8 }}>
              <span className="chico apagado">También</span>
              <div className="fila" style={{ gap: 8, flexWrap: 'wrap' }}>
                {secundarias.map((o) => (
                  <button
                    key={o.formato}
                    className="boton boton-chico"
                    disabled={exportar.isPending}
                    onClick={() => descargar(o.formato)}
                    title={o.para}
                  >
                    {exportar.isPending && ultimo === o.formato
                      ? 'Preparando…'
                      : `${o.nombre} ${o.extension}`}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {exportar.error && (
          <div className="aviso aviso-error" role="alert">
            <IconoAlerta />
            <span>
              {(exportar.error as { codigo?: string }).codigo === 'sin_bloques'
                ? 'Este documento se procesó antes de que se guardaran los bloques. Hay que volver a subirlo.'
                : (exportar.error as Error).message}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
