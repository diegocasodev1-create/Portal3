"""v19: «Consulta de base de datos» de solo lectura (app/consulta_bd.py, /consulta-bd y /api/consulta-bd/*)."""

import logging
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyodbc
import pytest

from app import consulta_bd, db
from tests.conftest import poner_sesion

RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "app" / "static"

LISTA_CERRADA = {
    "AdministradoresPortal", "ColaRecepcion", "ColaTicketsControl", "Contrapropuesta", "ContrataDireccion",
    "Descargas", "HistorialAccesos", "Incidencias", "LogConsulta", "Observados", "Propuesta",
    "Registros_SkuComprometido", "ReglaClasificacion", "ReservasPedido", "SesionesAgente", "SKUComprometido",
    "SolicitudDetalle", "Solicitudes", "StockLurinERI", "UsuariosEntel",
}
OCULTAS = {
    "AdministradoresPortal": {"ContrasenaHash", "ContrasenaSal"},
    "HistorialAccesos": {"Token"},
    "SesionesAgente": {"Token"},
    "Descargas": {"Token"},
}
BUSQUEDA = {
    "AdministradoresPortal": ("Correo",),
    "ColaRecepcion": ("TicketJira",),
    "ColaTicketsControl": ("Num_Ticket_JIRA",),
    "Contrapropuesta": ("SKU", "Solicitante", "TicketJira"),
    "ContrataDireccion": (),
    "Descargas": (),
    "HistorialAccesos": ("Correo",),
    "Incidencias": ("TicketJira",),
    "LogConsulta": ("CorreoUsuario",),
    "Observados": ("TicketJira",),
    "Propuesta": ("SKU", "Solicitante", "TicketJira"),
    "Registros_SkuComprometido": ("SKU", "Referencia"),
    "ReglaClasificacion": (),
    "ReservasPedido": ("SKU", "Usuario"),
    "SesionesAgente": ("Correo",),
    "SKUComprometido": ("SKU", "Referencia"),
    "SolicitudDetalle": ("SKU", "Solicitante"),
    "Solicitudes": ("Solicitante", "TicketJira"),
    "StockLurinERI": ("SKU",),
    "UsuariosEntel": ("Correo",),
}
ORDEN = {
    "ContrataDireccion": "[Contrata], [Subinventario]",
    "Descargas": "[CreadoEn] DESC, [NombreArchivo]",
    "HistorialAccesos": "[Fecha] DESC, [Id] DESC",
    "ReglaClasificacion": "[FechaActualizacion] DESC, [Clasificacion]",
    "SesionesAgente": "[CreadoEn] DESC, [Correo]",
    "StockLurinERI": "[FechaCarga] DESC, [Llave]",
    "UsuariosEntel": "[Id] DESC",
    "Propuesta": "[IdPropuesta] DESC",
}


# ---------------------------------------------------------------------------
# Conexión de lectura simulada
# ---------------------------------------------------------------------------

class CursorBD:
    def __init__(self, conteos=(0, 0), filas=()):
        self.ejecutados = []
        self.conteos = list(conteos)
        self.filas = list(filas)

    def execute(self, sql, *params):
        self.ejecutados.append((sql, params))

    def fetchone(self):
        return (self.conteos.pop(0),)

    def fetchall(self):
        return self.filas


@pytest.fixture
def lectura(monkeypatch):
    estado = {"cursor": CursorBD(), "conexiones": 0, "error": None}

    @contextmanager
    def conexion():
        estado["conexiones"] += 1
        if estado["error"]:
            raise estado["error"]

        class Conn:
            def cursor(self):
                return estado["cursor"]

        yield Conn()

    monkeypatch.setattr(consulta_bd, "_conexion_consulta", conexion)
    return estado


def filas(cliente, **params):
    return cliente.get("/api/consulta-bd/filas", params=params)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def test_lista_cerrada_de_20_tablas():
    assert set(consulta_bd.TABLAS) == LISTA_CERRADA
    assert len(consulta_bd.TABLAS) == 20


@pytest.mark.parametrize("nombre", sorted(LISTA_CERRADA))
def test_columnas_ocultas_nunca_se_piden(nombre):
    tabla = consulta_bd.TABLAS[nombre]
    columnas = {c for c, _ in tabla.columnas}
    assert not columnas & OCULTAS.get(nombre, set())
    sql = consulta_bd.SQL[nombre]
    for texto in (sql.contar, sql.contar_busqueda or "", sql.listar, sql.listar_busqueda or ""):
        for oculta in OCULTAS.get(nombre, set()):
            assert f"[{oculta}]" not in texto and oculta not in re.findall(r"\w+", texto)


