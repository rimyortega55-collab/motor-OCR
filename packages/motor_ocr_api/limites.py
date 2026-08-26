"""Límite de tasa para los endpoints que cuestan cómputo o IA.

Sin esto, cualquiera podía mandar `/procesar` sin tope y consumir el crédito
del proveedor de IA configurado, que es gasto real porque escalar a un LLM
cuesta dinero. Si la instancia pide clave de acceso (`MOTOR_OCR_CLAVE_ACCESO`),
probarla sin límite también sería gratis para quien intenta adivinarla.

Es un contador en memoria del proceso, coherente con la decisión de correr los
trabajos en hilos y no en una cola: alcanza para una instancia. Con varias, cada
una lleva su propia cuenta y el límite efectivo se multiplica por la cantidad de
instancias; llegado ese punto corresponde moverlo a Redis, sin cambiar la firma
de `exigir_limite`.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

# ventana en segundos -> cuántos intentos se permiten dentro de ella
LIMITES: dict[str, tuple[int, int]] = {
    "acceso": (900, 10),     # 10 intentos de clave cada 15 minutos
    "procesar": (3600, 60),  # 60 documentos por hora
}

_intentos: dict[tuple[str, str], list[float]] = defaultdict(list)
_candado = threading.Lock()


def _cliente(request: Request) -> str:
    """IP del cliente, mirando el proxy si lo hay.

    Detrás de un proxy `request.client.host` es siempre la IP del proxy, con lo
    que todos los usuarios compartirían un mismo contador y el primero en gastar
    la cuota bloquearía a los demás.
    """
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocido"


def exigir_limite(request: Request, accion: str) -> None:
    """Corta con 429 si la IP superó la cuota de esa acción."""

    ventana, maximo = LIMITES.get(accion, (3600, 100))
    clave = (accion, _cliente(request))
    ahora = time.monotonic()

    with _candado:
        recientes = [t for t in _intentos[clave] if ahora - t < ventana]

        if len(recientes) >= maximo:
            espera = int(ventana - (ahora - recientes[0])) + 1
            _intentos[clave] = recientes
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "codigo": "demasiados_intentos",
                    "detail": f"Demasiados intentos. Probá de nuevo en {espera} segundos.",
                },
                headers={"Retry-After": str(espera)},
            )

        recientes.append(ahora)
        _intentos[clave] = recientes


def limpiar() -> None:
    """Vacía los contadores. Para las pruebas, que si no se pisan entre sí."""
    with _candado:
        _intentos.clear()
