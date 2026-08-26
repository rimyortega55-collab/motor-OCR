"""Sirve el build del SPA desde el mismo FastAPI que expone la API.

Un solo origen para el frontend y la API evita CORS y, sobre todo, evita tener
que aflojar la cookie de sesión a `SameSite=None`, que es lo que haría falta si
el SPA viviera en otro dominio.

El build lo genera `npm run build` desde `frontend/` y cae en `estatico/`. Si no
está —que es lo normal en desarrollo, donde Vite sirve el frontend en su propio
puerto y proxea la API— no se monta nada y la API funciona igual.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

RUTA_ESTATICO = Path(__file__).parent / "estatico"
INDICE = RUTA_ESTATICO / "index.html"

# Prefijos que atiende la API. Una ruta desconocida que empiece con uno de estos
# debe dar 404 y no el HTML del SPA: devolverle una página a un cliente que
# esperaba JSON convierte un error claro en uno incomprensible.
PREFIJOS_API = ("api", "docs", "redoc", "openapi.json")


def hay_build() -> bool:
    return INDICE.is_file()


def _indice() -> FileResponse:
    # Sin caché: el index referencia los bundles con hash en el nombre, así que
    # si el navegador se queda con un index viejo pide bundles que ya no existen.
    return FileResponse(INDICE, headers={"Cache-Control": "no-cache"})


def montar_spa(app: FastAPI) -> bool:
    """Monta el SPA si hay build. Devuelve si lo montó."""

    if not hay_build():
        return False

    # Los assets llevan hash en el nombre, así que se pueden cachear para siempre.
    app.mount(
        "/assets",
        StaticFiles(directory=RUTA_ESTATICO / "assets"),
        name="assets",
    )

    @app.get("/{ruta_spa:path}", include_in_schema=False)
    async def servir_spa(ruta_spa: str):
        """Cualquier ruta no reclamada por la API la resuelve el router del SPA.

        Se registra al final para que las rutas de la API, declaradas antes,
        ganen siempre: FastAPI resuelve por orden de registro.
        """
        primero = ruta_spa.split("/", 1)[0]
        if primero in PREFIJOS_API:
            raise HTTPException(status_code=404, detail={"codigo": "no_encontrado",
                                                         "detail": "Ruta inexistente"})

        # Un archivo real del build (favicon, manifest) se sirve tal cual; el
        # resto es una ruta de React Router y le toca el index.
        archivo = (RUTA_ESTATICO / ruta_spa).resolve()
        if (
            ruta_spa
            and archivo.is_file()
            and archivo.is_relative_to(RUTA_ESTATICO.resolve())
        ):
            return FileResponse(archivo)

        return _indice()

    return True
