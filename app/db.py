"""Acceso a Azure SQL (core.UsuariosEntel) con pyodbc. Todas las consultas son parametrizadas.

Tipos reales (INFORMATION_SCHEMA.COLUMNS):
  Id int IDENTITY | Correo nvarchar(256) NOT NULL, único (UQ_UsuariosEntel_Correo), CI
  Nombre nvarchar(100) NOT NULL | Apellido nvarchar(100) NOT NULL | Gerencia nvarchar(150) NULL
  Portal1/Portal2 bit NOT NULL default 0 | Activo bit NOT NULL default 1
  FechaAlta datetime2 NOT NULL default sysutcdatetime() | Portal3/InvitacionEnviada bit NULL
  Cliente nvarchar(100) NOT NULL default 'Otro' ('Entel' | 'MiraGroup' | 'Otro'; v12)
  Portal3 ya no da acceso a esta app (v12): es solo un dato. El acceso lo da core.AdministradoresPortal.

Tabla core.AdministradoresPortal (la crea y la mantiene el usuario; los administradores se crean por SQL):
  Id int PK | Nombre nvarchar(150) | Correo nvarchar(256) único (UQ_AdministradoresPortal_Correo), minúsculas
  ContrasenaHash varbinary(256) | ContrasenaSal varbinary(64) | AlgoritmoHash varchar(20) ('SHA2_512' | 'PBKDF2_SHA256')
  DebeCambiarContrasena bit default 1 | Activo bit default 1 | IntentosFallidos int default 0
  BloqueadoHasta / UltimoAcceso / FechaCambioContrasena datetime2 NULL (UTC) | FechaAlta datetime2 default sysutcdatetime()
  sp_RestablecerContrasenaAdmin vuelve a la contraseña por defecto con DebeCambiarContrasena = 1.

Vista core.vHistorialAccesos (solo lectura; la mantiene el usuario, no esta app):
  Fecha datetime2(0) en UTC | Correo (minúsculas) | Usuario (Nombre + Apellido; vacío o NULL si el
  correo no está en UsuariosEntel) | Portal ('Energía' | 'MiraStock') | Resultado ('OK' | 'Denegado')
  FinalSesion datetime2(0) UTC (último latido; NULL sin latidos) | TiempoSesionSeg int (FinalSesion − Fecha;
  NULL sin latidos) | EnCurso bit (1 si el último latido tiene menos de 5 minutos; 0 si se cerró con botón)
  | CierreExplicito bit (1 si la sesión se cerró con el botón «Atrás» o «Cerrar sesión»)

Latidos (POST /api/latido) escriben FinalSesion en core.SesionesAgente (MiraStock) y core.HistorialAccesos (Energía).
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator

import pyodbc

from app.config import get_settings


class CorreoDuplicado(Exception):
    """El correo ya existe en core.UsuariosEntel."""


_COLUMNAS = """Id, Correo, Nombre, Apellido, Gerencia, Cliente,
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
    correo: str, nombre: str, apellido: str, gerencia: str, cliente: str, portal1: bool, portal2: bool, portal3: bool
) -> dict[str, Any]:
    try:
        with _conexion() as conn:
            cur = conn.cursor()
            cur.execute(
                "SET NOCOUNT ON;"
                " INSERT INTO core.UsuariosEntel"
                " (Correo, Nombre, Apellido, Gerencia, Cliente, Portal1, Portal2, Portal3, Activo, InvitacionEnviada)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0);"
                " SELECT CAST(SCOPE_IDENTITY() AS INT);",
                correo, nombre, apellido, gerencia, cliente, portal1, portal2, portal3,
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
    usuario_id: int, nombre: str, apellido: str, gerencia: str, cliente: str, portal1: bool, portal2: bool, portal3: bool
) -> bool:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE core.UsuariosEntel"
            " SET Nombre = ?, Apellido = ?, Gerencia = ?, Cliente = ?, Portal1 = ?, Portal2 = ?, Portal3 = ?"
            " WHERE Id = ?",
            nombre, apellido, gerencia, cliente, portal1, portal2, portal3, usuario_id,
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
# Administradores de Portal3 (core.AdministradoresPortal)
# ---------------------------------------------------------------------------

