"""v19: «Consulta de base de datos», de solo lectura, sobre una lista cerrada de 20 tablas de `core`.

Usa las mismas credenciales que el resto de la app (app.db._cadena_conexion), en una conexión aparte con
autocommit (solo hay SELECT, nunca abre transacciones) y un tiempo máximo de 20 s por consulta.

El SQL se arma una sola vez, al importar el módulo, con los nombres de este catálogo. Lo único que llega del
usuario es la clave de la tabla (se busca en el catálogo) y el texto a buscar, que siempre va como parámetro `?`.

Columnas que nunca se muestran (ni se piden a la base): ContrasenaHash y ContrasenaSal de AdministradoresPortal,
y Token de HistorialAccesos, SesionesAgente y Descargas.

Todas las fechas se tratan como UTC (en Azure SQL getdate() y sysdatetime() también devuelven UTC).
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import pyodbc

from app.db import _cadena_conexion, _escapar_like

TOPE_FILAS = 500
LARGO_TEXTO = 300            # los textos largos se cortan en SQL a 300 caracteres + «…»
MAX_LARGO_BUSQUEDA = 100
TIEMPO_MAXIMO_S = 20         # tiempo máximo de cada consulta

# Tipos de columna (lo que recibe el frontend en `columnas[].tipo`).
TEXTO = "texto"
TEXTO_LARGO = "textoLargo"   # puede pasar de 300 caracteres: se corta en SQL
ENTERO = "entero"
DECIMAL = "decimal"
BIT = "bit"
FECHA_HORA = "fechaHora"
FECHA = "fecha"
GUID = "guid"


@dataclass(frozen=True)
class Tabla:
    nombre: str                          # sin esquema; también es la clave que usa la API
    columnas: tuple[tuple[str, str], ...]
    orden: str                           # fragmento fijo de ORDER BY
    busqueda: tuple[str, ...] = ()       # columnas del buscador («contiene»)

    @property
    def nombre_completo(self) -> str:
        return f"core.{self.nombre}"


def _cols(texto: str) -> tuple[tuple[str, str], ...]:
    """'Id:entero Nombre:texto' → (('Id', 'entero'), ('Nombre', 'texto'))."""
    return tuple(tuple(par.split(":")) for par in texto.split())  # type: ignore[misc]


_TABLAS = (
    Tabla(
        "AdministradoresPortal",
        _cols("Id:entero Nombre:texto Correo:texto AlgoritmoHash:texto DebeCambiarContrasena:bit Activo:bit "
              "IntentosFallidos:entero BloqueadoHasta:fechaHora UltimoAcceso:fechaHora "
              "FechaCambioContrasena:fechaHora FechaAlta:fechaHora"),
        "[Id] DESC", ("Correo",),
    ),
    Tabla(
        "ColaRecepcion",
        _cols("IdCola:entero TicketJira:texto PayloadJSON:textoLargo FechaRecepcion:fechaHora Estado:texto "
              "MensajeError:textoLargo"),
        "[IdCola] DESC", ("TicketJira",),
    ),
    Tabla(
        "ColaTicketsControl",
        _cols("Id:entero Num_Ticket_JIRA:texto Url_SharePoint:textoLargo Estado:texto Fecha_Creacion:fechaHora "
              "Fecha_Actualizacion:fechaHora Codigo_RQ:texto RQ_Oracle:texto Num_Pedido:texto "
              "Respuesta_Oracle:textoLargo Detalle_Respuesta:textoLargo Respuesta_Correo:texto "
              "Detalle_Respuesta_Correo:textoLargo Fecha_Notificacion_Correo:fechaHora"),
        "[Id] DESC", ("Num_Ticket_JIRA",),
    ),
    Tabla(
        "Contrapropuesta",
        _cols("IdContrapropuesta:entero TicketJira:texto Gerencia:texto ProyectoDestino:texto Item:entero SKU:texto "
              "Descripcion:texto CantSolicitada:decimal Contratista:texto Direccion:texto CantReservada:decimal "
              "SaldoFaltante:decimal MensajeAlerta:textoLargo Solicitante:texto UrlSharepoint:textoLargo"),
        "[IdContrapropuesta] DESC", ("SKU", "Solicitante", "TicketJira"),
    ),
    Tabla(
        "ContrataDireccion",
        _cols("Contrata:texto Subinventario:texto DireccionDestino:textoLargo"),
        "[Contrata], [Subinventario]",
    ),
    Tabla(
        "Descargas",
        _cols("RutaArchivo:textoLargo NombreArchivo:texto CreadoEn:fechaHora ExpiraEn:fechaHora Descargas:entero"),
        "[CreadoEn] DESC, [NombreArchivo]",
    ),
    Tabla(
        "HistorialAccesos",
        _cols("Id:entero Correo:textoLargo Portal:texto Resultado:texto Fecha:fechaHora FinalSesion:fechaHora "
              "CierreExplicito:bit"),
        "[Fecha] DESC, [Id] DESC", ("Correo",),
    ),
    Tabla(
        "Incidencias",
        _cols("IdIncidencia:entero TicketJira:texto FechaIncidencia:fechaHora TipoError:texto MensajeError:textoLargo "
              "PayloadOriginal:textoLargo EstadoResolucion:texto FechaResolucion:fechaHora UsuarioResolucion:texto "
              "CantidadReintentos:entero"),
        "[IdIncidencia] DESC", ("TicketJira",),
    ),
    Tabla(
        "LogConsulta",
        _cols("LogConsultaId:entero CorreoUsuario:textoLargo GerenciaUsuario:texto Operacion:texto "
              "Parametros:textoLargo CantidadResultados:entero FueExitosa:bit MensajeError:textoLargo "
              "FechaConsulta:fechaHora"),
        "[LogConsultaId] DESC", ("CorreoUsuario",),
    ),
    Tabla(
        "Observados",
        _cols("IdObservado:entero TicketJira:texto FechaRegistro:fechaHora Detalle:textoLargo LogSistema:textoLargo "
              "PayloadOriginal:textoLargo EstadoNotificacion:texto"),
        "[IdObservado] DESC", ("TicketJira",),
    ),
    Tabla(
        "Propuesta",
        _cols("IdPropuesta:entero TicketJira:texto RqItem:entero SKU:texto Descripcion:texto TipoLinea:texto "
              "Cantidad:decimal Solicitante:texto NumProyecto:texto NomProyecto:texto Contratista:texto "
              "Subinventario:texto Direccion:texto Tipo_Articulo:texto CodigoProyecto:texto Proyecto:texto "
              "UrlSharepoint:textoLargo Tarea:texto SubinventarioOrigen:texto"),
        "[IdPropuesta] DESC", ("SKU", "Solicitante", "TicketJira"),
    ),
    Tabla(
        "Registros_SkuComprometido",
        _cols("IdRegistro:entero Accion:texto Fecha_Registro:fechaHora ComprometidoId:entero SKU:texto "
              "CodigoProyecto:texto SerieLote:texto CantidadComprometida:decimal Estado:texto FechaInicio:fechaHora "
              "FechaFin:fechaHora Referencia:texto Gerencia:texto Etapa_Proceso:texto CodigoProyectoOrigen:texto "
              "TipoSKU:texto Tarea:texto SubinventarioOrigen:texto GerenciaOrigen:texto AlmacenOrigen:texto"),
        "[IdRegistro] DESC", ("SKU", "Referencia"),
    ),
    Tabla(
        "ReglaClasificacion",
        _cols("Clasificacion:texto EsAsignable:bit Motivo:textoLargo FechaActualizacion:fechaHora"),
        "[FechaActualizacion] DESC, [Clasificacion]",
    ),
    Tabla(
        "ReservasPedido",
        _cols("IdReserva:entero SKU:texto Gerencia:texto Usuario:texto CantidadSolicitada:entero "
              "CantidadReservada:entero Estado:texto Fecha:fechaHora"),
        "[IdReserva] DESC", ("SKU", "Usuario"),
    ),
    Tabla(
        "SesionesAgente",
        _cols("Correo:texto CreadoEn:fechaHora ExpiraEn:fechaHora FinalSesion:fechaHora CierreExplicito:bit"),
        "[CreadoEn] DESC, [Correo]", ("Correo",),
    ),
    Tabla(
        "SKUComprometido",
        _cols("ComprometidoId:entero SKU:texto CodigoProyecto:texto SerieLote:texto CantidadComprometida:decimal "
              "Estado:texto FechaInicio:fechaHora FechaFin:fechaHora Referencia:texto Gerencia:texto "
              "Etapa_Proceso:texto CodigoProyectoOrigen:texto TipoSKU:texto Tarea:texto SubinventarioOrigen:texto "
              "GerenciaOrigen:texto AlmacenOrigen:texto"),
        "[ComprometidoId] DESC", ("SKU", "Referencia"),
    ),
    Tabla(
        "SolicitudDetalle",
        _cols("IdDetalle:entero IdSolicitud:entero SKU:texto Descripcion:texto CantSolicitada:decimal "
              "Contratista:texto Direccion:texto Solicitante:texto"),
        "[IdDetalle] DESC", ("SKU", "Solicitante"),
    ),
    Tabla(
        "Solicitudes",
        _cols("IdSolicitud:entero TicketJira:texto Gerencia:texto ProyectoDestino:texto Solicitante:texto "
              "FechaRecepcion:fechaHora EstadoTicket:texto"),
        "[IdSolicitud] DESC", ("Solicitante", "TicketJira"),
    ),
    Tabla(
        "StockLurinERI",
        _cols("Llave:texto Subinventario:texto DescripcionSubinventario:texto Proyecto:texto CodigoProyecto:texto "
              "PO:texto SKU:texto Descripcion:textoLargo SerieLote:texto Cantidad:decimal Tarea:texto "
              "PrecioUnitarioSoles:decimal PrecioTotalSoles:decimal TipoSKU:texto TipoEquipo:texto "
              "FechaPrimerRegistroOracle:fecha Antiguamiento:texto Clasificacion:texto Gerencia:texto "
              "Jefatura:texto CantidadLurinERI:decimal VP:texto FechaCarga:fechaHora Almacen:texto"),
        "[FechaCarga] DESC, [Llave]", ("SKU",),
    ),
    Tabla(
        "UsuariosEntel",
        _cols("Id:entero Correo:texto Nombre:texto Apellido:texto Portal1:bit Portal2:bit Activo:bit "
              "FechaAlta:fechaHora Gerencia:texto Portal3:bit InvitacionEnviada:bit Cliente:texto"),
        "[Id] DESC", ("Correo",),
    ),
)

TABLAS: dict[str, Tabla] = {t.nombre: t for t in _TABLAS}


# ---------------------------------------------------------------------------
# SQL fijo por tabla (armado al importar, solo con el catálogo)
# ---------------------------------------------------------------------------

def _expresion(columna: str, tipo: str) -> str:
    if tipo == TEXTO_LARGO:
        return (
            f"CASE WHEN LEN([{columna}]) > {LARGO_TEXTO} THEN LEFT([{columna}], {LARGO_TEXTO}) + N'…' "
            f"ELSE [{columna}] END AS [{columna}]"
        )
    return f"[{columna}]"


def _where(tabla: Tabla) -> str:
    return "WHERE (" + " OR ".join(f"[{c}] LIKE ? ESCAPE '\\'" for c in tabla.busqueda) + ")"


@dataclass(frozen=True)
class _Sql:
    contar: str
    contar_busqueda: str | None
    listar: str
    listar_busqueda: str | None


def _armar_sql(tabla: Tabla) -> _Sql:
    origen = f"FROM [core].[{tabla.nombre}]"
    seleccion = ", ".join(_expresion(c, t) for c, t in tabla.columnas)
    listar = f"SELECT TOP ({TOPE_FILAS}) {seleccion} {origen} {{where}}ORDER BY {tabla.orden}"
    contar = f"SELECT COUNT_BIG(*) {origen}"
    if not tabla.busqueda:
        return _Sql(contar, None, listar.format(where=""), None)
    where = _where(tabla)
    return _Sql(contar, f"{contar} {where}", listar.format(where=""), listar.format(where=where + " "))


SQL: dict[str, _Sql] = {nombre: _armar_sql(t) for nombre, t in TABLAS.items()}


# ---------------------------------------------------------------------------
# Conexión (mismas credenciales que app.db)
# ---------------------------------------------------------------------------

@contextmanager
def _conexion_consulta() -> Iterator[pyodbc.Connection]:
    # autocommit: no abre transacciones (solo hay SELECT). La base tiene RCSI: no bloquea al bot ni a los flujos.
    conn = pyodbc.connect(_cadena_conexion(), autocommit=True, readonly=True)
    try:
        conn.timeout = TIEMPO_MAXIMO_S
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def _iso_utc(valor: datetime) -> str:
    return valor.replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _decimal_texto(valor: Decimal) -> str:
    # Sin ceros de relleno ni notación científica: 12.5000 → «12.5», 100.00 → «100».
    texto = format(valor, "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return "0" if texto in ("", "-0") else texto


def valor_json(tipo: str, valor: Any) -> Any:
    """Convierte un valor de pyodbc a JSON: fechas ISO (UTC con Z), decimales como texto, bits como bool."""
    if valor is None:
        return None
    if tipo == FECHA_HORA and isinstance(valor, datetime):
        return _iso_utc(valor)
    if tipo == FECHA and isinstance(valor, (date, datetime)):
        return (valor.date() if isinstance(valor, datetime) else valor).isoformat()
    if tipo == DECIMAL and isinstance(valor, Decimal):
        return _decimal_texto(valor)
    if tipo == BIT:
        return bool(valor)
    if tipo == ENTERO:
        return int(valor)
    return str(valor)


def consultar(tabla: Tabla, texto: str | None) -> dict[str, Any]:
    """Últimas TOPE_FILAS filas (o hasta TOPE_FILAS coincidencias de `texto`) y los contadores."""
    sql = SQL[tabla.nombre]
    with _conexion_consulta() as conn:
        cur = conn.cursor()
        cur.execute(sql.contar)
        total_tabla = int(cur.fetchone()[0])
        if texto:
            patron = "%" + _escapar_like(texto) + "%"
            params = [patron] * len(tabla.busqueda)
            cur.execute(sql.contar_busqueda, *params)
            total = int(cur.fetchone()[0])
            cur.execute(sql.listar_busqueda, *params)
        else:
            total = total_tabla
            cur.execute(sql.listar)
        filas = cur.fetchall()
    tipos = [t for _, t in tabla.columnas]
    return {
        "filas": [[valor_json(t, v) for t, v in zip(tipos, fila)] for fila in filas],
        "total": total,
        "totalTabla": total_tabla,
    }
