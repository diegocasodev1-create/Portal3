"""Acceso a Azure SQL (core.UsuariosEntel) con pyodbc. Todas las consultas son parametrizadas.

Tipos reales (INFORMATION_SCHEMA.COLUMNS):
  Id int IDENTITY | Correo nvarchar(256) NOT NULL, único (UQ_UsuariosEntel_Correo), CI
  Nombre nvarchar(100) NOT NULL | Apellido nvarchar(100) NOT NULL | Gerencia nvarchar(150) NULL
  Portal1/Portal2 bit NOT NULL default 0 | Activo bit NOT NULL default 1
  FechaAlta datetime2 NOT NULL default sysutcdatetime() | Portal3/InvitacionEnviada bit NULL

Vista core.vHistorialAccesos (solo lectura; la mantiene el usuario, no esta app):
  Fecha datetime2(0) en UTC | Correo (minúsculas) | Usuario (Nombre + Apellido; vacío o NULL si el
  correo no está en UsuariosEntel) | Portal ('Energía' | 'MiraStock') | Resultado ('OK' | 'Denegado')
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator

import pyodbc

from app.config import get_settings


class CorreoDuplicado(Exception):
    """El correo ya existe en core.UsuariosEntel."""


_COLUMNAS = """Id, Correo, Nombre, Apellido, Gerencia,
    ISNULL(Portal1, 0) AS Portal1, ISNULL(Portal2, 0) AS Portal2, ISNULL(Portal3, 0) AS Portal3,
    ISNULL(Activo, 0) AS Activo, ISNULL(InvitacionEnviada, 0) AS InvitacionEnviada, FechaAlta"""


def _valor_odbc(v: str) -> str:
    # Encierra el valor entre llaves para que caracteres como ; o } no rompan la cadena.
    return "{" + v.replace("}", "}}") + "}"


def _cadena_conexion() -> str:
    s = get_settings()
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{s.sql_server},1433;"
        f"DATABASE={s.sql_database};"
        f"UID={_valor_odbc(s.sql_user)};"
        f"PWD={_valor_odbc(s.sql_password.get_secret_value())};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )


@contextmanager
def _conexion() -> Iterator[pyodbc.Connection]:
    conn = pyodbc.connect(_cadena_conexion(), autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fila(cursor: pyodbc.Cursor, row: pyodbc.Row) -> dict[str, Any]:
    d = {col[0]: valor for col, valor in zip(cursor.description, row)}
    for campo in ("Portal1", "Portal2", "Portal3", "Activo", "InvitacionEnviada"):
        d[campo] = bool(d[campo])
    d["Apellido"] = d["Apellido"] or ""
    d["FechaAlta"] = d["FechaAlta"].strftime("%Y-%m-%d") if d["FechaAlta"] else None
    return d


def es_admin(correo: str) -> bool:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM core.UsuariosEntel "
            "WHERE Correo = ? AND ISNULL(Portal3, 0) = 1 AND ISNULL(Activo, 0) = 1",
            correo,
        )
        return cur.fetchone() is not None


def listar_gerencias() -> list[str]:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT Gerencia FROM ("
            " SELECT DISTINCT Gerencia FROM core.StockLurinERI WHERE Gerencia IS NOT NULL"
            " UNION"
            " SELECT DISTINCT Gerencia FROM core.UsuariosEntel WHERE Gerencia IS NOT NULL"
            ") g WHERE LTRIM(RTRIM(Gerencia)) <> '' ORDER BY Gerencia"
        )
        return [r[0] for r in cur.fetchall()]


def listar_usuarios() -> list[dict[str, Any]]:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNAS} FROM core.UsuariosEntel ORDER BY FechaAlta DESC, Id DESC")
        return [_fila(cur, r) for r in cur.fetchall()]


def listar_usuarios_con_acceso() -> list[dict[str, Any]]:
    """Usuarios activos con al menos un portal (los que necesitan cuenta en External ID)."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_COLUMNAS} FROM core.UsuariosEntel"
            " WHERE ISNULL(Activo, 0) = 1"
            " AND (ISNULL(Portal1, 0) = 1 OR ISNULL(Portal2, 0) = 1 OR ISNULL(Portal3, 0) = 1)"
            " ORDER BY Correo"
        )
        return [_fila(cur, r) for r in cur.fetchall()]


def obtener_usuario(usuario_id: int) -> dict[str, Any] | None:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNAS} FROM core.UsuariosEntel WHERE Id = ?", usuario_id)
        row = cur.fetchone()
        return _fila(cur, row) if row else None


def existe_correo(correo: str) -> bool:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM core.UsuariosEntel WHERE Correo = ?", correo)
        return cur.fetchone() is not None


def crear_usuario(
    correo: str, nombre: str, apellido: str, gerencia: str, portal1: bool, portal2: bool, portal3: bool
) -> dict[str, Any]:
    try:
        with _conexion() as conn:
            cur = conn.cursor()
            cur.execute(
                "SET NOCOUNT ON;"
                " INSERT INTO core.UsuariosEntel"
                " (Correo, Nombre, Apellido, Gerencia, Portal1, Portal2, Portal3, Activo, InvitacionEnviada)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0);"
                " SELECT CAST(SCOPE_IDENTITY() AS INT);",
                correo, nombre, apellido, gerencia, portal1, portal2, portal3,
            )
            nuevo_id = cur.fetchone()[0]
    except pyodbc.IntegrityError as e:
        # 2627 = restricción UNIQUE, 2601 = índice único
        if "2627" in str(e) or "2601" in str(e):
            raise CorreoDuplicado() from None
        raise
    usuario = obtener_usuario(nuevo_id)
    assert usuario is not None
    return usuario


