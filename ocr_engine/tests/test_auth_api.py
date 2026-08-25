"""Pruebas del paso 1 del contrato: sesión, API keys y listado de documentos.

Cada prueba corre contra una base SQLite propia en un directorio temporal. La
variable DATABASE_URL se fija antes de importar nada del motor, porque el engine
se crea al importar `persistence.db`.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_DIRECTORIO = tempfile.mkdtemp(prefix="motor_ocr_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DIRECTORIO) / 'prueba.db'}"
os.environ["MOTOR_OCR_COOKIE_SEGURA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from ocr_engine.persistence import (  # noqa: E402
    ApiKey,
    DocumentoAlmacenado,
    Sesion,
    Usuario,
    init_db,
    session_scope,
)
from ocr_engine.persistence.db import engine  # noqa: E402
from ocr_engine.web_interface import auth  # noqa: E402
from ocr_engine.web_interface import limites  # noqa: E402
from ocr_engine.web_interface.api import app  # noqa: E402

PASSWORD = "una-contrasena-larga"


@pytest.fixture(autouse=True)
def base_limpia():
    """Base vacía en cada prueba, para que el orden no las acople."""
    init_db()
    # El limitador de tasa cuenta por proceso, así que sin esto una suite que
    # crea varios usuarios agota la cuota y las siguientes reciben 429.
    limites.limpiar()
    with session_scope() as sesion:
        for modelo in (Sesion, ApiKey, DocumentoAlmacenado, Usuario):
            sesion.query(modelo).delete()
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cliente_sin_sesion():
    """Cliente aparte, sin cookie.

    `usuario_actual` resuelve la cookie antes que la cabecera, asi que probar la
    API key con un cliente que ya tiene sesion abierta no probaria nada.
    """
    with TestClient(app) as c:
        yield c


def _registrar(cliente, email="rimy@example.com", nombre="Rimy Ortega"):
    respuesta = cliente.post(
        "/api/auth/registro",
        json={"nombre": nombre, "email": email, "password": PASSWORD},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# ============================================================================
# CONTRASEÑAS
# ============================================================================

def test_password_se_verifica_y_cada_hash_es_distinto():
    uno = auth.hashear_password(PASSWORD)
    otro = auth.hashear_password(PASSWORD)

    assert uno != otro, "la sal debe hacer que dos hashes de la misma clave difieran"
    assert auth.verificar_password(PASSWORD, uno)
    assert auth.verificar_password(PASSWORD, otro)
    assert not auth.verificar_password("otra-cosa-larga", uno)


def test_password_no_viaja_en_claro_a_la_base(cliente):
    _registrar(cliente)

    with session_scope() as sesion:
        usuario = sesion.query(Usuario).one()
        assert usuario.password_hash is not None
        assert PASSWORD not in usuario.password_hash
        assert usuario.password_hash.startswith("scrypt$")


@pytest.mark.parametrize("almacenado", [None, "", "sin-formato", "bcrypt$1$2$3$4$5"])
def test_verificar_password_rechaza_hashes_invalidos(almacenado):
    assert not auth.verificar_password(PASSWORD, almacenado)


# ============================================================================
# REGISTRO Y SESIÓN
# ============================================================================

def test_registro_abre_sesion_y_devuelve_la_clave_una_vez(cliente):
    datos = _registrar(cliente)

    assert datos["api_key"].startswith("moc_")
    assert datos["usuario"]["email"] == "rimy@example.com"
    assert datos["usuario"]["plan"] == "libre"
    assert auth.COOKIE_SESION in cliente.cookies

    # La clave en claro no queda en ningún lado.
    with session_scope() as sesion:
        clave = sesion.query(ApiKey).one()
        assert clave.clave_hash == auth.hashear_api_key(datos["api_key"])
        assert clave.prefijo == datos["api_key"][:12]


def test_registro_rechaza_email_repetido(cliente):
    _registrar(cliente)
    respuesta = cliente.post(
        "/api/auth/registro",
        json={"nombre": "Otro", "email": "rimy@example.com", "password": PASSWORD},
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["codigo"] == "email_ya_registrado"


def test_registro_rechaza_password_corta(cliente):
    respuesta = cliente.post(
        "/api/auth/registro",
        json={"nombre": "Corto", "email": "corto@example.com", "password": "corta"},
    )
    assert respuesta.status_code == 422


def test_login_y_logout(cliente):
    _registrar(cliente)
    cliente.cookies.clear()

    login = cliente.post(
        "/api/auth/login", json={"email": "rimy@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert auth.COOKIE_SESION in cliente.cookies

    assert cliente.get("/api/auth/yo").status_code == 200

    assert cliente.post("/api/auth/logout").status_code == 204
    cliente.cookies.clear()
    assert cliente.get("/api/auth/yo").status_code == 401


def test_login_no_distingue_email_inexistente_de_password_incorrecta(cliente):
    _registrar(cliente)

    inexistente = cliente.post(
        "/api/auth/login", json={"email": "nadie@example.com", "password": PASSWORD}
    )
    incorrecta = cliente.post(
        "/api/auth/login", json={"email": "rimy@example.com", "password": "otra-clave-larga"}
    )

    assert inexistente.status_code == incorrecta.status_code == 401
    assert inexistente.json() == incorrecta.json()


def test_sesion_vencida_no_autentica(cliente):
    _registrar(cliente)

    with session_scope() as sesion:
        registro = sesion.query(Sesion).one()
        registro.expira_en = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert cliente.get("/api/auth/yo").status_code == 401

    # Y además se limpió, para que no queden sesiones muertas acumulándose.
    with session_scope() as sesion:
        assert sesion.query(Sesion).count() == 0


def test_cuenta_desactivada_no_entra(cliente):
    _registrar(cliente)

    with session_scope() as sesion:
        sesion.query(Usuario).one().activo = False

    assert cliente.get("/api/auth/yo").status_code == 403


# ============================================================================
# API KEYS
# ============================================================================

def test_api_key_autentica_los_endpoints_de_datos(cliente, cliente_sin_sesion):
    datos = _registrar(cliente)

    respuesta = cliente_sin_sesion.get(
        "/api/auth/yo", headers={"X-API-Key": datos["api_key"]}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == datos["usuario"]["id"]


def test_api_key_no_alcanza_para_administrar_claves(cliente, cliente_sin_sesion):
    """Una clave filtrada no debe poder emitir claves nuevas."""
    datos = _registrar(cliente)

    cabeceras = {"X-API-Key": datos["api_key"]}
    assert cliente_sin_sesion.get("/api/api-keys", headers=cabeceras).status_code == 401
    assert cliente_sin_sesion.post(
        "/api/api-keys", json={"nombre": "x"}, headers=cabeceras
    ).status_code == 401


def test_crear_y_revocar_api_key(cliente, cliente_sin_sesion):
    _registrar(cliente)

    creada = cliente.post("/api/api-keys", json={"nombre": "notebook local"})
    assert creada.status_code == 201
    clave = creada.json()["api_key"]
    assert clave.startswith("moc_")

    listado = cliente.get("/api/api-keys").json()
    assert len(listado) == 2  # la inicial y la nueva
    assert "api_key" not in listado[0], "el listado nunca devuelve la clave en claro"

    # La clave nueva sirve.
    cabeceras = {"X-API-Key": clave}
    assert cliente_sin_sesion.get("/api/auth/yo", headers=cabeceras).status_code == 200

    # Y deja de servir al revocarla, sin tocar las demás.
    assert cliente.delete(f"/api/api-keys/{creada.json()['id']}").status_code == 204
    assert cliente_sin_sesion.get("/api/auth/yo", headers=cabeceras).status_code == 401

    with session_scope() as sesion:
        assert sesion.query(ApiKey).filter(ApiKey.revocada_en.is_(None)).count() == 1


def test_no_se_puede_revocar_la_clave_de_otro(cliente):
    _registrar(cliente)
    ajena = cliente.post("/api/api-keys", json={"nombre": "de otro"}).json()

    cliente.cookies.clear()
    _registrar(cliente, email="otro@example.com", nombre="Otro")

    respuesta = cliente.delete(f"/api/api-keys/{ajena['id']}")
    assert respuesta.status_code == 404, "se responde 404 para no confirmar que existe"


def test_ultimo_uso_se_registra(cliente, cliente_sin_sesion):
    datos = _registrar(cliente)
    cliente_sin_sesion.get("/api/auth/yo", headers={"X-API-Key": datos["api_key"]})

    with session_scope() as sesion:
        clave = sesion.query(ApiKey).filter(ApiKey.prefijo == datos["api_key"][:12]).one()
        assert clave.ultimo_uso_en is not None


# ============================================================================
# LISTADO DE DOCUMENTOS
# ============================================================================

def _sembrar_documentos(usuario_id: str, cantidad: int, **campos) -> list[str]:
    ids = []
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)

    with session_scope() as sesion:
        for i in range(cantidad):
            documento_id = str(uuid4())
            ids.append(documento_id)
            sesion.add(
                DocumentoAlmacenado(
                    id=documento_id,
                    usuario_id=usuario_id,
                    titulo=campos.get("titulo", f"documento-{i:02d}.pdf"),
                    estado=campos.get("estado", "completado"),
                    total_paginas=10,
                    total_bloques=100,
                    necesita_revision=campos.get("necesita_revision", False),
                    creado_en=base + timedelta(minutes=i),
                )
            )
    return ids


def test_listado_devuelve_items_total_y_cursor(cliente):
    datos = _registrar(cliente)
    _sembrar_documentos(datos["usuario"]["id"], 5)

    cuerpo = cliente.get("/api/documentos", params={"limite": 2}).json()

    assert cuerpo["total"] == 5
    assert len(cuerpo["items"]) == 2
    assert cuerpo["siguiente_cursor"] is not None
    # Del más reciente al más viejo.
    assert cuerpo["items"][0]["titulo"] == "documento-04.pdf"


def test_cursor_recorre_todo_sin_repetir_ni_saltear(cliente):
    datos = _registrar(cliente)
    _sembrar_documentos(datos["usuario"]["id"], 7)

    vistos, cursor = [], None
    for _ in range(10):
        params = {"limite": 3}
        if cursor:
            params["cursor"] = cursor
        cuerpo = cliente.get("/api/documentos", params=params).json()
        vistos.extend(d["documento_id"] for d in cuerpo["items"])
        cursor = cuerpo["siguiente_cursor"]
        if cursor is None:
            break

    assert len(vistos) == 7
    assert len(set(vistos)) == 7, "el cursor no debe repetir filas"


def test_cursor_desempata_documentos_del_mismo_instante(cliente):
    """Sin el id en el orden, un empate de fechas saltea o repite filas."""
    datos = _registrar(cliente)
    momento = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    with session_scope() as sesion:
        for i in range(6):
            sesion.add(
                DocumentoAlmacenado(
                    id=str(uuid4()),
                    usuario_id=datos["usuario"]["id"],
                    titulo=f"simultaneo-{i}.pdf",
                    estado="completado",
                    creado_en=momento,
                )
            )

    vistos, cursor = [], None
    for _ in range(10):
        params = {"limite": 2}
        if cursor:
            params["cursor"] = cursor
        cuerpo = cliente.get("/api/documentos", params=params).json()
        vistos.extend(d["documento_id"] for d in cuerpo["items"])
        cursor = cuerpo["siguiente_cursor"]
        if cursor is None:
            break

    assert len(set(vistos)) == 6


def test_filtros_de_estado_busqueda_y_revision(cliente):
    datos = _registrar(cliente)
    usuario_id = datos["usuario"]["id"]
    _sembrar_documentos(usuario_id, 3, estado="completado", titulo="analisis-real.pdf")
    _sembrar_documentos(usuario_id, 2, estado="error", titulo="roto.pdf")
    _sembrar_documentos(usuario_id, 1, estado="completado", titulo="revisar.pdf",
                        necesita_revision=True)

    assert cliente.get("/api/documentos", params={"estado": "error"}).json()["total"] == 2
    assert cliente.get("/api/documentos", params={"buscar": "real"}).json()["total"] == 3
    assert cliente.get("/api/documentos", params={"buscar": "REAL"}).json()["total"] == 3
    assert cliente.get(
        "/api/documentos", params={"necesita_revision": True}
    ).json()["total"] == 1


def test_listado_no_muestra_documentos_ajenos(cliente):
    primero = _registrar(cliente)
    _sembrar_documentos(primero["usuario"]["id"], 4)

    cliente.cookies.clear()
    _registrar(cliente, email="otro@example.com", nombre="Otro")

    cuerpo = cliente.get("/api/documentos").json()
    assert cuerpo["total"] == 0
    assert cuerpo["items"] == []


def test_cursor_invalido_da_400(cliente):
    _registrar(cliente)
    respuesta = cliente.get("/api/documentos", params={"cursor": "esto-no-es-un-cursor"})

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "cursor_invalido"


def test_endpoints_de_datos_exigen_autenticacion(cliente):
    cliente.cookies.clear()
    assert cliente.get("/api/documentos").status_code == 401
    assert cliente.get("/api/consumo").status_code == 401


def test_los_errores_traen_codigo_para_ramificar(cliente, cliente_sin_sesion):
    """El frontend ramifica por `codigo`, no parseando el texto del mensaje."""
    sin_auth = cliente_sin_sesion.get("/api/documentos")
    assert sin_auth.json()["detail"]["codigo"] == "sin_autenticacion"

    datos = _registrar(cliente)
    solo_sesion = cliente_sin_sesion.get(
        "/api/api-keys", headers={"X-API-Key": datos["api_key"]}
    )
    assert solo_sesion.json()["detail"]["codigo"] == "requiere_sesion"

    with session_scope() as sesion:
        sesion.query(Usuario).one().activo = False

    desactivada = cliente.get("/api/documentos")
    assert desactivada.status_code == 403
    assert desactivada.json()["detail"]["codigo"] == "cuenta_desactivada"


# ============================================================================
# MIGRACIÓN
# ============================================================================

def test_migracion_mueve_una_clave_vieja_a_api_keys():
    """Una base con la clave en `usuarios` sigue autenticando después de migrar."""
    from sqlalchemy import text

    from ocr_engine.persistence.migraciones import migrar

    clave, clave_hash, prefijo = auth.generar_api_key()
    usuario_id = str(uuid4())

    # Se simula el esquema viejo: la clave vive en `usuarios`.
    with engine.begin() as conexion:
        conexion.execute(
            text("""
                INSERT INTO usuarios (id, nombre, email, api_key_hash, api_key_prefijo,
                                      plan, activo, creado_en)
                VALUES (:id, 'Viejo', 'viejo@example.com', :h, :p, 'libre', 1, :ahora)
            """),
            {"id": usuario_id, "h": clave_hash, "p": prefijo,
             "ahora": datetime.now(timezone.utc)},
        )

    hechos = migrar(engine)
    assert any("claves movidas" in h for h in hechos), hechos

    with session_scope() as sesion:
        movida = sesion.query(ApiKey).filter(ApiKey.usuario_id == usuario_id).one()
        assert movida.clave_hash == clave_hash
        assert movida.revocada_en is None

    # Y es idempotente: correrla otra vez no duplica nada.
    migrar(engine)
    with session_scope() as sesion:
        assert sesion.query(ApiKey).filter(ApiKey.usuario_id == usuario_id).count() == 1


# ============================================================================
# SPA
# ============================================================================

def test_las_rutas_del_spa_no_chocan_con_las_de_la_api(cliente):
    """Sin el prefijo /api, `GET /documentos` seria la pantalla y el endpoint.

    El navegador que entra a /documentos tiene que recibir la aplicacion, y el
    cliente que pide /api/documentos, JSON.
    """
    from ocr_engine.web_interface.estaticos import hay_build

    if not hay_build():
        pytest.skip("el SPA no esta compilado (npm run build en frontend/)")

    for ruta in ("/", "/documentos", "/revision", "/cuenta", "/lo-que-sea"):
        respuesta = cliente.get(ruta)
        assert respuesta.status_code == 200, ruta
        assert respuesta.headers["content-type"].startswith("text/html"), ruta

    # Y la API sigue siendo JSON, incluso cuando no encuentra la ruta.
    datos = cliente.get("/api/documentos")
    assert datos.headers["content-type"].startswith("application/json")

    inexistente = cliente.get("/api/no-existe")
    assert inexistente.status_code == 404
    assert inexistente.headers["content-type"].startswith("application/json")


# ============================================================================
# MIGRACIÓN DESDE UNA BASE VIEJA DE VERDAD
# ============================================================================

# Esquema anterior a la sesión de navegador: la clave vive en `usuarios`, no hay
# `password_hash` y no existen `api_keys` ni `sesiones`. Se escribe a mano en vez
# de derivarlo de los modelos actuales porque el punto de la prueba es justamente
# arrancar de un esquema que los modelos ya no describen.
_ESQUEMA_VIEJO = """
CREATE TABLE usuarios (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL,
    email VARCHAR(320),
    api_key_hash VARCHAR(64) NOT NULL,
    api_key_prefijo VARCHAR(12) NOT NULL,
    plan VARCHAR(50),
    activo BOOLEAN,
    creado_en DATETIME,
    UNIQUE (email),
    UNIQUE (api_key_hash)
);
CREATE TABLE documentos (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    usuario_id VARCHAR(36) NOT NULL,
    titulo VARCHAR(500) NOT NULL,
    estado VARCHAR(30),
    total_paginas INTEGER,
    total_bloques INTEGER,
    inconsistencias INTEGER,
    necesita_revision BOOLEAN,
    error TEXT,
    resultado JSON,
    creado_en DATETIME,
    actualizado_en DATETIME,
    FOREIGN KEY(usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
);
"""


def _base_con_esquema_viejo(tmp_path):
    """Crea una base con el esquema anterior y devuelve (engine, clave_en_claro)."""
    import sqlite3

    from sqlalchemy import create_engine

    ruta = tmp_path / "vieja.db"
    clave, clave_hash, prefijo = auth.generar_api_key()
    usuario_id = str(uuid4())

    conexion = sqlite3.connect(ruta)
    conexion.executescript(_ESQUEMA_VIEJO)
    conexion.execute(
        "INSERT INTO usuarios VALUES (?,?,?,?,?,?,?,?)",
        (usuario_id, "Cliente Viejo", "viejo@ejemplo.com", clave_hash, prefijo,
         "pro", 1, "2026-08-01 10:00:00"),
    )
    conexion.execute(
        "INSERT INTO documentos (id, usuario_id, titulo, estado, total_paginas)"
        " VALUES (?,?,?,?,?)",
        (str(uuid4()), usuario_id, "viejo.pdf", "completado", 21),
    )
    conexion.commit()
    conexion.close()

    return create_engine(f"sqlite:///{ruta}", future=True), clave


def test_migrar_una_base_vieja_no_falla_y_conserva_los_datos(tmp_path):
    """El caso que rompía el arranque: una base sin la tabla `api_keys`.

    La otra prueba de migración inserta la fila vieja en una base ya migrada, así
    que `api_keys` existe y el backfill nunca se topa con su ausencia. Acá la base
    arranca con el esquema anterior de verdad, que es lo que hay en un despliegue.
    """
    from sqlalchemy import text

    from ocr_engine.persistence.db import Base
    from ocr_engine.persistence.migraciones import migrar

    engine_viejo, clave = _base_con_esquema_viejo(tmp_path)

    # El mismo orden que init_db: crear lo que falta y recién después migrar.
    Base.metadata.create_all(engine_viejo)
    hechos = migrar(engine_viejo)

    assert any("api_keys" in h for h in hechos)

    with engine_viejo.begin() as conexion:
        clave_hash = auth.hashear_api_key(clave)
        fila = conexion.execute(
            text("SELECT usuario_id, nombre FROM api_keys WHERE clave_hash = :h"),
            {"h": clave_hash},
        ).fetchone()
        assert fila is not None, "la clave vieja no se movió a api_keys"

        # Los datos previos no se pierden al reconstruir `usuarios`.
        assert conexion.execute(text("SELECT COUNT(*) FROM usuarios")).scalar() == 1
        assert conexion.execute(text("SELECT COUNT(*) FROM documentos")).scalar() == 1
        assert conexion.execute(
            text("SELECT password_hash FROM usuarios")
        ).scalar() is None

    # Idempotente: volver a migrar no duplica la clave ni explota.
    migrar(engine_viejo)
    with engine_viejo.begin() as conexion:
        assert conexion.execute(text("SELECT COUNT(*) FROM api_keys")).scalar() == 1


def test_migrar_antes_de_crear_las_tablas_falla(tmp_path):
    """Fija el orden de init_db: create_all va primero.

    El backfill escribe en `api_keys`; invertir el orden hacía que el arranque
    muriera con "no such table: api_keys" contra cualquier base ya desplegada.
    Si alguien vuelve a invertirlo, esta prueba lo señala.
    """
    from sqlalchemy.exc import OperationalError

    engine_viejo, _ = _base_con_esquema_viejo(tmp_path)

    from ocr_engine.persistence.migraciones import migrar

    with pytest.raises(OperationalError, match="api_keys"):
        migrar(engine_viejo)
