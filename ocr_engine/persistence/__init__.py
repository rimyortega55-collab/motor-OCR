"""Persistencia del motor: usuarios, documentos, costos y decisiones.

Reemplaza el almacenamiento en memoria de la Capa 7 y los archivos JSONL de
ruta relativa que usaban las Capas 5 y 6. Ambos esquemas servían para correr en
una notebook, pero no sobreviven a un despliegue: el diccionario se pierde en
cada reinicio y los JSONL se escriben dentro del contenedor, con lo que el
registro de costos -el que haría falta para facturar- desaparece justo cuando
más importa.

El motor de base de datos se elige con la variable de entorno DATABASE_URL. Por
defecto usa SQLite sobre un archivo local, que alcanza para una instancia con
volumen persistente; para varias instancias basta apuntar la variable a Postgres
sin tocar código.
"""

from .db import Base, get_session, init_db, session_scope
from .models import (
    ApiKey,
    BloqueAlmacenado,
    CostoRegistrado,
    DecisionAlmacenada,
    DocumentoAlmacenado,
    Sesion,
    UmbralesUsuario,
    Usuario,
)

__all__ = [
    "Base",
    "get_session",
    "init_db",
    "session_scope",
    "Usuario",
    "ApiKey",
    "BloqueAlmacenado",
    "Sesion",
    "DocumentoAlmacenado",
    "CostoRegistrado",
    "DecisionAlmacenada",
    "UmbralesUsuario",
]