def actualizar_usuario(
    usuario_id: int, nombre: str, apellido: str, gerencia: str, portal1: bool, portal2: bool, portal3: bool
) -> bool:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE core.UsuariosEntel"
            " SET Nombre = ?, Apellido = ?, Gerencia = ?, Portal1 = ?, Portal2 = ?, Portal3 = ?"
            " WHERE Id = ?",
            nombre, apellido, gerencia, portal1, portal2, portal3, usuario_id,
        )
        return cur.rowcount > 0


def eliminar_usuario(usuario_id: int) -> bool:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM core.UsuariosEntel WHERE Id = ?", usuario_id)
        return cur.rowcount > 0


def marcar_invitacion_enviada(usuario_id: int) -> None:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE core.UsuariosEntel SET InvitacionEnviada = 1 WHERE Id = ?", usuario_id)


# ---------------------------------------------------------------------------
# Historial de accesos (solo lectura sobre core.vHistorialAccesos)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FiltrosHistorial:
    """Filtros opcionales. `desde` es inclusivo y `hasta` exclusivo, ambos en UTC sin zona."""

    correo: str | None = None
    portal: str | None = None
    resultado: str | None = None
    desde: datetime | None = None
    hasta: datetime | None = None


def _escapar_like(texto: str) -> str:
    # Con ESCAPE '\' los comodines del texto se buscan como caracteres literales.
    return "".join("\\" + c if c in "\\%_[" else c for c in texto)


def _where_historial(filtros: FiltrosHistorial) -> tuple[str, list[Any]]:
    """Arma el WHERE con fragmentos fijos y parámetros `?`."""
    condiciones: list[str] = []
    params: list[Any] = []
    if filtros.correo:
        condiciones.append("Correo LIKE ? ESCAPE '\\'")
        params.append("%" + _escapar_like(filtros.correo.strip().lower()) + "%")
    if filtros.portal:
        condiciones.append("Portal = ?")
        params.append(filtros.portal)
    if filtros.resultado:
        condiciones.append("Resultado = ?")
        params.append(filtros.resultado)
    if filtros.desde:
        condiciones.append("Fecha >= ?")
        params.append(filtros.desde)
    if filtros.hasta:
        condiciones.append("Fecha < ?")
        params.append(filtros.hasta)
    sql = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
    return sql, params


def listar_historial(
    filtros: FiltrosHistorial, pagina: int, tamano: int = 50
) -> tuple[list[dict[str, Any]], int]:
    """Filas de la página pedida (Fecha DESC) y el total de filas que cumplen los filtros."""
    where, params = _where_historial(filtros)
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM core.vHistorialAccesos{where}", *params)
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT Fecha, ISNULL(Usuario, '') AS Usuario, Correo, Portal, Resultado"
            f" FROM core.vHistorialAccesos{where}"
            " ORDER BY Fecha DESC, Correo"
            " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            *params, (pagina - 1) * tamano, tamano,
        )
        filas = [
            {"Fecha": r[0], "Usuario": (r[1] or "").strip(), "Correo": r[2], "Portal": r[3], "Resultado": r[4]}
            for r in cur.fetchall()
        ]
    return filas, total


def resumen_historial(filtros: FiltrosHistorial, tz_offset_min: int) -> dict[str, Any]:
    """Totales e indicadores. Los días se agrupan en hora local: DATEADD(minute, tz_offset_min, Fecha)."""
    where, params = _where_historial(filtros)
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*), COUNT(DISTINCT Correo),"
            " ISNULL(SUM(CASE WHEN Portal = N'Energía' THEN 1 ELSE 0 END), 0),"
            " ISNULL(SUM(CASE WHEN Portal = 'MiraStock' THEN 1 ELSE 0 END), 0),"
            " ISNULL(SUM(CASE WHEN Resultado = 'Denegado' THEN 1 ELSE 0 END), 0)"
            f" FROM core.vHistorialAccesos{where}",
            *params,
        )
        total, unicos, energia, mirastock, denegados = cur.fetchone()
        cur.execute(
            "SELECT Dia, COUNT(*) FROM ("
            " SELECT CAST(DATEADD(minute, ?, Fecha) AS date) AS Dia"
            f" FROM core.vHistorialAccesos{where}"
            ") d GROUP BY Dia ORDER BY Dia",
            tz_offset_min, *params,
        )
        por_dia = [{"dia": _texto_dia(r[0]), "total": r[1]} for r in cur.fetchall()]
    return {
        "total": total,
        "usuariosUnicos": unicos,
        "porPortal": {"Energía": energia, "MiraStock": mirastock},
        "denegados": denegados,
        "porDia": por_dia,
    }


def _texto_dia(valor: Any) -> str:
    # El driver devuelve date (o str con controladores antiguos).
    return valor.isoformat() if isinstance(valor, date) else str(valor)[:10]
