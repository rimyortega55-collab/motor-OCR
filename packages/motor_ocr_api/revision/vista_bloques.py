"""Interfaz interactiva CLI para revisión humana de bloques.

Permite revisar bloques con baja confianza o escalaciones LLM,
comparar versión engine vs versión corregida, y tomar decisiones:
- Aceptar (usar versión actual)
- Rechazar (volver a versión anterior)
- Editar (edición manual)
- Escalar (enviar a especialista)
"""

from __future__ import annotations

import sys
from uuid import UUID
from typing import Optional

class VistaInteractiva:
    """Interfaz interactiva para revisión de bloques."""

    def __init__(self, ancho_terminal: int = 100):
        self.ancho = ancho_terminal
        self.decisiones = {}

    def mostrar_bloque(
        self,
        bloque_id: UUID,
        pagina: int,
        tipo: str,
        contenido_engine: str,
        contenido_llm: Optional[str] = None,
        confianza_engine: float = 0.0,
        confianza_llm: float = 0.0,
        razon_escalacion: str = ""
    ) -> dict:
        """Muestra bloque y recibe decisión del usuario.

        Returns:
            {
                "decision": "aceptar" | "rechazar" | "editar" | "escalar",
                "contenido_final": str,
                "comentarios": str,
                "confianza_usuario": float (0-1)
            }
        """

        self._limpiar_pantalla()
        self._mostrar_header(bloque_id, pagina, tipo)

        print(f"\n{'='*self.ancho}")
        print(f"RESULTADO ENGINE (confianza: {confianza_engine:.2f})")
        print(f"{'='*self.ancho}")
        print(self._truncar_texto(contenido_engine, 500))

        if contenido_llm:
            print(f"\n{'='*self.ancho}")
            print(f"CORRECCIÓN LLM (confianza: {confianza_llm:.2f})")
            print(f"{'='*self.ancho}")
            print(self._truncar_texto(contenido_llm, 500))

            if razon_escalacion:
                print(f"\nRazon de escalación: {razon_escalacion}")

        print(f"\n{'='*self.ancho}")
        print("OPCIONES:")
        print(f"{'='*self.ancho}")
        print("(1) Aceptar resultado actual")
        print("(2) Rechazar y usar versión anterior")
        print("(3) Editar manualmente")
        print("(4) Escalar a especialista")
        print("(5) Saltar")
        print("(q) Quit")

        while True:
            try:
                opcion = input("\nSelecciona opción (1-5, q): ").strip().lower()

                if opcion == "q":
                    return {"decision": "quit"}

                elif opcion == "1":
                    # Aceptar
                    comentarios = input("Comentarios (Enter para vacío): ").strip()
                    return {
                        "decision": "aceptar",
                        "contenido_final": contenido_llm or contenido_engine,
                        "comentarios": comentarios,
                        "confianza_usuario": max(confianza_engine, confianza_llm)
                    }

                elif opcion == "2":
                    # Rechazar
                    comentarios = input("Razon del rechazo: ").strip()
                    return {
                        "decision": "rechazar",
                        "contenido_final": contenido_engine,
                        "comentarios": comentarios,
                        "confianza_usuario": confianza_engine
                    }

                elif opcion == "3":
                    # Editar
                    print(f"\nTexto actual:\n{contenido_llm or contenido_engine}")
                    texto_editado = input("Ingresa texto corregido:\n").strip()

                    if texto_editado:
                        return {
                            "decision": "editar",
                            "contenido_final": texto_editado,
                            "comentarios": "Editado manualmente por usuario",
                            "confianza_usuario": 0.9  # Usuario corrigió, alta confianza
                        }
                    else:
                        print("No se ingresó texto. Intentando de nuevo...")

                elif opcion == "4":
                    # Escalar
                    razon = input("Razon de escalación a especialista: ").strip()
                    return {
                        "decision": "escalar",
                        "contenido_final": contenido_engine,
                        "comentarios": razon,
                        "confianza_usuario": 0.0
                    }

                elif opcion == "5":
                    # Saltar
                    return {
                        "decision": "saltar",
                        "contenido_final": contenido_llm or contenido_engine,
                        "comentarios": "Saltado por usuario",
                        "confianza_usuario": 0.5
                    }

                else:
                    print("Opción inválida. Intenta de nuevo.")

            except KeyboardInterrupt:
                print("\n\nInterrupción del usuario.")
                return {"decision": "quit"}
            except Exception as e:
                print(f"Error: {e}. Intenta de nuevo.")

    def mostrar_resumen(self, estadisticas: dict) -> None:
        """Muestra resumen de decisiones tomadas."""

        self._limpiar_pantalla()

        print(f"\n{'='*self.ancho}")
        print("RESUMEN DE REVISIÓN")
        print(f"{'='*self.ancho}\n")

        print(f"Bloques revisados:        {estadisticas.get('total_revisados', 0)}")
        print(f"Aceptados:                {estadisticas.get('aceptados', 0)}")
        print(f"Rechazados:               {estadisticas.get('rechazados', 0)}")
        print(f"Editados:                 {estadisticas.get('editados', 0)}")
        print(f"Escalados:                {estadisticas.get('escalados', 0)}")
        print(f"Saltados:                 {estadisticas.get('saltados', 0)}")

        if estadisticas.get('aceptados', 0) > 0:
            pct_aceptacion = (
                100 * estadisticas['aceptados'] / estadisticas['total_revisados']
            )
            print(f"\nTasa de aceptación:       {pct_aceptacion:.1f}%")

        confianza_promedio = estadisticas.get('confianza_promedio_usuario', 0)
        print(f"Confianza usuario promedio: {confianza_promedio:.2f}")

        print(f"\n{'='*self.ancho}\n")

    def _mostrar_header(self, bloque_id: UUID, pagina: int, tipo: str) -> None:
        """Muestra encabezado con metadatos del bloque."""
        print(f"\n{'='*self.ancho}")
        print(f"BLOQUE: {tipo.upper()}")
        print(f"ID: {str(bloque_id)[:8]}... | Página: {pagina}")
        print(f"{'='*self.ancho}")

    def _truncar_texto(self, texto: str, max_chars: int = 500) -> str:
        """Trunca texto largo para visualización."""
        if len(texto) > max_chars:
            return texto[:max_chars] + f"\n... [truncado, {len(texto)} chars totales]"
        return texto

    def _limpiar_pantalla(self) -> None:
        """Limpia la pantalla (cross-platform)."""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')


def solicitar_confirmacion(mensaje: str) -> bool:
    """Solicita confirmación sí/no."""
    while True:
        respuesta = input(f"\n{mensaje} (s/n): ").strip().lower()
        if respuesta in ('s', 'si', 'sí', 'y', 'yes'):
            return True
        elif respuesta in ('n', 'no'):
            return False
        else:
            print("Respuesta inválida. Intenta de nuevo.")


def solicitar_numero(mensaje: str, minimo: float = 0.0, maximo: float = 1.0) -> float:
    """Solicita número en rango."""
    while True:
        try:
            valor = float(input(f"\n{mensaje} ({minimo}-{maximo}): ").strip())
            if minimo <= valor <= maximo:
                return valor
            else:
                print(f"Valor fuera de rango [{minimo}, {maximo}].")
        except ValueError:
            print("Entrada inválida. Intenta de nuevo.")
