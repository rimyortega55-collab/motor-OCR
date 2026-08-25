/** Umbrales de confianza y auto-ajuste.
 *
 * Los umbrales deciden qué bloque se escala al modelo y cuál va a revisión
 * humana, así que moverlos cambia el costo del documento: subirlos escala más y
 * gasta más; bajarlos manda más trabajo a la persona. La pantalla lo dice en vez
 * de presentar los deslizadores como una preferencia inocua.
 *
 * Las recomendaciones se calculan sin aplicarse, para poder verlas antes de
 * decidir. `validacion` llega en null a propósito y por eso acá no se dibuja
 * ningún "mejoró un 4%": el motor todavía no valida contra un lote real, e
 * inventar ese número sería peor que no mostrarlo.
 */

import { useEffect, useState } from 'react'

import {
  useAplicarRecomendaciones,
  useGuardarUmbrales,
  useRecomendaciones,
  useUmbrales,
} from '../api/consultas'
import { IconoAlerta } from '../componentes/Iconos'

/** Qué significa cada umbral, en palabras de quien lo va a mover. */
const EXPLICACION: Record<string, string> = {
  umbral_confianza_engine: 'Piso que le exigimos al motor de OCR.',
  umbral_confianza_estructural: 'Piso tras validar la estructura del bloque.',
  umbral_confianza_global_escalacion: 'Por debajo de esto, el bloque va a revisión.',
  umbral_escalacion_micro_segmento: 'Por debajo de esto, el fragmento se escala al modelo.',
  estructura_rota: 'Cuándo se considera que la estructura no se pudo reparar.',
  inconsistencia: 'En 1.00 toda inconsistencia se escala siempre.',
}

function Deslizador({
  clave,
  valor,
  onCambio,
}: {
  clave: string
  valor: number
  onCambio: (valor: number) => void
}) {
  return (
    <div className="columna" style={{ gap: 4 }}>
      <div className="fila" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 13 }}>{clave.replace(/_/g, ' ')}</span>
        <span className="num" style={{ fontSize: 13, fontWeight: 600 }}>
          {valor.toFixed(2)}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={valor}
        aria-label={clave.replace(/_/g, ' ')}
        onChange={(e) => onCambio(Number(e.target.value))}
        style={{ width: '100%' }}
      />
      {EXPLICACION[clave] && (
        <span className="chico apagado">{EXPLICACION[clave]}</span>
      )}
    </div>
  )
}

