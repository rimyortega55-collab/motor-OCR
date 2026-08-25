"""CLI de administración de usuarios y API keys.

    python -m ocr_engine.web_interface.gestion_usuarios crear "Nombre" --email a@b.com
    python -m ocr_engine.web_interface.gestion_usuarios listar
    python -m ocr_engine.web_interface.gestion_usuarios desactivar <id>

La clave en claro se imprime una única vez, al crearla: en la base sólo queda su
hash, así que no hay manera de volver a mostrarla. Si se pierde, se da de baja
al usuario y se crea otro.
"""

from __future__ import annotations

import argparse
import sys

from ocr_engine.persistence import ApiKey, Usuario, init_db, session_scope
from .auth import crear_usuario


def _cmd_crear(args: argparse.Namespace) -> int:
    with session_scope() as sesion:
        if args.email:
            existente = (
                sesion.query(Usuario).filter(Usuario.email == args.email).one_or_none()
            )
            if existente is not None:
                print(f"Ya existe un usuario con el email {args.email}", file=sys.stderr)
                return 1

        usuario, clave = crear_usuario(
            sesion,
            nombre=args.nombre,
            email=args.email,
            plan=args.plan,
            password=args.password,
        )

        print(f"Usuario creado: {usuario.nombre}  (id {usuario.id}, plan {usuario.plan})")
        print()
        print(f"  API key: {clave}")
        print()
        print("Guardala ahora: no se puede volver a mostrar.")
    return 0


def _cmd_listar(_: argparse.Namespace) -> int:
    with session_scope() as sesion:
        usuarios = sesion.query(Usuario).order_by(Usuario.creado_en).all()

        if not usuarios:
            print("No hay usuarios. Creá uno con: gestion_usuarios crear \"Nombre\"")
            return 0

        print(f"{'ID':38} {'NOMBRE':22} {'PLAN':10} {'CLAVES':7} ESTADO")
        for u in usuarios:
            estado = "activo" if u.activo else "desactivado"
            # Las claves viven en api_keys desde que un usuario puede tener varias.
            activas = (
                sesion.query(ApiKey)
                .filter(ApiKey.usuario_id == u.id, ApiKey.revocada_en.is_(None))
                .count()
            )
            print(f"{u.id:38} {u.nombre[:22]:22} {u.plan:10} {activas:<7} {estado}")
    return 0


def _cmd_desactivar(args: argparse.Namespace) -> int:
    with session_scope() as sesion:
        usuario = sesion.query(Usuario).filter(Usuario.id == args.id).one_or_none()
        if usuario is None:
            print(f"No existe el usuario {args.id}", file=sys.stderr)
            return 1

        usuario.activo = False
        print(f"Usuario {usuario.nombre} desactivado; sus API keys dejan de servir.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administración de usuarios del motor OCR")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_crear = sub.add_parser("crear", help="Crea un usuario y su API key")
    p_crear.add_argument("nombre")
    p_crear.add_argument("--email", default=None)
    p_crear.add_argument("--plan", default="libre")
    p_crear.add_argument(
        "--password",
        default=None,
        help="Habilita el ingreso por navegador. Sin esto el usuario sólo usa la API key.",
    )
    p_crear.set_defaults(func=_cmd_crear)

    p_listar = sub.add_parser("listar", help="Lista los usuarios")
    p_listar.set_defaults(func=_cmd_listar)

    p_desactivar = sub.add_parser("desactivar", help="Desactiva un usuario")
    p_desactivar.add_argument("id")
    p_desactivar.set_defaults(func=_cmd_desactivar)

    args = parser.parse_args(argv)

    init_db()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