INTENTOS_PARA_BLOQUEO = 5
MINUTOS_BLOQUEO = 15
# La contraseña por defecto solo sirve estas horas desde el alta o el último restablecimiento.
HORAS_CONTRASENA_POR_DEFECTO = 72

# El reloj es el de SQL (SYSUTCDATETIME), igual que en los latidos: Bloqueado y PorDefectoVencida se calculan ahí.
_COLUMNAS_ADMIN = f"""Id, Nombre, Correo, ContrasenaHash, ContrasenaSal, AlgoritmoHash,
    ISNULL(DebeCambiarContrasena, 0) AS DebeCambiarContrasena, ISNULL(Activo, 0) AS Activo,
    ISNULL(IntentosFallidos, 0) AS IntentosFallidos, BloqueadoHasta, UltimoAcceso,
    CASE WHEN BloqueadoHasta > SYSUTCDATETIME() THEN 1 ELSE 0 END AS Bloqueado,
    CASE WHEN DATEADD(HOUR, {HORAS_CONTRASENA_POR_DEFECTO}, COALESCE(FechaCambioContrasena, FechaAlta))
        < SYSUTCDATETIME() THEN 1 ELSE 0 END AS PorDefectoVencida"""

# Un fallo con el bloqueo anterior ya vencido empieza la cuenta de nuevo (si no, el primer error volvería a bloquear).
# En un UPDATE, todas las expresiones de SET ven los valores previos de la fila.
_SQL_FALLO_ADMIN = (
    "UPDATE core.AdministradoresPortal SET"
    " IntentosFallidos = CASE WHEN BloqueadoHasta <= SYSUTCDATETIME() THEN 1"
    "  ELSE ISNULL(IntentosFallidos, 0) + 1 END,"
    " BloqueadoHasta = CASE WHEN BloqueadoHasta <= SYSUTCDATETIME() THEN NULL"
    f"  WHEN ISNULL(IntentosFallidos, 0) + 1 >= {INTENTOS_PARA_BLOQUEO}"
    f"  THEN DATEADD(MINUTE, {MINUTOS_BLOQUEO}, SYSUTCDATETIME())"
    "  ELSE BloqueadoHasta END"
    " WHERE Id = ? AND (BloqueadoHasta IS NULL OR BloqueadoHasta <= SYSUTCDATETIME())"
)


def _fila_admin(cursor: pyodbc.Cursor, row: pyodbc.Row) -> dict[str, Any]:
    d = {col[0]: valor for col, valor in zip(cursor.description, row)}
    for campo in ("DebeCambiarContrasena", "Activo", "Bloqueado", "PorDefectoVencida"):
        d[campo] = bool(d[campo])
    d["ContrasenaHash"] = bytes(d["ContrasenaHash"] or b"")
    d["ContrasenaSal"] = bytes(d["ContrasenaSal"] or b"")
    return d


def obtener_admin(admin_id: int) -> dict[str, Any] | None:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNAS_ADMIN} FROM core.AdministradoresPortal WHERE Id = ?", admin_id)
        row = cur.fetchone()
        return _fila_admin(cur, row) if row else None


def obtener_admin_por_correo(correo: str) -> dict[str, Any] | None:
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNAS_ADMIN} FROM core.AdministradoresPortal WHERE Correo = ?", correo)
        row = cur.fetchone()
        return _fila_admin(cur, row) if row else None