export default function Umbrales() {
  const { data, isPending, error } = useUmbrales()
  const guardar = useGuardarUmbrales()
  const recomendaciones = useRecomendaciones()
  const aplicar = useAplicarRecomendaciones()

  // Copia local para que el deslizador se mueva sin esperar al servidor. Se
  // siembra cuando llegan los datos y no en cada render, o el arrastre se
  // reiniciaría con cada respuesta.
  const [borrador, setBorrador] = useState<Record<string, Record<string, number>> | null>(null)

  useEffect(() => {
    if (data && borrador === null) {
      setBorrador({
        capa3: { ...data.capa3 },
        capa4: { ...data.capa4 },
        globales: { ...data.globales },
      })
    }
  }, [data, borrador])

  const cambiar = (ambito: string, clave: string, valor: number) =>
    setBorrador((previo) =>
      previo ? { ...previo, [ambito]: { ...previo[ambito], [clave]: valor } } : previo,
    )

  const haCambiado =
    data !== undefined &&
    borrador !== null &&
    JSON.stringify(borrador) !==
      JSON.stringify({ capa3: data.capa3, capa4: data.capa4, globales: data.globales })

  const aplicables = (recomendaciones.data?.recomendaciones ?? []).filter((r) => r.aplicable)

  return (
    <>
      <div className="cabecera-pagina">
        <h1>Umbrales</h1>
        <div className="crece" />
        {data?.actualizado_en && (
          <span className="chico apagado">
            editado {new Date(data.actualizado_en).toLocaleString('es')}
          </span>
        )}
      </div>

      {error && (
        <div className="aviso aviso-error" role="alert" style={{ marginBottom: 18 }}>
          <IconoAlerta />
          <span>{(error as Error).message}</span>
        </div>
      )}

      <div className="aviso" style={{ marginBottom: 20 }}>
        <span className="tenue" style={{ display: 'flex', flexShrink: 0 }}>
          <IconoAlerta />
        </span>
        <div className="columna" style={{ gap: 5 }}>
          <strong style={{ fontSize: 13 }}>Mover esto cambia lo que gastás</strong>
          <span className="apagado chico">
            Un umbral más alto manda más bloques al modelo: mejor resultado, más costo.
            Uno más bajo deja más trabajo para tu revisión. Son tuyos: no afectan a
            ninguna otra cuenta.
          </span>
        </div>
      </div>

      {/* ---- recomendaciones ---- */}
      <div className="tarjeta" style={{ padding: '18px 20px', marginBottom: 20 }}>
        <div className="columna" style={{ gap: 12 }}>
          <div className="fila" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span className="etiqueta">Lo que sugieren tus revisiones</span>
            <span className="chico apagado">
              {recomendaciones.data?.decisiones_analizadas ?? 0} decisiones analizadas
            </span>
          </div>

          {recomendaciones.isPending ? (
            <div className="esqueleto" style={{ width: '60%' }} />
          ) : aplicables.length === 0 ? (
            <span className="apagado chico">
              {(recomendaciones.data?.decisiones_analizadas ?? 0) === 0
                ? 'Todavía no revisaste bloques. Cuando aceptes o corrijas algunos, el motor propone ajustes a partir de eso.'
                : 'Nada que ajustar por ahora: tus decisiones coinciden con lo que el motor ya hace.'}
            </span>
          ) : (
            <>
              <div className="columna" style={{ gap: 10 }}>
                {aplicables.map((r) => (
                  <div
                    key={`${r.ambito}-${r.clave}`}
                    className="fila"
                    style={{ gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}
                  >
                    <span className="pildora">{r.clave}</span>
                    <span className="num" style={{ fontSize: 13 }}>
                      {r.actual.toFixed(2)} → <strong>{r.propuesto.toFixed(2)}</strong>
                    </span>
                    <span className="chico apagado crece">{r.razon}</span>
                  </div>
                ))}
              </div>

              <div className="fila" style={{ gap: 10, alignItems: 'center' }}>
                <button
                  className="boton boton-primario boton-chico"
                  disabled={aplicar.isPending}
                  onClick={() => aplicar.mutate(aplicables.map((r) => r.clave))}
                >
                  {aplicar.isPending ? 'Aplicando…' : `Aplicar ${aplicables.length}`}
                </button>
                <span className="chico apagado">
                  Se aplican sobre tus umbrales; podés volver a moverlos a mano.
                </span>
              </div>
            </>
          )}

          {aplicar.data?.status === 'ok' && (
            <span className="chico" style={{ color: 'var(--bien, inherit)' }}>
              {aplicar.data.cambios_aplicados} umbral(es) actualizado(s).
            </span>
          )}
        </div>
      </div>

      {/* ---- deslizadores ---- */}
      {isPending || borrador === null ? (
        <div className="tarjeta" style={{ padding: '18px 20px' }}>
          <div className="esqueleto" style={{ width: '70%', height: 18 }} />
        </div>
      ) : (
        <div className="columna" style={{ gap: 16 }}>
          {(
            [
              ['capa3', 'Por tipo de bloque (Capa 3)', 'Qué confianza le exigimos al OCR según qué sea el bloque.'],
              ['capa4', 'Corrección (Capa 4)', 'Cuándo una inconsistencia del documento se escala.'],
              ['globales', 'Globales', 'Los que valen para todo el pipeline.'],
            ] as const
          ).map(([ambito, titulo, bajada]) => (
            <div className="tarjeta" style={{ padding: '18px 20px' }} key={ambito}>
              <div className="columna" style={{ gap: 14 }}>
                <div className="columna" style={{ gap: 3 }}>
                  <span className="etiqueta">{titulo}</span>
                  <span className="chico apagado">{bajada}</span>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))',
                    gap: 18,
                  }}
                >
                  {Object.entries(borrador[ambito]).map(([clave, valor]) => (
                    <Deslizador
                      key={clave}
                      clave={clave}
                      valor={valor}
                      onCambio={(v) => cambiar(ambito, clave, v)}
                    />
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ---- guardar ---- */}
      {haCambiado && borrador && (
        <div
          className="fila"
          style={{ gap: 12, alignItems: 'center', marginTop: 18, flexWrap: 'wrap' }}
        >
          <button
            className="boton boton-primario"
            disabled={guardar.isPending}
            onClick={() => guardar.mutate(borrador)}
          >
            {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
          <button
            className="boton boton-chico"
            onClick={() =>
              setBorrador(
                data
                  ? { capa3: { ...data.capa3 }, capa4: { ...data.capa4 }, globales: { ...data.globales } }
                  : null,
              )
            }
          >
            Descartar
          </button>
          <span className="chico apagado">
            Se aplican a los documentos que subas de ahora en adelante.
          </span>
        </div>
      )}

      {guardar.error && (
        <div className="aviso aviso-error" role="alert" style={{ marginTop: 14 }}>
          <IconoAlerta />
          <span>{(guardar.error as Error).message}</span>
        </div>
      )}
    </>
  )
}
