"""Gestión persistente de decisiones de revisión humana.

Almacena todas las decisiones en JSON (append-only) para:
- Trazabilidad completa de correcciones
- Análisis de patrones (qué tipos escalan más)
- Retroalimentación a LLM
- Auditoría
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from uuid import UUID
from typing import Optional

class DecisionRevision:
    """Decisión de revisión humana de un bloque."""

    def __init__(
        self,
        bloque_id: UUID,
        documento_id: UUID,
        pagina: int,
        tipo_bloque: str,
        decision: str,  # "aceptar", "rechazar", "editar", "escalar", "saltar"
        contenido_original: str,
        contenido_final: str,
        confianza_engine: float,
        confianza_llm: Optional[float] = None,
        confianza_usuario: float = 0.5,
        comentarios: str = "",
        revisor: str = "anonimo"
    ):
        self.timestamp = datetime.utcnow().isoformat()
        self.bloque_id = str(bloque_id)
        self.documento_id = str(documento_id)
        self.pagina = pagina
        self.tipo_bloque = tipo_bloque
        self.decision = decision
        self.contenido_original = contenido_original[:500]  # Truncar
        self.contenido_final = contenido_final[:500]
        self.confianza_engine = confianza_engine
        self.confianza_llm = confianza_llm
        self.confianza_usuario = confianza_usuario
        self.comentarios = comentarios[:200]
        self.revisor = revisor

    def a_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "bloque_id": self.bloque_id,
            "documento_id": self.documento_id,
            "pagina": self.pagina,
            "tipo_bloque": self.tipo_bloque,
            "decision": self.decision,
            "contenido_original": self.contenido_original,
            "contenido_final": self.contenido_final,
            "confianza_engine": self.confianza_engine,
            "confianza_llm": self.confianza_llm,
            "confianza_usuario": self.confianza_usuario,
            "comentarios": self.comentarios,
            "revisor": self.revisor,
        }

    def cambio_contenido(self) -> bool:
        """¿Se cambió el contenido?"""
        return self.contenido_original != self.contenido_final


class GestorDecisiones:
    """Gestiona decisiones de revisión."""

    def __init__(self, ruta_archivo: str | Path = "decisiones_revision.jsonl"):
        self.ruta = Path(ruta_archivo)
        self._decisiones_cache = []
        self._cargar_existentes()

    def _cargar_existentes(self) -> None:
        """Carga decisiones existentes del archivo."""
        if self.ruta.exists():
            try:
                with open(self.ruta, "r") as f:
                    for linea in f:
                        if linea.strip():
                            self._decisiones_cache.append(json.loads(linea))
            except Exception as e:
                print(f"[REVISIÓN] Error cargando decisiones: {e}")

    def registrar_decision(self, decision: DecisionRevision) -> None:
        """Registra una decisión (append-only)."""
        self._decisiones_cache.append(decision.a_dict())

        # Escribir a archivo
        try:
            with open(self.ruta, "a") as f:
                f.write(json.dumps(decision.a_dict()) + "\n")
        except Exception as e:
            print(f"[REVISIÓN] Error escribiendo decisión: {e}")

    def obtener_estadisticas(self, documento_id: str = None) -> dict:
        """Obtiene estadísticas de decisiones."""

        decisiones = self._decisiones_cache
        if documento_id:
            decisiones = [d for d in decisiones if d['documento_id'] == documento_id]

        if not decisiones:
            return {
                "total": 0,
                "por_decision": {},
                "por_tipo_bloque": {},
                "tasa_cambio": 0.0,
                "confianza_promedio_usuario": 0.0,
            }

        # Contar por tipo de decisión
        por_decision = {}
        for d in decisiones:
            decision = d['decision']
            por_decision[decision] = por_decision.get(decision, 0) + 1

        # Contar por tipo de bloque
        por_tipo_bloque = {}
        for d in decisiones:
            tipo = d['tipo_bloque']
            por_tipo_bloque[tipo] = por_tipo_bloque.get(tipo, 0) + 1

        # Tasa de cambio (editar + rechazar)
        cambios = sum(1 for d in decisiones if d['contenido_original'] != d['contenido_final'])
        tasa_cambio = (100 * cambios / len(decisiones)) if decisiones else 0

        # Confianza promedio del usuario
        confianza_promedio = sum(d['confianza_usuario'] for d in decisiones) / len(decisiones)

        return {
            "total": len(decisiones),
            "por_decision": por_decision,
            "por_tipo_bloque": por_tipo_bloque,
            "tasa_cambio": tasa_cambio,
            "confianza_promedio_usuario": confianza_promedio,
        }

    def obtener_patrones(self) -> dict:
        """Analiza patrones en las decisiones."""

        if not self._decisiones_cache:
            return {}

        # Tipos que se rechazan más frecuentemente
        rechazos_por_tipo = {}
        para_escalar_por_tipo = {}

        for d in self._decisiones_cache:
            tipo = d['tipo_bloque']

            if d['decision'] == 'rechazar':
                rechazos_por_tipo[tipo] = rechazos_por_tipo.get(tipo, 0) + 1

            elif d['decision'] == 'escalar':
                para_escalar_por_tipo[tipo] = para_escalar_por_tipo.get(tipo, 0) + 1

        # Ordenar por frecuencia
        rechazos_ordenados = sorted(
            rechazos_por_tipo.items(), key=lambda x: x[1], reverse=True
        )
        escalaciones_ordenadas = sorted(
            para_escalar_por_tipo.items(), key=lambda x: x[1], reverse=True
        )

        return {
            "tipos_rechazados_frecuentemente": rechazos_ordenados[:5],
            "tipos_escalados_frecuentemente": escalaciones_ordenadas[:5],
            "confianza_engines_baja": self._tipos_con_baja_confianza()
        }

    def _tipos_con_baja_confianza(self) -> list[tuple[str, float]]:
        """Encuentra tipos de bloque con baja confianza promedio del engine."""

        confianzas_por_tipo = {}
        cuentas_por_tipo = {}

        for d in self._decisiones_cache:
            tipo = d['tipo_bloque']
            conf_engine = d['confianza_engine']

            confianzas_por_tipo[tipo] = confianzas_por_tipo.get(tipo, 0) + conf_engine
            cuentas_por_tipo[tipo] = cuentas_por_tipo.get(tipo, 0) + 1

        resultado = []
        for tipo in confianzas_por_tipo:
            conf_promedio = confianzas_por_tipo[tipo] / cuentas_por_tipo[tipo]
            if conf_promedio < 0.7:  # Baja confianza
                resultado.append((tipo, conf_promedio))

        return sorted(resultado, key=lambda x: x[1])

    def obtener_decisiones_filtradas(
        self,
        documento_id: str = None,
        tipo_bloque: str = None,
        decision: str = None
    ) -> list[dict]:
        """Obtiene decisiones filtradas."""

        resultado = self._decisiones_cache

        if documento_id:
            resultado = [d for d in resultado if d['documento_id'] == documento_id]

        if tipo_bloque:
            resultado = [d for d in resultado if d['tipo_bloque'] == tipo_bloque]

        if decision:
            resultado = [d for d in resultado if d['decision'] == decision]

        return resultado

    def exportar_csv(self, ruta_salida: str | Path) -> None:
        """Exporta decisiones a CSV para análisis."""

        import csv

        try:
            with open(ruta_salida, "w", newline="") as f:
                if self._decisiones_cache:
                    writer = csv.DictWriter(f, fieldnames=self._decisiones_cache[0].keys())
                    writer.writeheader()
                    writer.writerows(self._decisiones_cache)

                    print(f"[REVISIÓN] Exportado a {ruta_salida}")
        except Exception as e:
            print(f"[REVISIÓN] Error exportando CSV: {e}")

    def limpiar(self) -> None:
        """Limpia caché (para testing)."""
        self._decisiones_cache = []