def listar_admins() -> list[dict[str, Any]]:
    """Todos los administradores (también los inactivos), sin hash ni sal."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT Id, Nombre, Correo, ISNULL(Activo, 0) AS Activo, UltimoAcceso, BloqueadoHasta,"
            " CASE WHEN BloqueadoHasta > SYSUTCDATETIME() THEN 1 ELSE 0 END AS Bloqueado"
            " FROM core.AdministradoresPortal ORDER BY Nombre, Correo"
        )
        filas = []
        for row in cur.fetchall():
            d = {col[0]: valor for col, valor in zip(cur.description, row)}
            d["Activo"] = bool(d["Activo"])
            d["Bloqueado"] = bool(d["Bloqueado"])
            filas.append(d)
        return filas


def registrar_fallo_admin(admin_id: int) -> None:
    """Suma un intento fallido; al llegar a INTENTOS_PARA_BLOQUEO bloquea MINUTOS_BLOQUEO minutos."""
    with _conexion() as conn:
        conn.cursor().execute(_SQL_FALLO_ADMIN, admin_id)


def registrar_exito_admin(admin_id: int, es_ingreso: bool) -> None:
    """Contraseña correcta: reinicia los intentos. UltimoAcceso solo cambia en el login (no en las cards)."""
    with _conexion() as conn:
        conn.cursor().execute(
            "UPDATE core.AdministradoresPortal SET IntentosFallidos = 0, BloqueadoHasta = NULL"
            + (", UltimoAcceso = SYSUTCDATETIME()" if es_ingreso else "")
            + " WHERE Id = ?",
            admin_id,
        )


def cambiar_contrasena_admin(admin_id: int, hash_: bytes, sal: bytes, algoritmo: str) -> None:
    """Contraseña nueva elegida por el administrador: ya no debe cambiarla y se desbloquea."""
    with _conexion() as conn:
        conn.cursor().execute(
            "UPDATE core.AdministradoresPortal SET ContrasenaHash = ?, ContrasenaSal = ?, AlgoritmoHash = ?,"
            " DebeCambiarContrasena = 0, FechaCambioContrasena = SYSUTCDATETIME(),"
            " IntentosFallidos = 0, BloqueadoHasta = NULL WHERE Id = ?",
            pyodbc.Binary(hash_), pyodbc.Binary(sal), algoritmo, admin_id,
        )


def migrar_hash_admin(admin_id: int, hash_anterior: bytes, hash_: bytes, sal: bytes, algoritmo: str) -> bool:
    """Pasa la misma contraseña a otro algoritmo. No toca nada si el hash cambió entretanto (p. ej. un restablecimiento)."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE core.AdministradoresPortal SET ContrasenaHash = ?, ContrasenaSal = ?, AlgoritmoHash = ?"
            " WHERE Id = ? AND ContrasenaHash = ? AND ISNULL(DebeCambiarContrasena, 0) = 0",
            pyodbc.Binary(hash_), pyodbc.Binary(sal), algoritmo, admin_id, pyodbc.Binary(hash_anterior),
        )
        return cur.rowcount > 0


def actualizar_admin(admin_id: int, nombre: str, correo: str) -> bool:
    try:
        with _conexion() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE core.AdministradoresPortal SET Nombre = ?, Correo = ? WHERE Id = ?", nombre, correo, admin_id
            )
            return cur.rowcount > 0
    except pyodbc.IntegrityError as e:
        if "2627" in str(e) or "2601" in str(e):
            raise CorreoDuplicado() from None
        raise


# ---------------------------------------------------------------------------
# Latidos de sesión (POST /api/latido)
# ---------------------------------------------------------------------------

# Un latido no reescribe FinalSesion si el anterior llegó hace menos de 60 s, y nunca toca una sesión cerrada.
_SQL_LATIDO_MIRASTOCK = (
    "UPDATE core.SesionesAgente SET FinalSesion = SYSUTCDATETIME()"
    " WHERE Token = ? AND CreadoEn >= DATEADD(HOUR, -12, SYSUTCDATETIME())"
    " AND COALESCE(CierreExplicito, 0) = 0"
    " AND (FinalSesion IS NULL OR FinalSesion < DATEADD(SECOND, -60, SYSUTCDATETIME()))"
)

# Cierre con botón: sin la regla de 60 s. ExpiraEn se adelanta a ahora, así el agente ya no acepta la llave.
_SQL_CIERRE_MIRASTOCK = (
    "UPDATE core.SesionesAgente"
    " SET FinalSesion = SYSUTCDATETIME(),"
    " ExpiraEn = CASE WHEN ExpiraEn > SYSUTCDATETIME() THEN SYSUTCDATETIME() ELSE ExpiraEn END,"
    " CierreExplicito = 1"
    " WHERE Token = ? AND CreadoEn >= DATEADD(HOUR, -12, SYSUTCDATETIME()) AND COALESCE(CierreExplicito, 0) = 0"
)

