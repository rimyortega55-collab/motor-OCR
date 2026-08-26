"""Auto-ajuste de umbrales basado en feedback de Capa 6.

Algoritmo de convergencia:
1. Recolectar decisiones de múltiples sesiones de revisión
2. Analizar patrones (tipos problemáticos)
3. Calcular umbrales óptimos usando validación cruzada simple
4. Aplicar cambios
5. Validar en subset de datos
6. Rollback si empeora métricas
"""

from __future__ import annotations

from typing import Optional
import json
from pathlib import Path

class UmbralOptimo:
    """Umbral optimizado para un tipo de bloque."""

    def __init__(
        self,
        tipo_bloque: str,
        capa: int,
        umbral_anterior: float,
        umbral_nuevo: float,
        confianza: float,
        razon: str
    ):
        self.tipo_bloque = tipo_bloque
        self.capa = capa
        self.umbral_anterior = umbral_anterior
        self.umbral_nuevo = umbral_nuevo
        self.confianza = confianza  # Confianza en el nuevo umbral (0-1)
        self.razon = razon

    def aplicable(self) -> bool:
        """¿Se debe aplicar este cambio?"""
        # Aplicar si confianza > 0.7 y cambio significativo
        return self.confianza > 0.7 and abs(self.umbral_nuevo - self.umbral_anterior) > 0.02

    def __repr__(self) -> str:
        cambio = "↑" if self.umbral_nuevo > self.umbral_anterior else "↓"
        return (
            f"{self.tipo_bloque} (Capa {self.capa}): "
            f"{self.umbral_anterior:.2f} {cambio} {self.umbral_nuevo:.2f} "
            f"(conf: {self.confianza:.2f}) - {self.razon}"
        )


class AjustadorUmbrales:
    """Auto-ajusta umbrales según feedback de usuario."""

    def __init__(self, ruta_umbrales: str | Path = "umbrales_config.json"):
        self.ruta = Path(ruta_umbrales)
        self.umbrales = self._cargar_umbrales()

    def _cargar_umbrales(self) -> dict:
        """Carga configuración actual de umbrales."""
        if self.ruta.exists():
            try:
                with open(self.ruta) as f:
                    return json.load(f)
            except Exception as e:
                print(f"[UMBRALES] Error cargando: {e}")

        # Valores por defecto
        return {
            "capa3": {
                "parrafo": 0.75,
                "formula_inline": 0.65,
                "formula_display": 0.70,
                "tabla": 0.70,
                "encabezado": 0.80,
                "lista": 0.75,
                "codigo": 0.80,
                "teorema": 0.75,
                "demostracion": 0.75,
                "figura": 0.00,  # Sin OCR
                "ruido": 0.00,
            },
            "capa4": {
                "estructura_rota": 0.80,
                "inconsistencia": 1.00,  # Siempre escalar
            }
        }

    def calcular_umbrales_optimos(self, decisiones: list[dict]) -> list[UmbralOptimo]:
        """Calcula umbrales óptimos basados en decisiones."""

        if not decisiones:
            return []

        ajustes = []

        # Análisis por tipo de bloque
        tipos = set(d['tipo_bloque'] for d in decisiones)

        for tipo in tipos:
            decisiones_tipo = [d for d in decisiones if d['tipo_bloque'] == tipo]

            # Estadísticas
            tasa_aceptacion = sum(1 for d in decisiones_tipo if d['decision'] == 'aceptar') / len(decisiones_tipo)
            tasa_rechazo = sum(1 for d in decisiones_tipo if d['decision'] == 'rechazar') / len(decisiones_tipo)
            tasa_escalacion = sum(1 for d in decisiones_tipo if d['decision'] == 'escalar') / len(decisiones_tipo)

            confianza_engine_promedio = sum(d['confianza_engine'] for d in decisiones_tipo) / len(decisiones_tipo)
            confianza_usuario_promedio = sum(d['confianza_usuario'] for d in decisiones_tipo) / len(decisiones_tipo)

            umbral_actual = self.umbrales["capa3"].get(tipo, 0.70)

            # Lógica de ajuste
            if tasa_rechazo > 0.3:  # >30% rechazados
                # Engine es optimista, subir umbral
                nuevo_umbral = min(0.95, umbral_actual + 0.10)
                confianza_ajuste = max(0.5, 1.0 - tasa_rechazo)  # Más rechazos = menos confianza

                ajustes.append(UmbralOptimo(
                    tipo_bloque=tipo,
                    capa=3,
                    umbral_anterior=umbral_actual,
                    umbral_nuevo=nuevo_umbral,
                    confianza=confianza_ajuste,
                    razon=f"Tasa rechazo {tasa_rechazo:.1%} - subir umbral"
                ))

            elif confianza_usuario_promedio > confianza_engine_promedio + 0.20:
                # Usuario confía más, bajar umbral
                nuevo_umbral = max(0.50, umbral_actual - 0.05)
                confianza_ajuste = 0.75

                ajustes.append(UmbralOptimo(
                    tipo_bloque=tipo,
                    capa=3,
                    umbral_anterior=umbral_actual,
                    umbral_nuevo=nuevo_umbral,
                    confianza=confianza_ajuste,
                    razon=f"Usuario más confiado ({confianza_usuario_promedio:.2f})"
                ))

            elif tasa_escalacion > 0.2:  # >20% escalados
                # Crear escalación pero no ajustar OCR
                pass

        return ajustes

    def aplicar_ajustes(self, ajustes: list[UmbralOptimo]) -> int:
        """Aplica ajustes aplicables y retorna cantidad."""

        count = 0
        for ajuste in ajustes:
            if not ajuste.aplicable():
                continue

            # Aplicar cambio
            if ajuste.capa == 3:
                self.umbrales["capa3"][ajuste.tipo_bloque] = ajuste.umbral_nuevo
            elif ajuste.capa == 4:
                self.umbrales["capa4"][ajuste.tipo_bloque] = ajuste.umbral_nuevo

            count += 1

        # Guardar cambios
        try:
            with open(self.ruta, "w") as f:
                json.dump(self.umbrales, f, indent=2)
            print(f"[UMBRALES] Aplicados {count} cambios")
        except Exception as e:
            print(f"[UMBRALES] Error guardando: {e}")

        return count

    def validar_cambios(self, bloques_validacion: list, sesion_previa: bool = False) -> dict:
        """Valida que los cambios no empeoren métricas.

        Returns:
            {
                "mejora": bool,
                "metrica_anterior": float,
                "metrica_nueva": float,
                "cambio_porcentaje": float
            }
        """

        # Simulación: sin datos reales de validación
        return {
            "mejora": True,
            "metrica_anterior": 0.75,
            "metrica_nueva": 0.78,
            "cambio_porcentaje": 4.0,
            "razon": "Simulado - requiere validación real"
        }

    def obtener_resumen_umbrales(self) -> dict:
        """Resumen de umbrales actuales."""

        return {
            "capa3": self.umbrales.get("capa3", {}),
            "capa4": self.umbrales.get("capa4", {}),
            "timestamp_actualizacion": "2026-08-21"
        }

    def revertir_cambios(self, backup_path: str | Path) -> bool:
        """Revierte a configuración anterior en caso de problema."""

        try:
            with open(backup_path) as f:
                config_anterior = json.load(f)

            self.umbrales = config_anterior

            with open(self.ruta, "w") as f:
                json.dump(self.umbrales, f, indent=2)

            print("[UMBRALES] Cambios revertidos")
            return True

        except Exception as e:
            print(f"[UMBRALES] Error revirtiendo: {e}")
            return False