@pytest.mark.parametrize("nombre", sorted(LISTA_CERRADA))
def test_busqueda_y_orden_usan_columnas_del_catalogo(nombre):
    tabla = consulta_bd.TABLAS[nombre]
    columnas = {c for c, _ in tabla.columnas}
    assert tabla.busqueda == BUSQUEDA[nombre]
    assert set(tabla.busqueda) <= columnas
    assert all(dict(tabla.columnas)[c] in (consulta_bd.TEXTO, consulta_bd.TEXTO_LARGO) for c in tabla.busqueda)
    assert set(re.findall(r"\[(\w+)\]", tabla.orden)) <= columnas
    if nombre in ORDEN:
        assert tabla.orden == ORDEN[nombre]
    tipos = {t for _, t in tabla.columnas}
    assert tipos <= {consulta_bd.TEXTO, consulta_bd.TEXTO_LARGO, consulta_bd.ENTERO, consulta_bd.DECIMAL,
                     consulta_bd.BIT, consulta_bd.FECHA_HORA, consulta_bd.FECHA, consulta_bd.GUID}


def test_nombres_seguros_para_sql():
    for tabla in consulta_bd.TABLAS.values():
        assert re.fullmatch(r"\w+", tabla.nombre)
        assert all(re.fullmatch(r"\w+", c) for c, _ in tabla.columnas)


# ---------------------------------------------------------------------------
# SQL armado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", sorted(LISTA_CERRADA))
def test_sql_fijo_por_tabla(nombre):
    tabla = consulta_bd.TABLAS[nombre]
    sql = consulta_bd.SQL[nombre]
    origen = f"FROM [core].[{nombre}]"
    assert sql.contar == f"SELECT COUNT_BIG(*) {origen}"
    assert sql.listar.startswith("SELECT TOP (500) ")
    assert sql.listar.endswith(f"{origen} ORDER BY {tabla.orden}")
    assert "?" not in sql.listar
    for columna, tipo in tabla.columnas:
        if tipo == consulta_bd.TEXTO_LARGO:
            assert (f"CASE WHEN LEN([{columna}]) > 300 THEN LEFT([{columna}], 300) + N'…' "
                    f"ELSE [{columna}] END AS [{columna}]") in sql.listar
        else:
            assert f"[{columna}]" in sql.listar
    if not tabla.busqueda:
        assert sql.contar_busqueda is None and sql.listar_busqueda is None
        return
    where = "WHERE (" + " OR ".join(f"[{c}] LIKE ? ESCAPE '\\'" for c in tabla.busqueda) + ")"
    assert sql.contar_busqueda == f"{sql.contar} {where}"
    assert sql.listar_busqueda.endswith(f"{origen} {where} ORDER BY {tabla.orden}")
    assert sql.listar_busqueda.count("?") == sql.contar_busqueda.count("?") == len(tabla.busqueda)


def test_consultar_sin_busqueda(lectura):
    lectura["cursor"] = cur = CursorBD(conteos=[45008], filas=[("A",) * 24])
    datos = consulta_bd.consultar(consulta_bd.TABLAS["StockLurinERI"], None)
    sql = consulta_bd.SQL["StockLurinERI"]
    assert cur.ejecutados == [(sql.contar, ()), (sql.listar, ())]
    assert datos["total"] == datos["totalTabla"] == 45008
    assert len(datos["filas"]) == 1


