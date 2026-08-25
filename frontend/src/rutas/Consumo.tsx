/** Consumo del usuario.
 *
 * Muestra lo que el endpoint devuelve hoy: totales. La serie diaria y el
 * desglose por documento son parte del paso 5 del contrato, y en vez de
 * dibujarlos con datos inventados se dice que faltan.
 */

import { useConsumo } from '../api/consultas'
import { IconoAlerta } from '../componentes/Iconos'

export default function Consumo() {
  const { data, isPending, error } = useConsumo()

  const indicadores = [
    { etiqueta: 'Documentos', valor: data?.documentos_procesados ?? 0, nota: 'procesados en total' },
    { etiqueta: 'Páginas', valor: data?.paginas_procesadas ?? 0, nota: 'la unidad de facturación' },
    { etiqueta: 'Llamadas al modelo', valor: data?.llamadas_llm ?? 0, nota: 'sólo bloques ambiguos' },
    {
      etiqueta: 'Costo acumulado',
      valor: `$${(data?.costo_llm_usd ?? 0).toFixed(4)}`,
      nota: 'atribuido por bloque',
    },
  ]

  return (
    <>
      <div className="cabecera-pagina">
        <h1>Consumo</h1>
        <div className="crece" />
        {data && <span className="pildora">plan {data.plan}</span>}
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

      <div className="tarjeta" style={{ padding: '18px 20px', marginBottom: 20 }}>
        <div className="columna" style={{ gap: 12 }}>
          <span className="etiqueta">Tokens</span>
          {isPending ? (
            <div className="esqueleto" style={{ width: '45%' }} />
          ) : (
            <div className="fila" style={{ gap: 32, flexWrap: 'wrap' }}>
              <div className="columna" style={{ gap: 2 }}>
                <span className="num" style={{ fontSize: 19, fontWeight: 600 }}>
                  {(data?.tokens_entrada ?? 0).toLocaleString('es')}
                </span>
                <span className="chico apagado">de entrada</span>
              </div>
              <div className="columna" style={{ gap: 2 }}>
                <span className="num" style={{ fontSize: 19, fontWeight: 600 }}>
                  {(data?.tokens_salida ?? 0).toLocaleString('es')}
                </span>
                <span className="chico apagado">de salida</span>
              </div>
              <div className="columna" style={{ gap: 2 }}>
                <span className="num" style={{ fontSize: 19, fontWeight: 600 }}>
                  {data && data.paginas_procesadas > 0
                    ? `$${(data.costo_llm_usd / data.paginas_procesadas).toFixed(5)}`
                    : '—'}
                </span>
                <span className="chico apagado">costo por página</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="aviso">
        <span className="tenue" style={{ display: 'flex', flexShrink: 0 }}>
          <IconoAlerta />
        </span>
        <div className="columna" style={{ gap: 5 }}>
          <strong style={{ fontSize: 13 }}>Todavía no hay serie diaria ni desglose</strong>
          <span className="apagado chico">
            El endpoint <code>GET /consumo</code> devuelve totales. El gráfico por día, el
            desglose por documento y los límites del plan llegan cuando se implemente la
            sección 9 del contrato. Los datos ya están en la base: falta la consulta que los
            agrupe.
          </span>
        </div>
      </div>
    </>
  )
}
