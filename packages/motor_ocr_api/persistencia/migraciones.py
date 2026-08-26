"""Migraciones idempotentes del esquema.

`Base.metadata.create_all` crea las tablas que faltan pero no toca las que ya
existen ni borra las que sobran. Este módulo se encarga de lo que create_all no
hace: quitar de una base vieja las columnas y tablas que dejaron de existir
cuando el proyecto pasó de multi-cuenta a una sola instancia sin usuarios, y
mover a las nuevas tablas globales lo que antes vivía por cuenta.

No se usa Alembic todavía porque el historial de migraciones es corto y agregar
la herramienta obliga a versionar un historial que no existe. Si esto sigue
creciendo, conviene migrar a Alembic en vez de estirar esto.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrar(engine: Engine) -> list[str]:
    """Aplica lo que falte. Devuelve qué hizo, para poder registrarlo."""

    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    hechos: list[str] = []

    hechos.extend(_quitar_usuario_de_documentos(engine, inspector, tablas))
    hechos.extend(_quitar_usuario_de_costos(engine, inspector, tablas))
    hechos.extend(_migrar_umbrales_a_global(engine, inspector, tablas))
    hechos.extend(_quitar_tablas_de_cuentas(engine, tablas))

    return hechos


def _quitar_usuario_de_documentos(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    """`documentos` pierde `usuario_id`: sin cuentas, los documentos son de la instancia."""

    if "documentos" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("documentos")}
    if "usuario_id" not in columnas:
        return []

    if engine.dialect.name == "sqlite":
        with engine.begin() as conexion:
            conexion.execute(text("ALTER TABLE documentos DROP COLUMN usuario_id"))
    else:
        with engine.begin() as conexion:
            conexion.execute(text("ALTER TABLE documentos DROP COLUMN usuario_id"))

    return ["documentos.usuario_id (quitada, ya no hay cuentas)"]


def _quitar_usuario_de_costos(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    if "costos" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("costos")}
    if "usuario_id" not in columnas:
        return []

    with engine.begin() as conexion:
        conexion.execute(text("ALTER TABLE costos DROP COLUMN usuario_id"))

    return ["costos.usuario_id (quitada, ya no hay cuentas)"]


def _migrar_umbrales_a_global(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    """La vieja `umbrales` tenía una fila por `usuario_id`; la nueva, una sola fila "global".

    Se conserva la primera fila que haya (si hay varias, es imposible saber cuál
    prevalece sin cuentas) y se descarta el resto: es mejor arrancar con un
    umbral heredado y editable que perder la tabla entera sin aviso.
    """

    if "umbrales" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("umbrales")}
    if "usuario_id" not in columnas:
        return []  # ya está en la forma nueva

    with engine.begin() as conexion:
        primera = conexion.execute(
            text("SELECT capa3, capa4, globales FROM umbrales LIMIT 1")
        ).fetchone()

        conexion.execute(text("DROP TABLE umbrales"))
        conexion.execute(text("""
            CREATE TABLE umbrales (
                id VARCHAR(20) NOT NULL PRIMARY KEY,
                capa3 JSON,
                capa4 JSON,
                globales JSON,
                actualizado_en DATETIME
            )
        """))

        if primera is not None:
            conexion.execute(
                text(
                    "INSERT INTO umbrales (id, capa3, capa4, globales) "
                    "VALUES ('global', :capa3, :capa4, :globales)"
                ),
                {"capa3": primera[0], "capa4": primera[1], "globales": primera[2]},
            )

    return ["umbrales: de una fila por cuenta a una fila global"]


def _quitar_tablas_de_cuentas(engine: Engine, tablas: set[str]) -> list[str]:
    """Borra `usuarios`, `sesiones` y `api_keys`: ya no hay cuentas que guardar."""

    hechos = []
    for tabla in ("api_keys", "sesiones", "usuarios"):
        if tabla not in tablas:
            continue
        with engine.begin() as conexion:
            conexion.execute(text(f"DROP TABLE {tabla}"))
        hechos.append(f"{tabla} (eliminada, ya no hay cuentas)")

    return hechos
