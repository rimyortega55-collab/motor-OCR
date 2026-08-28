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
    hechos.extend(_agregar_idioma_original(engine, inspector, tablas))
    hechos.extend(_agregar_modo_motor(engine, inspector, tablas))

    return hechos


def _agregar_modo_motor(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    """`documentos` gana `modo_motor`. Las filas viejas se marcan "hibrido":
    es el único modo que existía cuando se procesaron, así que el default no
    inventa nada sobre ellas."""

    if "documentos" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("documentos")}
    if "modo_motor" in columnas:
        return []

    with engine.begin() as conexion:
        conexion.execute(
            text(
                "ALTER TABLE documentos ADD COLUMN modo_motor VARCHAR(20) "
                "NOT NULL DEFAULT 'hibrido'"
            )
        )

    return ["documentos.modo_motor (agregada)"]


def _agregar_idioma_original(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    """`documentos` gana `idioma_original`: agregarla es segura con ADD COLUMN,
    a diferencia de sacar una columna (ver `_quitar_columna`)."""

    if "documentos" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("documentos")}
    if "idioma_original" in columnas:
        return []

    with engine.begin() as conexion:
        conexion.execute(text("ALTER TABLE documentos ADD COLUMN idioma_original VARCHAR(20)"))

    return ["documentos.idioma_original (agregada)"]


def _quitar_columna(engine: Engine, tabla: str, columna: str) -> None:
    """Quita una columna, con SQLite reconstruyendo la tabla si hace falta.

    SQLite soporta `ALTER TABLE ... DROP COLUMN` desde la 3.35, pero lo
    rechaza cuando la columna aparece en una definición de FOREIGN KEY (aunque
    sea de la propia tabla): no reescribe esa cláusula, así que devuelve
    "error in table ... after drop column". `usuario_id` es justo ese caso acá
    -era la FK a `usuarios`-, así que el intento directo fallaba siempre que
    una base vieja llegaba con datos reales adentro.

    La única forma de sacarla en ese caso es el patrón de doce pasos de la
    propia documentación de SQLite: crear una tabla nueva sin la columna ni su
    FK, volcar los datos y renombrarla, con `foreign_keys` apagado mientras
    tanto para que las tablas que referencian a esta (`costos`, `bloques`,
    `decisiones`) no protesten por la ausencia momentánea.
    """

    if engine.dialect.name != "sqlite":
        with engine.begin() as conexion:
            conexion.execute(text(f"ALTER TABLE {tabla} DROP COLUMN {columna}"))
        return

    with engine.connect() as conexion:
        # PRAGMA foreign_keys es por conexión y no se puede tocar en medio de
        # una transacción: tiene que ser la primera sentencia de esta.
        conexion.execute(text("PRAGMA foreign_keys=OFF"))

        columnas_info = conexion.execute(text(f"PRAGMA table_info({tabla})")).mappings().all()
        columnas_nuevas = [c for c in columnas_info if c["name"] != columna]
        fks = conexion.execute(text(f"PRAGMA foreign_key_list({tabla})")).mappings().all()

        def _definicion_columna(c: dict) -> str:
            partes = [f'"{c["name"]}"', c["type"] or "TEXT"]
            if c["notnull"]:
                partes.append("NOT NULL")
            if c["dflt_value"] is not None:
                partes.append(f"DEFAULT {c['dflt_value']}")
            if c["pk"]:
                partes.append("PRIMARY KEY")
            return " ".join(partes)

        definiciones = [_definicion_columna(c) for c in columnas_nuevas]
        # Las FK que mencionan a la columna borrada se pierden con ella, que es
        # el objetivo; el resto se reconstruye tal cual estaban.
        for fk in fks:
            if fk["from"] == columna:
                continue
            definiciones.append(
                f'FOREIGN KEY ("{fk["from"]}") REFERENCES "{fk["table"]}"("{fk["to"]}")'
            )

        tabla_temporal = f"{tabla}_migracion_tmp"
        nombres = ", ".join(f'"{c["name"]}"' for c in columnas_nuevas)

        conexion.execute(text(f"DROP TABLE IF EXISTS {tabla_temporal}"))
        conexion.execute(text(f'CREATE TABLE "{tabla_temporal}" ({", ".join(definiciones)})'))
        conexion.execute(
            text(f'INSERT INTO "{tabla_temporal}" ({nombres}) SELECT {nombres} FROM {tabla}')
        )
        conexion.execute(text(f"DROP TABLE {tabla}"))
        conexion.execute(text(f'ALTER TABLE "{tabla_temporal}" RENAME TO {tabla}'))

        conexion.commit()
        conexion.execute(text("PRAGMA foreign_key_check"))
        conexion.execute(text("PRAGMA foreign_keys=ON"))


def _quitar_usuario_de_documentos(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    """`documentos` pierde `usuario_id`: sin cuentas, los documentos son de la instancia."""

    if "documentos" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("documentos")}
    if "usuario_id" not in columnas:
        return []

    _quitar_columna(engine, "documentos", "usuario_id")
    return ["documentos.usuario_id (quitada, ya no hay cuentas)"]


def _quitar_usuario_de_costos(engine: Engine, inspector, tablas: set[str]) -> list[str]:
    if "costos" not in tablas:
        return []

    columnas = {c["name"] for c in inspector.get_columns("costos")}
    if "usuario_id" not in columnas:
        return []

    _quitar_columna(engine, "costos", "usuario_id")
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