def test_consultar_con_busqueda_escapa_el_like_y_repite_el_parametro(lectura):
    lectura["cursor"] = cur = CursorBD(conteos=[375, 2], filas=[])
    datos = consulta_bd.consultar(consulta_bd.TABLAS["Propuesta"], "ZQ%_[x]\\Ab")
    sql = consulta_bd.SQL["Propuesta"]
    patron = "%ZQ\\%\\_\\[x]\\\\Ab%"
    assert cur.ejecutados == [
        (sql.contar, ()),
        (sql.contar_busqueda, (patron,) * 3),
        (sql.listar_busqueda, (patron,) * 3),
    ]
    # El texto nunca entra al SQL: solo va como parámetro (y sin pasarlo a minúsculas: la collation es CI).
    assert all("ZQ" not in s for s, _ in cur.ejecutados)
    assert datos == {"filas": [], "total": 2, "totalTabla": 375}


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tipo, valor, esperado", [
    ("fechaHora", datetime(2026, 11, 5, 13, 46, 7, 123456), "2026-11-05T13:46:07Z"),
    ("fecha", date(2025, 1, 31), "2025-01-31"),
    ("fecha", datetime(2025, 1, 31, 0, 0), "2025-01-31"),
    ("decimal", Decimal("12.5000"), "12.5"),
    ("decimal", Decimal("100.00"), "100"),
    ("decimal", Decimal("0.0000"), "0"),
    ("decimal", Decimal("-3.250000"), "-3.25"),
    ("decimal", Decimal("123456789012.345678"), "123456789012.345678"),
    ("decimal", Decimal("1E+2"), "100"),
    ("bit", True, True),
    ("bit", 0, False),
    ("entero", 9007199254740993, 9007199254740993),
    ("guid", "6F9619FF-8B86-D011-B42D-00C04FC964FF", "6F9619FF-8B86-D011-B42D-00C04FC964FF"),
    ("texto", "<script>alert(1)</script>", "<script>alert(1)</script>"),
    ("textoLargo", "x" * 300 + "…", "x" * 300 + "…"),
    ("texto", None, None),
    ("fechaHora", None, None),
    ("bit", None, None),
])
def test_valor_json(tipo, valor, esperado):
    assert consulta_bd.valor_json(tipo, valor) == esperado


# ---------------------------------------------------------------------------
# Conexión (mismas credenciales que la app)
# ---------------------------------------------------------------------------

def test_conexion_con_las_credenciales_de_la_app_autocommit_y_tiempo_maximo(monkeypatch):
    llamadas = []

    class Conn:
        timeout = 0
        cerrada = False

        def close(self):
            self.cerrada = True

    conn = Conn()

    def connect(cadena, **kw):
        llamadas.append((cadena, kw))
        return conn

    monkeypatch.setattr(pyodbc, "connect", connect)
    with consulta_bd._conexion_consulta() as c:
        assert c.timeout == 20
    assert llamadas == [(db._cadena_conexion(), {"autocommit": True, "readonly": True})]
    assert "UID={usuario-de-prueba};" in llamadas[0][0]
    assert conn.cerrada


def test_conexion_se_cierra_si_la_consulta_falla(monkeypatch):
    class Conn:
        cerrada = False

        def close(self):
            self.cerrada = True

    conn = Conn()
    monkeypatch.setattr(pyodbc, "connect", lambda cadena, **kw: conn)
    with pytest.raises(pyodbc.Error):
        with consulta_bd._conexion_consulta():
            raise pyodbc.Error("08S01", "error de prueba")
    assert conn.cerrada


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_tablas_sin_sesion_401(cliente):
    assert cliente.get("/api/consulta-bd/tablas").status_code == 401
    assert filas(cliente, tabla="UsuariosEntel").status_code == 401


def test_tablas_lista_cerrada(cliente_admin, lectura):
    datos = cliente_admin.get("/api/consulta-bd/tablas").json()
    assert set(datos) == {"tope", "tablas"} and datos["tope"] == 500
    assert {t["clave"] for t in datos["tablas"]} == LISTA_CERRADA
    porclave = {t["clave"]: t for t in datos["tablas"]}
    assert porclave["StockLurinERI"] == {"clave": "StockLurinERI", "nombre": "core.StockLurinERI", "camposBusqueda": ["SKU"]}
    assert porclave["ContrataDireccion"]["camposBusqueda"] == []
    assert lectura["conexiones"] == 0  # sale del catálogo, no de la base


def test_admin_que_debe_cambiar_contrasena_403(cliente, bd, lectura):
    aid = bd.agregar_admin("nuevo@miragroup.cl", "Nuevo", "Admin@123456", algoritmo="SHA2_512", debe_cambiar=True)
    poner_sesion(cliente, bd.admins[aid])
    resp = filas(cliente, tabla="UsuariosEntel")
    assert resp.status_code == 403 and resp.json()["cambioRequerido"] is True
    assert cliente.get("/api/consulta-bd/tablas").status_code == 403
    assert lectura["conexiones"] == 0


