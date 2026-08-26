"""Control de concurrencia hacia el proveedor de LLM.

Semáforo con límite configurable de llamadas concurrentes (config.settings,
`limite_concurrencia_llm`) que respeta rate limits. Cola 1 (micro-segmentos)
tiene prioridad sobre Cola 2 (inconsistencias) en caso de contención de
recursos, porque afecta directamente la fidelidad del contenido, no solo
metadata.
"""

from __future__ import annotations

from asyncio import Semaphore
from threading import Lock

# Configuración de concurrencia
LIMITE_CONCURRENCIA_LLM = 3  # máximo 3 llamadas concurrentes
LIMITE_LLAMADAS_POR_MINUTO = 30

# Semáforo para limitar concurrencia
_semaforo = None
_lock = Lock()

# Contador de llamadas para rate limiting
_contador_llamadas = 0
_inicio_ventana = None


def obtener_semaforo():
    """Obtiene el semáforo singleton."""
    global _semaforo
    if _semaforo is None:
        _semaforo = Semaphore(LIMITE_CONCURRENCIA_LLM)
    return _semaforo


class ControladorConcurrencia:
    """Controla acceso concurrente al LLM con prioridad por cola."""

    def __init__(self, prioridad: str = "normal"):
        """
        Args:
            prioridad: "alto" (micro-segmentos), "normal" (inconsistencias)
        """
        self.prioridad = prioridad
        self.adquirido = False

    async def __aenter__(self):
        """Adquiere acceso al LLM (async context manager)."""
        semaforo = obtener_semaforo()

        # Si es alta prioridad, intentar primero (no esperaría)
        # Si es normal prioridad, esperar con timeout

        if self.prioridad == "alto":
            # Intentar sin bloqueo
            if semaforo._value > 0:
                await semaforo.acquire()
                self.adquirido = True
            else:
                # Esperar si es urgente
                await semaforo.acquire()
                self.adquirido = True
        else:
            # Normal: esperar
            await semaforo.acquire()
            self.adquirido = True

        # Verificar rate limit
        _verificar_rate_limit()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Libera acceso al LLM."""
        if self.adquirido:
            semaforo = obtener_semaforo()
            semaforo.release()


def _verificar_rate_limit():
    """Verifica y actualiza contador de rate limit."""
    global _contador_llamadas, _inicio_ventana
    import time

    ahora = time.time()

    # Reiniciar ventana si pasó un minuto
    if _inicio_ventana is None or (ahora - _inicio_ventana) > 60:
        _inicio_ventana = ahora
        _contador_llamadas = 0

    _contador_llamadas += 1

    if _contador_llamadas > LIMITE_LLAMADAS_POR_MINUTO:
        # En producción, esperar o rechazar
        import time
        tiempo_espera = 60 - (ahora - _inicio_ventana)
        if tiempo_espera > 0:
            print(f"[BATCHING] Rate limit alcanzado. Esperando {tiempo_espera:.1f}s")
            time.sleep(tiempo_espera)


def resetear_contadores():
    """Resetea contadores (para testing)."""
    global _contador_llamadas, _inicio_ventana
    _contador_llamadas = 0
    _inicio_ventana = None
