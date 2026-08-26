/** Consumo de la instancia.
 *
 * La pregunta que tiene que contestar no es "cuánto se gastó" sino "de dónde
 * salió ese gasto", porque el costo del motor no es parejo: un documento
 * escaneado con mucho ruido escala muchos bloques al modelo y uno nativo no
 * escala ninguno. Por eso el desglose por documento pesa más que el total, y la
 * serie diaria está para ver si algo se disparó un día puntual.
 */

import { useConsumo } from '../api/consultas'
import { IconoAlerta } from '../componentes/Iconos'

export default function Consumo() {
  const { data, isPending, error } = useConsumo()

  const totales = data?.totales
  const serie = data?.serie_diaria ?? []
  const maximoDia = Math.max(
    ...serie.map((d) => d.micro_segmento_usd + d.inconsistencia_documental_usd),
    0.000001,
  )

  const indicadores = [
    { etiqueta: 'Documentos', valor: totales?.documentos ?? 0, nota: 'en el período' },
    { etiqueta: 'Páginas', valor: totales?.paginas ?? 0, nota: 'la unidad de facturación' },
    { etiqueta: 'Llamadas al modelo', valor: totales?.llamadas_llm ?? 0, nota: 'sólo bloques ambiguos' },
    {
      etiqueta: 'Costo del modelo',
      valor: `$${(totales?.costo_llm_usd ?? 0).toFixed(4)}`,
      nota: 'atribuido por bloque',
    },
  ]

  return (
    <>
      <div className="cabecera-pagina">
        <h1>Consumo</h1>
        <div className="crece" />
        {data && (
          <span className="chico apagado">
            {data.desde} — {data.hasta}
          </span>
        )}
      </div>

      {error && (
        <div className="aviso aviso-error" role="alert" style={{ marginBottom: 18 }}>
          <IconoAlerta />
          <span>{(error as Error).message}</span>
        </div>
      )}

      <div className="rejilla-kpi" style={{ marginBottom: 20 }}>
        {indicadores.map((i) => (
          <div className="tarjeta kpi" key={i.etiqueta}>
            <span className="etiqueta">{i.etiqueta}</span>
            {isPending ? (
              <div className="esqueleto" style={{ width: '55%', height: 22 }} />
            ) : (
              <span className="valor">
                {typeof i.valor === 'number' ? i.valor.toLocaleString('es') : i.valor}
              </span>
            )}
            <span className="nota">{i.nota}</span>
          </div>
        ))}
      </div>

      {/* ---- serie diaria ---- */}
      <div className="tarjeta" style={{ padding: '18px 20px', marginBottom: 20 }}>
        <div className="columna" style={{ gap: 14 }}>
          <div className="columna" style={{ gap: 3 }}>
            <span className="etiqueta">Gasto por día</span>
            <span className="chico apagado">
              Corrección de fragmentos e inconsistencias del documento, por separado.
            </span>
          </div>

          {isPending ? (
            <div className="esqueleto" style={{ width: '70%', height: 60 }} />
          ) : serie.length === 0 ? (
            <span className="apagado chico">
              Sin gasto en el período. Los documentos nativos digitales no escalan al
              modelo, así que salen gratis.
            </span>
          ) : (
            <div className="fila" style={{ gap: 4, alignItems: 'flex-end', height: 90 }}>
              {serie.map((d) => {
                const total = d.micro_segmento_usd + d.inconsistencia_documental_usd
                const alto = Math.max((total / maximoDia) * 76, 2)
                return (
                  <div
                    key={d.fecha}
                    className="columna"
                    style={{ gap: 4, alignItems: 'center', flex: 1, minWidth: 14 }}
                    title={`${d.fecha}: $${total.toFixed(5)}`}
                  >
                    <div
                      style={{
                        width: '100%',
                        height: alto,
                        borderRadius: '2px 2px 0 0',
                        background: 'var(--acento, #4F4CDE)',
                        opacity: 0.85,
                      }}
                    />
                    <span className="chico apagado" style={{ fontSize: 10 }}>
                      {d.fecha.slice(8)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* ---- desglose por documento ---- */}
      <div className="tarjeta" style={{ padding: '18px 20px' }}>
        <div className="columna" style={{ gap: 14 }}>
          <div className="columna" style={{ gap: 3 }}>
            <span className="etiqueta">Qué documento costó qué</span>
            <span className="chico apagado">
              De mayor a menor. Los escaneados con ruido son los que más escalan.
            </span>
          </div>

          {isPending ? (
            <div className="esqueleto" style={{ width: '80%' }} />
          ) : (data?.por_documento.length ?? 0) === 0 ? (
            <span className="apagado chico">
              Ningún documento del período generó llamadas al modelo.
            </span>
          ) : (
            <div className="marco-tabla">
              <table>
                <thead>
                  <tr>
                    <th>Documento</th>
                    <th style={{ textAlign: 'right' }}>Llamadas</th>
                    <th style={{ textAlign: 'right' }}>Tokens</th>
                    <th style={{ textAlign: 'right' }}>Costo</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.por_documento.map((d) => (
                    <tr key={d.documento_id}>
                      <td>{d.titulo}</td>
                      <td className="num" style={{ textAlign: 'right' }}>
                        {d.llamadas.toLocaleString('es')}
                      </td>
                      <td className="num" style={{ textAlign: 'right' }}>
                        {(d.tokens_entrada + d.tokens_salida).toLocaleString('es')}
                      </td>
                      <td className="num" style={{ textAlign: 'right' }}>
                        ${d.costo_usd.toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {totales && totales.paginas > 0 && (
            <span className="chico apagado">
              Promedio: ${(totales.costo_llm_usd / totales.paginas).toFixed(5)} por página
              procesada.
            </span>
          )}
        </div>
      </div>
    </>
  )
}
