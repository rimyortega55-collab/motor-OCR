"""Aislamiento del entorno y fixtures compartidos de la suite.

Aislamiento del entorno de la maquina donde se corre la suite.

Esto se ejecuta antes de importar cualquier modulo de prueba, y por lo tanto
antes de que se importe `motor_ocr_api`, que es lo que hace falta: la clave de
acceso y el modo de la cookie se leen del entorno en tiempo de import.

El caso concreto que motiva el archivo: si quien corre las pruebas tiene
`MOTOR_OCR_CLAVE_ACCESO` exportada en su shell -algo normal en la maquina del
operador de una instancia-, `exigir_acceso` empieza a pedir cookie y las
pruebas de API, que nunca hacen login, fallan en bloque con 401. La suite tiene
que probar el motor, no el entorno de quien la invoca, asi que la instancia
bajo prueba se fuerza siempre a "abierta".
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Instancia abierta: sin clave configurada, `exigir_acceso` no pide nada. Las
# pruebas que si quieran ejercitar el 401 deben setear la clave ellas mismas.
os.environ.pop("MOTOR_OCR_CLAVE_ACCESO", None)

# Sin `Secure` en la cookie: el TestClient habla por http y descartaria una
# cookie marcada como segura, con lo que ningun login de prueba se sostendria.
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"


@pytest.fixture
def pdf_en_disco(tmp_path):
    """Escribe bytes de PDF a un archivo temporal y devuelve su ruta.

    Casi todo el motor recibe una ruta y no bytes -PyMuPDF abre por nombre de
    archivo en `detectar_origen`, `perfil_visual` y el pipeline-, mientras que
    los generadores de `tests/fixtures/sinteticos.py` devuelven bytes para no
    tener que decidir donde escribirlos. Este fixture es el puente, y usa
    `tmp_path` para que pytest limpie solo: la version escaneada de un PDF
    sintetico pesa varios MB y no debe quedar tirada en el arbol del proyecto.
    """
    contador = iter(range(1000))

    def _escribir(datos: bytes, nombre: str | None = None) -> Path:
        ruta = tmp_path / (nombre or f"fixture_{next(contador)}.pdf")
        ruta.write_bytes(datos)
        return ruta

    return _escribir
