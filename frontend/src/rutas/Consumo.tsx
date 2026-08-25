/** Consumo del usuario.
 *
 * La pregunta que tiene que contestar no es "cuánto gasté" sino "de dónde salió
 * ese gasto", porque el costo del motor no es parejo: un documento escaneado con
 * mucho ruido escala muchos bloques al modelo y uno nativo no escala ninguno. Por
 * eso el desglose por documento pesa más que el total, y la serie diaria está
 * para ver si algo se disparó un día puntual.
 */

import { useConsumo } from '../api/consultas'
import { IconoAlerta } from '../componentes/Iconos'

/** Barra de uso contra el tope del plan. Null = plan sin tope. */
function Barra({ usado, tope }: { usado: number; tope: number | null }) {
  if (tope === null) {
    return <span className="chico apagado">sin tope en este plan</span>
  }

  const proporcion = Math.min(usado / tope, 1)
  const apretado = proporcion >= 0.8

  return (
    <div className="columna" style={{ gap: 4 }}>
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: 'var(--linea, rgba(128,128,128,.2))',
          overflow: 'hidden',
        }}
        role="progressbar"
        aria-valuenow={Math.round(proporcion * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          style={{
            width: `${proporcion * 100}%`,
            height: '100%',
            background: apretado ? 'var(--alerta, #A8551A)' : 'var(--acento, #4F4CDE)',
          }}
        />
      </div>
      <span className="chico apagado">
        {usado.toLocaleString('es')} de {tope.toLocaleString('es')}
      </span>
    </div>
  )
}

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
          <div className="fila" style={{ gap: 10, alignItems: 'center' }}>
            <span className="chico apagado">
              {data.desde} — {data.hasta}
            </span>
            <span className="pildora">plan {data.plan}</span>
          </div>
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

      {/* ---- límites del plan ---- */}
      {data && (
        <div className="tarjeta" style={{ padding: '18px 20px', marginBottom: 20 }}>
          <div className="columna" style={{ gap: 14 }}>
            <span className="etiqueta">Tu plan este mes</span>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 20,
              }}
            >
              <div className="columna" style={{ gap: 6 }}>
                <span className="chico">Páginas</span>
                <Barra usado={totales?.paginas ?? 0} tope={data.limites.paginas_mes} />
              </div>
              <div className="columna" style={{ gap: 6 }}>
                <span className="chico">Gasto en el modelo</span>
                {data.limites.gasto_llm_mes_usd === null ? (
                  <span className="chico apagado">sin tope en este plan</span>
                ) : (
                  <div className="columna" style={{ gap: 4 }}>
                    <Barra
                      usado={Math.round((totales?.costo_llm_usd ?? 0) * 10000)}
                      tope={Math.round(data.limites.gasto_llm_mes_usd * 10000)}
                    />
                    <span className="chico apagado">
                      ${(totales?.costo_llm_usd ?? 0).toFixed(4)} de $
                      {data.limites.gasto_llm_mes_usd.toFixed(2)}
                    </span>
                  </div>
                )}
              </div>
            </div>
            <span className="chico apagado">
              Al superar cualquiera de los dos, las subidas se rechazan hasta el mes
              siguiente.
            </span>
          </div>
        </div>
      )}

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