# Energía: la fila activa es la MÁS RECIENTE de la ventana de 30 min (abierta o cerrada); después se decide
# según su estado. Todo va en un batch dentro de la transacción de la conexión: UPDLOCK + HOLDLOCK bloquean el
# rango buscado hasta el commit, así dos latidos simultáneos no insertan dos filas.
_SQL_ENERGIA_INICIO = (
    "SET NOCOUNT ON; SET XACT_ABORT ON;"
    " DECLARE @correo NVARCHAR(256) = ?;"
    " DECLARE @ahora DATETIME2 = SYSUTCDATETIME();"
    " DECLARE @previa TABLE (Cerrada BIT, FinalSesion DATETIME2(0));"
    " WITH ult AS ("
    " SELECT TOP (1) FinalSesion, CierreExplicito FROM core.HistorialAccesos WITH (UPDLOCK, HOLDLOCK)"
    " WHERE Correo = @correo AND Portal = N'Energía' AND Resultado = N'OK'"
    " AND COALESCE(FinalSesion, Fecha) >= DATEADD(MINUTE, -30, @ahora)"
    " ORDER BY Fecha DESC)"
)

# Latido normal: abierta → FinalSesion (regla de 60 s); cerrada hace 60 s o más, o sin fila → INSERT;
# cerrada hace menos de 60 s → se ignora (un latido que venía en camino al momento del cierre).
_SQL_LATIDO_ENERGIA = _SQL_ENERGIA_INICIO + (
    " UPDATE ult SET FinalSesion = CASE"
    " WHEN COALESCE(CierreExplicito, 0) = 0"
    " AND (FinalSesion IS NULL OR FinalSesion < DATEADD(SECOND, -60, @ahora))"
    " THEN @ahora ELSE FinalSesion END"
    " OUTPUT COALESCE(deleted.CierreExplicito, 0), deleted.FinalSesion INTO @previa;"
    " IF NOT EXISTS (SELECT 1 FROM @previa)"
    " OR EXISTS (SELECT 1 FROM @previa WHERE Cerrada = 1"
    " AND (FinalSesion IS NULL OR FinalSesion < DATEADD(SECOND, -60, @ahora)))"
    " BEGIN"
    " INSERT INTO core.HistorialAccesos (Correo, Portal, Resultado, Fecha, FinalSesion)"
    " VALUES (@correo, N'Energía', N'OK', @ahora, @ahora);"
    " SELECT CAST(1 AS BIT);"
    " END"
    " ELSE SELECT CAST(0 AS BIT);"
)

# Cierre: solo si la fila más reciente está abierta. Nunca inserta.
_SQL_CIERRE_ENERGIA = _SQL_ENERGIA_INICIO + (
    " UPDATE ult SET"
    " FinalSesion = CASE WHEN COALESCE(CierreExplicito, 0) = 0 THEN @ahora ELSE FinalSesion END,"
    " CierreExplicito = CASE WHEN COALESCE(CierreExplicito, 0) = 0 THEN 1 ELSE CierreExplicito END"
    " OUTPUT COALESCE(deleted.CierreExplicito, 0) INTO @previa (Cerrada);"
    " SELECT CAST(CASE WHEN EXISTS (SELECT 1 FROM @previa WHERE Cerrada = 0) THEN 1 ELSE 0 END AS BIT);"
)

# Energía por llave (v10): la fila la crea el flujo ConsultarAccesoPortal al hacer clic en la card, con la llave
# en Token. Estos UPDATE nunca insertan.
_SQL_LATIDO_ENERGIA_LLAVE = (
    "UPDATE core.HistorialAccesos SET FinalSesion = SYSUTCDATETIME()"
    " WHERE Token = ? AND Portal = N'Energía' AND Resultado = N'OK'"
    " AND Fecha >= DATEADD(HOUR, -12, SYSUTCDATETIME())"
    " AND COALESCE(CierreExplicito, 0) = 0"
    " AND (FinalSesion IS NULL OR FinalSesion < DATEADD(SECOND, -60, SYSUTCDATETIME()))"
)

