"""Capa 1: validar con PDFs reales de distintos tipos (nativo-digital limpio,
escaneado, mixto) antes de avanzar a segmentación — ver orden de
implementación sugerido en .contexto/04-estructura-proyecto.md.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Pendiente: agregar fixtures PDF en tests/fixtures/")


def test_detecta_origen_nativo_digital():
    ...


def test_detecta_origen_escaneado():
    ...


def test_zonifica_paginas_contiguas_por_perfil():
    ...