def test_filas_respuesta(cliente_admin, lectura):
    lectura["cursor"] = CursorBD(conteos=[3], filas=[
        (7, "Ana", "ana@ejemplo.com", "PBKDF2_SHA256", 0, 1, 0, None, datetime(2026, 11, 5, 13, 0), None,
         datetime(2026, 10, 30, 22, 0, 5)),
    ])
    resp = filas(cliente_admin, tabla="AdministradoresPortal")
    assert resp.status_code == 200
    datos = resp.json()
    assert datos["tabla"] == "core.AdministradoresPortal" and datos["clave"] == "AdministradoresPortal"
    assert datos["columnas"][0] == {"nombre": "Id", "tipo": "entero"}
    assert [c["nombre"] for c in datos["columnas"]] == [c for c, _ in consulta_bd.TABLAS["AdministradoresPortal"].columnas]
    assert datos["camposBusqueda"] == ["Correo"]
    assert datos["busqueda"] is None
    assert (datos["tope"], datos["mostrando"], datos["total"], datos["totalTabla"]) == (500, 1, 3, 3)
    assert datos["filas"] == [[7, "Ana", "ana@ejemplo.com", "PBKDF2_SHA256", False, True, 0, None,
                               "2026-11-05T13:00:00Z", None, "2026-10-30T22:00:05Z"]]
    assert "Contrasena" not in resp.text.replace("DebeCambiarContrasena", "").replace("FechaCambioContrasena", "")


def test_filas_con_busqueda_recortada(cliente_admin, lectura):
    lectura["cursor"] = cur = CursorBD(conteos=[45008, 1], filas=[])
    datos = filas(cliente_admin, tabla="StockLurinERI", q="  ABC-123  ").json()
    assert datos["busqueda"] == "ABC-123"
    assert (datos["mostrando"], datos["total"], datos["totalTabla"]) == (0, 1, 45008)
    assert cur.ejecutados[1][1] == ("%ABC-123%",)


def test_busqueda_vacia_es_sin_busqueda(cliente_admin, lectura):
    lectura["cursor"] = cur = CursorBD(conteos=[63], filas=[])
    datos = filas(cliente_admin, tabla="ContrataDireccion", q="   ").json()
    assert datos["busqueda"] is None
    assert len(cur.ejecutados) == 2


@pytest.mark.parametrize("params, campo, mensaje", [
    ({}, "tabla", "Elige una tabla."),
    ({"tabla": "  "}, "tabla", "Elige una tabla."),
    ({"tabla": "Inexistente"}, "tabla", "La tabla no está disponible para consulta."),
    ({"tabla": "usuariosentel"}, "tabla", "La tabla no está disponible para consulta."),
    ({"tabla": "core.UsuariosEntel"}, "tabla", "La tabla no está disponible para consulta."),
    ({"tabla": "UsuariosEntel]; DROP TABLE core.UsuariosEntel;--"}, "tabla", "La tabla no está disponible para consulta."),
    ({"tabla": "vHistorialAccesos"}, "tabla", "La tabla no está disponible para consulta."),
    ({"tabla": "UsuariosEntel", "q": "x" * 101}, "q", "La búsqueda admite hasta 100 caracteres."),
    ({"tabla": "ContrataDireccion", "q": "algo"}, "q", "Esta tabla no tiene columnas para buscar."),
    ({"tabla": "Descargas", "q": "algo"}, "q", "Esta tabla no tiene columnas para buscar."),
])
def test_filas_422(cliente_admin, lectura, params, campo, mensaje):
    resp = filas(cliente_admin, **params)
    assert resp.status_code == 422
    assert resp.json()["errores"][campo] == mensaje
    assert lectura["conexiones"] == 0


def test_busqueda_de_100_caracteres_se_acepta(cliente_admin, lectura):
    lectura["cursor"] = CursorBD(conteos=[1, 0], filas=[])
    assert filas(cliente_admin, tabla="UsuariosEntel", q="x" * 100).status_code == 200


def test_tabla_y_busqueda_invalidas_juntas(cliente_admin, lectura):
    errores = filas(cliente_admin, tabla="Nada", q="x" * 101).json()["errores"]
    assert set(errores) == {"tabla", "q"}


def test_filas_error_de_base_503(cliente_admin, lectura):
    lectura["error"] = pyodbc.Error("42000", "[42000] The SELECT permission was denied (230)")
    resp = filas(cliente_admin, tabla="UsuariosEntel")
    assert resp.status_code == 503
    assert resp.json()["detail"].startswith("No se pudo conectar con la base de datos")


