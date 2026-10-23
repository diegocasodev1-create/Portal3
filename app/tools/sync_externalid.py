"""Sincronización única: crea en External ID las cuentas que faltan para los usuarios con acceso.

Uso (desde la raíz del repo, con el .env local):
    python -m app.tools.sync_externalid            # modo prueba: no crea nada
    python -m app.tools.sync_externalid --apply    # crea las cuentas que faltan

Lee de core.UsuariosEntel los usuarios con Activo=1 y al menos un portal. No imprime secretos.
Las cuentas antiguas con contraseña (identidad emailAddress) se informan aparte y no se duplican.
"""

import argparse
import logging
import sys
from collections import Counter

from app import db, externalid


def _tabla(encabezados: list[str], filas: list[list[str]]) -> str:
    anchos = [max(len(str(x)) for x in col) for col in zip(encabezados, *filas)]
    linea = lambda valores: " | ".join(str(v).ljust(a) for v, a in zip(valores, anchos)).rstrip()
    separador = "-+-".join("-" * a for a in anchos)
    return "\n".join([linea(encabezados), separador, *(linea(f) for f in filas)])


# Estado por tipo de cuenta encontrada (modo prueba) y por resultado de asegurar() (--apply).
_ESTADO_PRUEBA = {
    externalid.TIPO_CODIGO: "Ya existe (código)",
    externalid.TIPO_CONTRASENA: "Ya existe (contraseña, antigua)",
    None: "Se crearía",
}
_ESTADO_APPLY = {
    externalid.EXISTE_CODIGO: "Ya existía (código)",
    externalid.EXISTE_CONTRASENA: "Ya existía (contraseña, antigua)",
    externalid.CREADA: "Creada",
}


def _nombre(u: dict) -> str:
    return f"{u['Nombre']} {u['Apellido']}".strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.sync_externalid",
        description="Crea en External ID las cuentas que faltan (por defecto, solo muestra qué haría).",
    )
    parser.add_argument("--apply", action="store_true", help="crea las cuentas que faltan")
    args = parser.parse_args(argv)

    try:
        externalid.verificar_configuracion()
    except externalid.ErrorExternalId as e:
        print(f"No se puede sincronizar: {e.motivo}.")
        return 2

    usuarios = db.listar_usuarios_con_acceso()
    print(f"Usuarios activos con al menos un portal: {len(usuarios)}")
    print("Modo: " + ("APLICAR (se crean las cuentas que faltan)" if args.apply else "PRUEBA (no se crea nada)"))
    print()

    totales: Counter[str] = Counter()
    filas: list[list[str]] = []
    for u in usuarios:
        correo = u["Correo"]
        try:
            if args.apply:
                _, resultado = externalid.asegurar(correo, u["Nombre"], u["Apellido"])
                estado = _ESTADO_APPLY[resultado]
            else:
                cuenta = externalid.buscar_por_correo(correo)
                estado = _ESTADO_PRUEBA[cuenta.tipo if cuenta else None]
            totales[estado] += 1
        except externalid.ErrorExternalId as e:
            estado = f"Error: {e.motivo}"
            totales["Error"] += 1
        filas.append([correo, estado] if args.apply else [correo, _nombre(u), estado])

    if filas:
        encabezados = ["Correo", "Resultado"] if args.apply else ["Correo", "Nombre", "Estado"]
        print(_tabla(encabezados, filas))
        print()

    orden = [*(_ESTADO_APPLY if args.apply else _ESTADO_PRUEBA).values(), "Error"]
    print("Resumen: " + ", ".join(f"{clave}: {totales[clave]}" for clave in orden) + f" (total: {len(usuarios)})")
    if totales[_ESTADO_PRUEBA[externalid.TIPO_CONTRASENA]] or totales[_ESTADO_APPLY[externalid.EXISTE_CONTRASENA]]:
        print("Las cuentas antiguas con contraseña no se tocan: para que entren solo con código, elimínalas "
              "(también de la papelera) y vuelve a ejecutar con --apply.")
    return 1 if totales["Error"] else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    for _ruidoso in ("msal", "httpx", "httpcore", "urllib3"):
        logging.getLogger(_ruidoso).setLevel(logging.WARNING)
    sys.exit(main())
