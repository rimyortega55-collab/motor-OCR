"""Capa 7: Interfaz Web + Auto-Ajuste de Umbrales.

Componentes:
- FastAPI: API REST para procesar PDFs
- Streamlit: Dashboard web para revisión
- AjustadorUmbrales: Auto-ajuste basado en feedback
"""

from .ajuste_umbrales import AjustadorUmbrales, UmbralOptimo

__all__ = ["AjustadorUmbrales", "UmbralOptimo"]
