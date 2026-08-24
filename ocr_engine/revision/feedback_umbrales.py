"""Análisis de feedback y recomendaciones de ajuste de umbrales.

Basado en decisiones humanas, recomienda ajustes a umbrales de confianza
en Capas 3-4 para reducir escalaciones innecesarias o mejorar calidad.
"""

from __future__ import annotations

from typing import Optional

class RecomendacionUmbral:
    """Recomendación de ajuste de umbral."""

    def __init__(
        self,
        tipo_bloque: str,
        capa: int,  # 3 o 4
        umbral_actual: float,
        umbral_recomendado: float,
        razon: str,
        impacto_esperado: str
    ):
        self.tipo_bloque = tipo_bloque
        self.capa = capa
        self.umbral_actual = umbral_actual
        self.umbral_recomendado = umbral_recomendado
        self.razon = razon
        self.impacto_esperado = impacto_esperado

    def __repr__(self) -> str:
        cambio = "↑" if self.umbral_recomendado > self.umbral_actual else "↓"
        return (
            f"{self.tipo_bloque} (Capa {self.capa}): "
            f"{self.umbral_actual:.2f} {cambio} {self.umbral_recomendado:.2f} "
            f"({self.impacto_esperado})"
        )


class AnalizadorFeedback:
    """Analiza decisiones humanas para mejorar umbrales."""

    def __init__(self, decisiones: list[dict]):
        self.decisiones = decisiones
        self.umbrales_actuales = {
            # Capa 3: OCR confidence thresholds
            "capa3_micro_segmento": 0.60,
            "capa3_parrafo": 0.75,
            "capa3_formula": 0.65,
            "capa3_tabla": 0.70,

            # Capa 4: Correction escalation thresholds
            "capa4_estructura_roota": 0.80,
            "capa4_inconsistencia": 1.00,  # Siempre escalar inconsistencias
        }

    def generar_recomendaciones(self) -> list[RecomendacionUmbral]:
        """Genera recomendaciones basadas en feedback."""

        if not self.decisiones:
            return []

        recomendaciones = []

        # Análisis por tipo de bloque
        tipos_analizados = set(d['tipo_bloque'] for d in self.decisiones)

        for tipo in tipos_analizados:
            decisiones_tipo = [d for d in self.decisiones if d['tipo_bloque'] == tipo]

            # Estadísticas
            tasa_rechazo = sum(1 for d in decisiones_tipo if d['decision'] == 'rechazar') / len(decisiones_tipo)
            tasa_escalacion = sum(1 for d in decisiones_tipo if d['decision'] == 'escalar') / len(decisiones_tipo)

            confianza_engine_promedio = sum(d['confianza_engine'] for d in decisiones_tipo) / len(decisiones_tipo)
            confianza_usuario_promedio = sum(d['confianza_usuario'] for d in decisiones_tipo) / len(decisiones_tipo)

            # Reglas de recomendación
            if tasa_rechazo > 0.3:  # >30% rechazados
                # Engine es demasiado optimista, subir umbral
                tipo_capa3 = f"capa3_{tipo.lower()}"
                umbral_actual = self.umbrales_actuales.get(tipo_capa3, 0.70)
                umbral_nuevo = min(0.95, umbral_actual + 0.10)

                recomendaciones.append(RecomendacionUmbral(
                    tipo_bloque=tipo,
                    capa=3,
                    umbral_actual=umbral_actual,
                    umbral_recomendado=umbral_nuevo,
                    razon=f"Tasa de rechazo alta ({tasa_rechazo:.1%})",
                    impacto_esperado="Menos falsos positivos"
                ))

            elif confianza_usuario_promedio > confianza_engine_promedio + 0.20:
                # Usuario confía más que engine, bajar umbral
                tipo_capa3 = f"capa3_{tipo.lower()}"
                umbral_actual = self.umbrales_actuales.get(tipo_capa3, 0.70)
                umbral_nuevo = max(0.50, umbral_actual - 0.05)

                recomendaciones.append(RecomendacionUmbral(
                    tipo_bloque=tipo,
                    capa=3,
                    umbral_actual=umbral_actual,
                    umbral_recomendado=umbral_nuevo,
                    razon=f"Confianza usuario > engine ({confianza_usuario_promedio:.2f} vs {confianza_engine_promedio:.2f})",
                    impacto_esperado="Menos escalaciones innecesarias"
                ))

            # Capa 4: Reparación estructural
            if tasa_escalacion > 0.2:  # >20% escalados
                recomendaciones.append(RecomendacionUmbral(
                    tipo_bloque=tipo,
                    capa=4,
                    umbral_actual=0.80,
                    umbral_recomendado=0.70,
                    razon=f"Alta tasa de escalación ({tasa_escalacion:.1%})",
                    impacto_esperado="Mejorar capacidad de reparación automática"
                ))

        return recomendaciones

    def obtener_resumen_mejoras(self) -> dict:
        """Resumen de mejoras identificadas."""

        if not self.decisiones:
            return {"total_decisiones": 0}

        aceptaciones_llm = sum(1 for d in self.decisiones if d['decision'] == 'aceptar' and d['confianza_llm'])
        rechazos_llm = sum(1 for d in self.decisiones if d['decision'] == 'rechazar' and d['confianza_llm'])

        # Confiabilidad de LLM
        if aceptaciones_llm + rechazos_llm > 0:
            tasa_acierto_llm = aceptaciones_llm / (aceptaciones_llm + rechazos_llm)
        else:
            tasa_acierto_llm = 0.0

        # Mejoras potenciales
        tipos_problematicos = self._identificar_tipos_problematicos()

        return {
            "total_decisiones": len(self.decisiones),
            "tasa_acierto_llm": tasa_acierto_llm,
            "tipos_problematicos": tipos_problematicos,
            "potencial_automatizacion": self._calcular_potencial_automatizacion()
        }

    def _identificar_tipos_problematicos(self) -> list[tuple[str, float]]:
        """Identifica tipos de bloque que causan más problemas."""

        problemas_por_tipo = {}

        for d in self.decisiones:
            tipo = d['tipo_bloque']
            es_problema = d['decision'] in ('rechazar', 'escalar', 'editar')

            if tipo not in problemas_por_tipo:
                problemas_por_tipo[tipo] = {"problemas": 0, "total": 0}

            problemas_por_tipo[tipo]["total"] += 1
            if es_problema:
                problemas_por_tipo[tipo]["problemas"] += 1

        # Calcular tasa de problemas
        resultado = []
        for tipo, stats in problemas_por_tipo.items():
            tasa = stats["problemas"] / stats["total"] if stats["total"] > 0 else 0
            resultado.append((tipo, tasa))

        # Retornar top 5
        return sorted(resultado, key=lambda x: x[1], reverse=True)[:5]

    def _calcular_potencial_automatizacion(self) -> float:
        """Calcula qué % adicional podría automatizarse con mejor modelo."""

        # Casos que fueron editados manualmente y podrían haberse evitado
        editados = [d for d in self.decisiones if d['decision'] == 'editar']

        if not editados:
            return 0.0

        # Si ediciones fueron pequeñas, podrían automatizarse
        ediciones_menores = sum(
            1 for d in editados
            if abs(len(d['contenido_final']) - len(d['contenido_original'])) < 50
        )

        potencial = (ediciones_menores / len(self.decisiones)) * 100

        return min(100.0, potencial)

    def mostrar_recomendaciones(self) -> None:
        """Muestra recomendaciones de forma legible."""

        recomendaciones = self.generar_recomendaciones()

        if not recomendaciones:
            print("\n[FEEDBACK] No hay recomendaciones de cambio.")
            return

        print(f"\n{'='*80}")
        print("RECOMENDACIONES DE AJUSTE DE UMBRALES")
        print(f"{'='*80}\n")

        for i, rec in enumerate(recomendaciones, 1):
            print(f"{i}. {rec}")
            print(f"   Razón: {rec.razon}")
            print(f"   Impacto: {rec.impacto_esperado}\n")

    def mostrar_resumen_mejoras(self) -> None:
        """Muestra resumen de mejoras potenciales."""

        resumen = self.obtener_resumen_mejoras()

        print(f"\n{'='*80}")
        print("ANÁLISIS DE MEJORAS")
        print(f"{'='*80}\n")

        print(f"Total de decisiones: {resumen['total_decisiones']}")
        print(f"Tasa de acierto LLM: {resumen['tasa_acierto_llm']:.1%}")
        print(f"Potencial de automatización: {resumen['potencial_automatizacion']:.1f}%\n")

        if resumen['tipos_problematicos']:
            print("Tipos de bloque más problemáticos:")
            for tipo, tasa_problema in resumen['tipos_problematicos']:
                print(f"  - {tipo}: {tasa_problema:.1%} con problemas")
