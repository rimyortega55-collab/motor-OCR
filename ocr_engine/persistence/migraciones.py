"""Migraciones idempotentes del esquema.

`Base.metadata.create_all` crea las tablas que faltan pero no toca las que ya
existen: en una base desplegada antes de la sesión de navegador, `usuarios` no
tiene `password_hash` y las claves siguen viviendo en esa misma tabla. Sin este
paso, el motor arranca contra un esquema viejo y falla en la primera consulta.

No se usa Alembic todavía porque hay una sola migración real y agregar la
herramienta obliga a versionar un historial que no existe. Cuando aparezca la
segunda o la tercera, conviene migrar a Alembic en vez de estirar esto.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrar(engine: Engine) -> list[str]:
    """Aplica lo que falte. Devuelve qué hizo, para poder registrarlo."""

    inspector = inspect(engine)
    if "usuarios" not in inspector.get_table_names():
        return []  # Base nueva: create_all ya dejó el esquema al día.

    hechos: list[str] = []
    columnas = {c["name"]: c for c in inspector.get_columns("usuarios")}

    if "password_hash" not in columnas:
        with engine.begin() as conexion:
            conexion.execute(text("ALTER TABLE usuarios ADD COLUMN password_hash VARCHAR(255)"))
        hechos.append("usuarios.password_hash")

    if _api_key_hash_es_obligatoria(columnas):
        _aflojar_api_key_hash(engine)
        hechos.append("usuarios.api_key_hash pasa a nullable")

    if "api_key_hash" in columnas:
        movidas = _backfill_api_keys(engine)
        if movidas:
            hechos.append(f"{movidas} claves movidas a api_keys")

    hechos.extend(_columnas_de_progreso(engine, inspector))

    return hechos


def _columnas_de_progreso(engine: Engine, inspector) -> list[str]:
    """Agrega a `documentos` el progreso por capa y el latido del worker."""

    if "documentos" not in inspector.get_table_names():
        return []

    existentes = {c["name"] for c in inspector.get_columns("documentos")}
    faltantes = [
        ("progreso", "JSON"),
        ("latido_en", "DATETIME"),
        ("ruta_pdf", "VARCHAR(500)"),
    ]

    hechos = []
    for nombre, tipo in faltantes:
        if nombre in existentes:
            continue
        with engine.begin() as conexion:
            conexion.execute(text(f"ALTER TABLE documentos ADD COLUMN {nombre} {tipo}"))
        hechos.append(f"documentos.{nombre}")

    return hechos


def _api_key_hash_es_obligatoria(columnas: dict) -> bool:
    columna = columnas.get("api_key_hash")
    return columna is not None and not columna.get("nullable", True)


def _aflojar_api_key_hash(engine: Engine) -> None:
    """Vuelve `usuarios.api_key_hash` opcional.

    SQLite no soporta ALTER COLUMN, así que hay que reconstruir la tabla: crear
    la nueva, copiar, borrar la vieja y renombrar. Es el mismo procedimiento que
    Alembic llama "batch mode". En Postgres alcanza con un ALTER.
    """

    if engine.dialect.name != "sqlite":
        with engine.begin() as conexion:
            conexion.execute(text("ALTER TABLE usuarios ALTER COLUMN api_key_hash DROP NOT NULL"))
            conexion.execute(text("ALTER TABLE usuarios ALTER COLUMN api_key_prefijo DROP NOT NULL"))
        return

    with engine.begin() as conexion:
        # Las claves foráneas apuntan a usuarios; desactivarlas durante el
        # rename evita que el DROP se lleve puestas las filas hijas.
        conexion.execute(text("PRAGMA foreign_keys=OFF"))
        conexion.execute(text("""
            CREATE TABLE usuarios_nuevo (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                nombre VARCHAR(200) NOT NULL,
                email VARCHAR(320),
                password_hash VARCHAR(255),
                api_key_hash VARCHAR(64),
                api_key_prefijo VARCHAR(12),
                plan VARCHAR(50),
                activo BOOLEAN,
                creado_en DATETIME,
                UNIQUE (email),
                UNIQUE (api_key_hash)
            )
        """))
        conexion.execute(text("""
            INSERT INTO usuarios_nuevo
                (id, nombre, email, password_hash, api_key_hash, api_key_prefijo,
                 plan, activo, creado_en)
            SELECT id, nombre, email, password_hash, api_key_hash, api_key_prefijo,
                   plan, activo, creado_en
            FROM usuarios
        """))
        conexion.execute(text("DROP TABLE usuarios"))
        conexion.execute(text("ALTER TABLE usuarios_nuevo RENAME TO usuarios"))
        conexion.execute(text("PRAGMA foreign_keys=ON"))


def _backfill_api_keys(engine: Engine) -> int:
    """Copia a `api_keys` las claves que todavía viven en `usuarios`."""

    ahora = datetime.now(timezone.utc)
    movidas = 0

    with engine.begin() as conexion:
        filas = conexion.execute(text("""
            SELECT u.id, u.api_key_hash, u.api_key_prefijo, u.creado_en
            FROM usuarios u
            WHERE u.api_key_hash IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM api_keys k WHERE k.clave_hash = u.api_key_hash)
        """)).fetchall()

        for usuario_id, clave_hash, prefijo, creado_en in filas:
            conexion.execute(
                text("""
                    INSERT INTO api_keys
                        (id, usuario_id, nombre, clave_hash, prefijo, creada_en)
                    VALUES (:id, :usuario_id, :nombre, :clave_hash, :prefijo, :creada_en)
                """),
                {
                    "id": str(uuid4()),
                    "usuario_id": usuario_id,
                    "nombre": "clave original",
                    "clave_hash": clave_hash,
                    "prefijo": prefijo or "moc_",
                    "creada_en": creado_en or ahora,
                },
            )
            movidas += 1

    return movidas