# Cierre por llave: sin la regla de 60 s.
_SQL_CIERRE_ENERGIA_LLAVE = (
    "UPDATE core.HistorialAccesos SET FinalSesion = SYSUTCDATETIME(), CierreExplicito = 1"
    " WHERE Token = ? AND Portal = N'Energía' AND Resultado = N'OK'"
    " AND Fecha >= DATEADD(HOUR, -12, SYSUTCDATETIME())"
    " AND COALESCE(CierreExplicito, 0) = 0"
)


def latido_mirastock(token: str) -> bool:
    """Marca FinalSesion de la llave de MiraStock (aunque ya pasó su ExpiraEn). True si actualizó una fila."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(_SQL_LATIDO_MIRASTOCK, token)
        return cur.rowcount > 0


def cierre_mirastock(token: str) -> bool:
    """Cierra la sesión de MiraStock y anula la llave. True si cerró una sesión abierta."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(_SQL_CIERRE_MIRASTOCK, token)
        return cur.rowcount > 0


def latido_energia(correo: str) -> bool:
    """Extiende la última sesión OK de Energía (ventana de 30 min) o inserta una nueva. True si insertó."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(_SQL_LATIDO_ENERGIA, correo)
        return bool(cur.fetchone()[0])


def cierre_energia(correo: str) -> bool:
    """Cierra la última sesión OK de Energía si está abierta (ventana de 30 min). True si cerró una."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(_SQL_CIERRE_ENERGIA, correo)
        return bool(cur.fetchone()[0])