def test_el_texto_buscado_no_se_registra(cliente_admin, lectura, caplog):
    lectura["cursor"] = CursorBD(conteos=[53, 1], filas=[])
    with caplog.at_level(logging.DEBUG):
        filas(cliente_admin, tabla="UsuariosEntel", q="secreto-buscado@ejemplo.com")
    assert "secreto-buscado" not in caplog.text
    assert "core.UsuariosEntel" in caplog.text


def test_solo_lectura_sin_metodos_de_escritura(cliente_admin):
    for metodo in ("post", "put", "patch", "delete"):
        resp = getattr(cliente_admin, metodo)("/api/consulta-bd/filas", headers={"X-Requested-With": "mira-admin"})
        assert resp.status_code in (403, 405)


def test_sin_usuario_de_base_aparte():
    # Cambio de decisión en v19: misma conexión que el resto de la app, sin variables ni secret nuevos.
    for archivo in ("config.py", "consulta_bd.py", "main.py"):
        texto = (RAIZ / "app" / archivo).read_text(encoding="utf-8")
        assert "sql_lectura" not in texto and "mira_consulta_lectura" not in texto
    assert not (RAIZ / "sql").exists()


# ---------------------------------------------------------------------------
# Página, card del menú y archivos estáticos
# ---------------------------------------------------------------------------

def test_pagina_sin_sesion_va_al_login(cliente):
    resp = cliente.get("/consulta-bd", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?siguiente=/consulta-bd"


def test_pagina_con_admin(cliente_admin):
    resp = cliente_admin.get("/consulta-bd")
    assert resp.status_code == 200
    texto = resp.text
    assert "<h1>Consulta de base de datos</h1>" in texto
    assert '<script src="/static/comun.js?v=19" defer></script>' in texto
    assert '<script src="/static/consulta-bd.js?v=19" defer></script>' in texto
    assert texto.index("comun.js") < texto.index("consulta-bd.js")
    assert 'href="/static/styles.css?v=19"' in texto
    assert 'href="/">← Inicio</a>' in texto
    assert 'maxlength="100"' in texto and 'placeholder="Contiene…"' in texto
    assert 'id="c-buscador" hidden' in texto
    assert 'style="' not in texto and "<script>" not in texto
    assert resp.headers["content-security-policy"].startswith("default-src 'self'; script-src 'self';")


def test_pagina_admin_desactivado_va_al_login(cliente_admin, bd):
    bd.admins[1]["Activo"] = False
    resp = cliente_admin.get("/consulta-bd", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"].startswith("/login")


def test_cuarta_card_del_menu(cliente_admin):
    inicio = cliente_admin.get("/").text
    assert inicio.count('class="card card-modulo card-menu"') == 4
    card = inicio[inicio.index('href="/consulta-bd"'):]
    card = card[:card.index("</a>")]
    assert '<span class="modulo-titulo">Consulta de base de datos</span>' in card
    assert "Solo lectura." in card
    assert 'Entrar <span class="modulo-flecha">→</span>' in card
    assert 'style="' not in inicio


def test_menu_en_cuadricula_de_2_x_2_y_1_columna_en_celular(cliente):
    css = cliente.get("/static/styles.css").text.replace("\r\n", "\n")
    assert ".modulos {\n  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert "@media (max-width: 600px) {\n  .modulos { grid-template-columns: minmax(0, 1fr); }\n}" in css


def test_css_tabla_con_encabezado_fijo_y_scroll(cliente):
    css = cliente.get("/static/styles.css").text
    assert "overflow: auto; max-height: max(320px, calc(100vh - 300px));" in css
    bloque = css[css.index(".tabla-bd th {"):]
    bloque = bloque[:bloque.index("}")]
    assert "position: sticky; top: 0;" in bloque and "background: #0c1d38;" in bloque


def test_js_servido_y_sin_innerhtml(cliente):
    resp = cliente.get("/static/consulta-bd.js?v=19")
    assert resp.status_code == 200
    js = resp.text
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert prohibido not in js
    assert "/api/consulta-bd/filas?" in js and "/api/consulta-bd/tablas" in js
    assert "sessionStorage" in js and "try {" in js
    # Sin nombres de tabla escritos en el JS: la lista sale de la API.
    assert not any(nombre in js for nombre in LISTA_CERRADA)