def latido_energia_llave(llave: str) -> bool:
    """Marca FinalSesion de la fila de Energía con esa llave (de las últimas 12 h). True si actualizó una fila."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(_SQL_LATIDO_ENERGIA_LLAVE, llave)
        return cur.rowcount > 0


def cierre_energia_llave(llave: str) -> bool:
    """Cierra la sesión de Energía con esa llave si está abierta. True si cerró una."""
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(_SQL_CIERRE_ENERGIA_LLAVE, llave)
        return cur.rowcount > 0


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
            "SELECT Fecha, ISNULL(Usuario, '') AS Usuario, Correo, Portal, Resultado,"
            " FinalSesion, TiempoSesionSeg, ISNULL(EnCurso, 0) AS EnCurso,"
            " ISNULL(CierreExplicito, 0) AS CierreExplicito"
            f" FROM core.vHistorialAccesos{where}"
            " ORDER BY Fecha DESC, Correo"
            " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            *params, (pagina - 1) * tamano, tamano,
        )
        filas = [
            {
                "Fecha": r[0], "Usuario": (r[1] or "").strip(), "Correo": r[2], "Portal": r[3], "Resultado": r[4],
                "FinalSesion": r[5], "TiempoSesionSeg": r[6], "EnCurso": bool(r[7]),
                "CierreExplicito": bool(r[8]),
            }
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
            " ISNULL(SUM(CASE WHEN Resultado = 'Denegado' THEN 1 ELSE 0 END), 0),"
            # AVG y SUM ignoran los NULL: solo cuentan las filas con latidos.
            " AVG(CAST(TiempoSesionSeg AS BIGINT)),"
            " ISNULL(SUM(CASE WHEN Portal = N'Energía' THEN CAST(TiempoSesionSeg AS BIGINT) END), 0),"
            " ISNULL(SUM(CASE WHEN Portal = 'MiraStock' THEN CAST(TiempoSesionSeg AS BIGINT) END), 0),"
            " ISNULL(SUM(CASE WHEN EnCurso = 1 THEN 1 ELSE 0 END), 0),"
            " ISNULL(SUM(CASE WHEN CierreExplicito = 1 THEN 1 ELSE 0 END), 0)"
            f" FROM core.vHistorialAccesos{where}",
            *params,
        )
        (total, unicos, energia, mirastock, denegados,
         promedio, tiempo_energia, tiempo_mirastock, en_curso, cerradas_boton) = cur.fetchone()
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
        "tiempoPromedioSeg": int(promedio) if promedio is not None else None,
        "tiempoTotalSeg": {"Energía": int(tiempo_energia), "MiraStock": int(tiempo_mirastock)},
        "enCurso": en_curso,
        "cerradasBoton": cerradas_boton,
        "porDia": por_dia,
    }


def _texto_dia(valor: Any) -> str:
    # El driver devuelve date (o str con controladores antiguos).
    return valor.isoformat() if isinstance(valor, date) else str(valor)[:10]


# ---------------------------------------------------------------------------
# Estadísticas (solo lectura sobre core.vHistorialAccesos; una sesión = una fila con Resultado = 'OK')
# ---------------------------------------------------------------------------

# Sesiones, segundos totales, promedio (AVG ignora los NULL: solo sesiones medidas), sesiones medidas y última.
_AGREGADOS_SESIONES = (
    "COUNT(*), SUM(CAST(TiempoSesionSeg AS BIGINT)), AVG(CAST(TiempoSesionSeg AS BIGINT)),"
    " COUNT(TiempoSesionSeg), MAX(Fecha)"
)


def _where_sesiones(portal: str | None, desde: datetime | None, hasta: datetime | None) -> tuple[str, list[Any]]:
    return _where_historial(FiltrosHistorial(portal=portal, resultado="OK", desde=desde, hasta=hasta))


def _agregados(sesiones: int, segundos: Any, promedio: Any, medidas: int, ultima: Any) -> dict[str, Any]:
    return {
        "sesiones": sesiones,
        "segundosTotales": int(segundos) if segundos is not None else None,
        "promedioSeg": int(promedio) if promedio is not None else None,
        "sesionesMedidas": medidas,
        "ultimaConexion": ultima,
    }


def _sin_sesiones() -> dict[str, Any]:
    return _agregados(0, None, None, 0, None)


def estadisticas_portales(desde: datetime | None, hasta: datetime | None) -> dict[str, Any]:
    """Una entrada por portal conocido (aunque no tenga sesiones en el rango) y el total general.

    El total sale de GROUPING SETS: cuenta los usuarios únicos sin repetirlos entre portales.
    """
    where, params = _where_sesiones(None, desde, hasta)
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT Portal FROM core.vHistorialAccesos WHERE Portal IS NOT NULL")
        conocidos = [r[0] for r in cur.fetchall()]
        cur.execute(
            f"SELECT Portal, GROUPING(Portal), COUNT(DISTINCT Correo), {_AGREGADOS_SESIONES}"
            f" FROM core.vHistorialAccesos{where} AND Portal IS NOT NULL"
            " GROUP BY GROUPING SETS ((Portal), ())",
            *params,
        )
        filas = cur.fetchall()
    por_portal: dict[str, dict[str, Any]] = {}
    total = {"usuariosUnicos": 0, **_sin_sesiones()}
    for portal, es_total, unicos, *resto in filas:
        datos = {"usuariosUnicos": unicos, **_agregados(*resto)}
        if es_total:
            total = datos
        else:
            por_portal[portal] = datos
    nombres = sorted(set(conocidos) | set(por_portal), key=str.casefold)
    return {
        "portales": [
            {"portal": p, **por_portal.get(p, {"usuariosUnicos": 0, **_sin_sesiones()})} for p in nombres
        ],
        "total": total,
    }


def estadisticas_usuarios(
    portal: str, desde: datetime | None, hasta: datetime | None, tope: int
) -> tuple[list[dict[str, Any]], bool]:
    """Una fila por usuario del portal, de más a menos horas. Devuelve (filas, truncado)."""
    where, params = _where_sesiones(portal, desde, hasta)
    with _conexion() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT TOP (?) Correo, MAX(ISNULL(Usuario, '')), {_AGREGADOS_SESIONES}"
            f" FROM core.vHistorialAccesos{where}"
            " GROUP BY Correo"
            " ORDER BY ISNULL(SUM(CAST(TiempoSesionSeg AS BIGINT)), 0) DESC, COUNT(*) DESC, Correo",
            tope + 1, *params,
        )
        filas = [
            {"usuario": (r[1] or "").strip(), "correo": r[0], **_agregados(*r[2:])}
            for r in cur.fetchall()
        ]
    return filas[:tope], len(filas) > tope
