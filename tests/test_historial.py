"""Inicio, /contactos, /historial y la API de solo lectura del historial de accesos."""

from datetime import date, datetime, timedelta, timezone

import pyodbc
import pytest

from app import db, main
from tests.conftest import ADMIN, crear_token

FECHA = datetime(2026, 10, 20, 15, 30, 0)  # UTC sin zona, como la vista


def revocar_admin(bd):
    bd.usuarios[1]["Portal3"] = False


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

PAGINAS = {
    "/": ("Portal de administración", 'href="/historial"'),
    "/contactos": ("Centro Administración de contactos", 'id="tabla-cuerpo"'),
    "/historial": ("Logs control de ingresos", '<script src="/static/historial.js?v=9"'),
}


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_sin_sesion_piden_ingresar(cliente, ruta):
    resp = cliente.get(ruta)
    assert resp.status_code == 200
    assert "Ingresa desde el Portal Corporativo" in resp.text
    assert PAGINAS[ruta][0] not in resp.text


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_con_admin(cliente_admin, ruta):
    resp = cliente_admin.get(ruta)
    assert resp.status_code == 200
    titulo, marca = PAGINAS[ruta]
    assert f"<h1>{titulo}</h1>" in resp.text
    assert marca in resp.text
    assert "{{PORTAL_URL}}" not in resp.text
    assert 'href="https://portal.ejemplo.com"' in resp.text


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_sin_permisos_403(cliente_admin, bd, ruta):
    revocar_admin(bd)
    resp = cliente_admin.get(ruta)
    assert resp.status_code == 403
    assert PAGINAS[ruta][0] not in resp.text


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_bd_no_disponible_503(cliente_admin, monkeypatch, ruta):
    def falla(correo):
        raise pyodbc.Error("08001", "sin conexión")

    monkeypatch.setattr(db, "es_admin", falla)
    resp = cliente_admin.get(ruta)
    assert resp.status_code == 503
    assert "No se pudo verificar tu acceso" in resp.text


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_sin_auth_se_sirven_directo(cliente_sin_auth, ruta):
    resp = cliente_sin_auth.get(ruta)
    assert resp.status_code == 200
    assert f"<h1>{PAGINAS[ruta][0]}</h1>" in resp.text
    assert "Ingresa desde el Portal Corporativo" not in resp.text


def test_inicio_enlaza_los_dos_modulos(cliente_admin):
    texto = cliente_admin.get("/").text
    assert 'href="/historial"' in texto and "Logs control de ingresos" in texto
    assert 'href="/contactos"' in texto and "Centro Administración de contactos" in texto


@pytest.mark.parametrize("ruta", ["/contactos", "/historial"])
def test_paginas_internas_tienen_enlace_inicio(cliente_admin, ruta):
    assert 'href="/">← Inicio</a>' in cliente_admin.get(ruta).text


def test_login_redirige_al_inicio(cliente):
    resp = cliente.post("/auth/portal", data={"token": crear_token()}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_paginas_sin_scripts_ni_estilos_inline(cliente_admin):
    for ruta in PAGINAS:
        texto = cliente_admin.get(ruta).text
        assert "<script>" not in texto and "style=" not in texto and "onclick" not in texto


# ---------------------------------------------------------------------------
# Autorización de la API
# ---------------------------------------------------------------------------

ENDPOINTS = ["/api/historial", "/api/historial/resumen", "/api/historial/csv"]


@pytest.mark.parametrize("ruta", ENDPOINTS)
def test_api_historial_sin_sesion_401(cliente, ruta):
    resp = cliente.get(ruta)
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.parametrize("ruta", ENDPOINTS)
def test_api_historial_401_antes_que_validar(cliente, ruta):
    assert cliente.get(ruta, params={"portal": "otro", "desde": "x"}).status_code == 401


@pytest.mark.parametrize("ruta", ENDPOINTS)
def test_api_historial_sin_permisos_403(cliente_admin, bd, ruta):
    revocar_admin(bd)
    resp = cliente_admin.get(ruta)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "No tienes permisos de administrador."


@pytest.mark.parametrize("ruta", ENDPOINTS)
def test_api_historial_sin_auth_responde(cliente_sin_auth, ruta):
    assert cliente_sin_auth.get(ruta).status_code == 200


def test_api_historial_error_de_bd_503(cliente_admin, monkeypatch):
    def falla(*args):
        raise pyodbc.Error("08001", "sin conexión")

    monkeypatch.setattr(db, "listar_historial", falla)
    resp = cliente_admin.get("/api/historial")
    assert resp.status_code == 503
    assert "base de datos" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Listado: orden, formato, filtros y paginación
# ---------------------------------------------------------------------------

def test_listado_ordenado_y_fechas_iso_z(cliente_admin, bd):
    bd.agregar_acceso(datetime(2026, 10, 20, 8, 0, 0), "a@ejemplo.com", usuario="Ana Pérez")
    bd.agregar_acceso(datetime(2026, 10, 21, 9, 5, 7), "b@ejemplo.com", "MiraStock", "Denegado")
    resp = cliente_admin.get("/api/historial")
    assert resp.status_code == 200
    datos = resp.json()
    assert datos["total"] == 2 and datos["pagina"] == 1 and datos["tamano"] == 50 and datos["paginas"] == 1
    assert datos["filas"] == [
        {"Fecha": "2026-10-21T09:05:07Z", "Usuario": "", "Correo": "b@ejemplo.com",
         "Portal": "MiraStock", "Resultado": "Denegado", "FinalSesion": None, "TiempoSesionSeg": None, "EnCurso": False,
         "CierreExplicito": False},
        {"Fecha": "2026-10-20T08:00:00Z", "Usuario": "Ana Pérez", "Correo": "a@ejemplo.com",
         "Portal": "Energía", "Resultado": "OK", "FinalSesion": None, "TiempoSesionSeg": None, "EnCurso": False,
         "CierreExplicito": False},
    ]


def test_listado_cierre_explicito(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", final_sesion=FECHA + timedelta(minutes=3), cierre=True)
    bd.agregar_acceso(FECHA - timedelta(hours=1), "b@ejemplo.com", final_sesion=FECHA - timedelta(minutes=50))
    filas = cliente_admin.get("/api/historial").json()["filas"]
    assert [(f["Correo"], f["CierreExplicito"], f["EnCurso"]) for f in filas] == [
        ("a@ejemplo.com", True, False), ("b@ejemplo.com", False, False),
    ]


def test_listado_columnas_de_sesion(cliente_admin, bd):
    inicio = datetime(2026, 10, 20, 8, 0, 0)
    bd.agregar_acceso(inicio, "a@ejemplo.com", final_sesion=inicio + timedelta(minutes=44, seconds=5))
    bd.agregar_acceso(inicio - timedelta(hours=1), "b@ejemplo.com", "MiraStock",
                      final_sesion=inicio - timedelta(minutes=58), en_curso=True)
    filas = cliente_admin.get("/api/historial").json()["filas"]
    assert [(f["FinalSesion"], f["TiempoSesionSeg"], f["EnCurso"]) for f in filas] == [
        ("2026-10-20T08:44:05Z", 2645, False),
        ("2026-10-20T07:02:00Z", 120, True),
    ]


def test_fila_con_fecha_o_correo_nulos_no_rompe(cliente_admin, bd, monkeypatch):
    fila = {"Fecha": None, "Usuario": "", "Correo": None, "Portal": "MiraStock", "Resultado": "OK",
            "FinalSesion": None, "TiempoSesionSeg": None, "EnCurso": False,
         "CierreExplicito": False}
    monkeypatch.setattr(db, "listar_historial", lambda *args: ([dict(fila)], 1))
    datos = cliente_admin.get("/api/historial").json()
    assert datos["filas"] == [fila]
    lineas = cliente_admin.get("/api/historial/csv").content.decode("utf-8-sig").splitlines()
    assert lineas[1] == ";;;MiraStock;OK;;;"


def test_listado_vacio(cliente_admin):
    datos = cliente_admin.get("/api/historial").json()
    assert datos == {"filas": [], "total": 0, "pagina": 1, "tamano": 50, "paginas": 1}


def test_paginacion_de_50(cliente_admin, bd):
    for i in range(120):
        bd.agregar_acceso(FECHA + timedelta(minutes=i), f"u{i}@ejemplo.com")
    p1 = cliente_admin.get("/api/historial").json()
    assert p1["total"] == 120 and p1["paginas"] == 3 and len(p1["filas"]) == 50
    assert p1["filas"][0]["Correo"] == "u119@ejemplo.com"
    p3 = cliente_admin.get("/api/historial", params={"pagina": 3}).json()
    assert p3["pagina"] == 3 and len(p3["filas"]) == 20
    assert p3["filas"][-1]["Correo"] == "u0@ejemplo.com"
    assert cliente_admin.get("/api/historial", params={"pagina": 4}).json()["filas"] == []


def test_filtro_correo_contiene_sin_mayusculas(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "ana.perez@ejemplo.com")
    bd.agregar_acceso(FECHA, "otro@ejemplo.com")
    datos = cliente_admin.get("/api/historial", params={"correo": "  ANA.P "}).json()
    assert [f["Correo"] for f in datos["filas"]] == ["ana.perez@ejemplo.com"]
    assert bd.llamadas_historial[-1][1].correo == "ANA.P"


def test_filtros_portal_y_resultado_valor_canonico(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", "Energía", "OK")
    bd.agregar_acceso(FECHA, "b@ejemplo.com", "Energía", "Denegado")
    bd.agregar_acceso(FECHA, "c@ejemplo.com", "MiraStock", "Denegado")
    datos = cliente_admin.get("/api/historial", params={"portal": "energía", "resultado": "denegado"}).json()
    assert [f["Correo"] for f in datos["filas"]] == ["b@ejemplo.com"]
    filtros = bd.llamadas_historial[-1][1]
    assert (filtros.portal, filtros.resultado) == ("Energía", "Denegado")


def test_filtros_vacios_se_ignoran(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com")
    params = {"correo": "", "portal": "", "resultado": "", "desde": "", "hasta": ""}
    assert cliente_admin.get("/api/historial", params=params).json()["total"] == 1
    assert bd.llamadas_historial[-1][1] == db.FiltrosHistorial()


def test_fechas_desde_inclusivo_hasta_exclusivo(cliente_admin, bd):
    bd.agregar_acceso(datetime(2026, 10, 20, 3, 0), "antes@ejemplo.com")
    bd.agregar_acceso(datetime(2026, 10, 20, 3, 0, 1), "dentro@ejemplo.com")
    bd.agregar_acceso(datetime(2026, 10, 21, 3, 0), "limite@ejemplo.com")
    # 00:00 en Chile (UTC-3) = 03:00 UTC
    params = {"desde": "2026-10-20T00:00:01-03:00", "hasta": "2026-10-21T03:00:00.000Z"}
    datos = cliente_admin.get("/api/historial", params=params).json()
    assert [f["Correo"] for f in datos["filas"]] == ["dentro@ejemplo.com"]
    filtros = bd.llamadas_historial[-1][1]
    assert filtros.desde == datetime(2026, 10, 20, 3, 0, 1) and filtros.desde.tzinfo is None
    assert filtros.hasta == datetime(2026, 10, 21, 3, 0) and filtros.hasta.tzinfo is None


def test_fecha_sin_zona_se_toma_como_utc(cliente_admin, bd):
    cliente_admin.get("/api/historial", params={"desde": "2026-10-20", "hasta": "2026-10-21T12:00"})
    filtros = bd.llamadas_historial[-1][1]
    assert filtros.desde == datetime(2026, 10, 20) and filtros.hasta == datetime(2026, 10, 21, 12)


# ---------------------------------------------------------------------------
# Validación (422 {detail, errores})
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ENDPOINTS)
@pytest.mark.parametrize("params, campo", [
    ({"portal": "Admin"}, "portal"),
    ({"resultado": "Error"}, "resultado"),
    ({"desde": "20/10/2026"}, "desde"),
    ({"hasta": "mañana"}, "hasta"),
    ({"desde": "2026-10-21T00:00:00Z", "hasta": "2026-10-21T00:00:00Z"}, "hasta"),
    ({"desde": "2026-10-22T00:00:00Z", "hasta": "2026-10-21T00:00:00Z"}, "hasta"),
    ({"correo": "a" * 257}, "correo"),
])
def test_validacion_422(cliente_admin, bd, ruta, params, campo):
    resp = cliente_admin.get(ruta, params=params)
    assert resp.status_code == 422
    datos = resp.json()
    assert set(datos) == {"detail", "errores"}
    assert campo in datos["errores"]
    assert datos["detail"] == next(iter(datos["errores"].values()))
    assert bd.llamadas_historial == []


def test_validacion_junta_todos_los_errores(cliente_admin):
    datos = cliente_admin.get("/api/historial", params={"portal": "x", "resultado": "y", "desde": "z"}).json()
    assert set(datos["errores"]) == {"portal", "resultado", "desde"}
    assert datos["errores"]["portal"] == "El portal debe ser Energía o MiraStock."


@pytest.mark.parametrize("pagina", ["0", "-1", "abc", "1000001"])
def test_pagina_invalida_422(cliente_admin, pagina):
    resp = cliente_admin.get("/api/historial", params={"pagina": pagina})
    assert resp.status_code == 422
    assert "pagina" in resp.json()["errores"]


@pytest.mark.parametrize("tz", ["841", "-841", "x"])
def test_tz_offset_invalido_422(cliente_admin, tz):
    resp = cliente_admin.get("/api/historial/resumen", params={"tz_offset_min": tz})
    assert resp.status_code == 422
    assert "tz_offset_min" in resp.json()["errores"]


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def test_resumen_indicadores(cliente_admin, bd):
    bd.agregar_acceso(datetime(2026, 10, 20, 12, 0), "a@ejemplo.com", "Energía", "OK")
    bd.agregar_acceso(datetime(2026, 10, 20, 13, 0), "a@ejemplo.com", "MiraStock", "OK")
    bd.agregar_acceso(datetime(2026, 10, 21, 12, 0), "b@ejemplo.com", "Energía", "Denegado")
    resp = cliente_admin.get("/api/historial/resumen")
    assert resp.status_code == 200
    assert resp.json() == {
        "total": 3,
        "usuariosUnicos": 2,
        "porPortal": {"Energía": 2, "MiraStock": 1},
        "denegados": 1,
        "tiempoPromedioSeg": None,
        "tiempoTotalSeg": {"Energía": 0, "MiraStock": 0},
        "enCurso": 0,
        "cerradasBoton": 0,
        "porDia": [{"dia": "2026-10-20", "total": 2}, {"dia": "2026-10-21", "total": 1}],
    }


def test_resumen_cerradas_con_boton(cliente_admin, bd):
    fin = FECHA + timedelta(minutes=5)
    bd.agregar_acceso(FECHA, "a@ejemplo.com", final_sesion=fin, cierre=True)
    bd.agregar_acceso(FECHA, "b@ejemplo.com", "MiraStock", final_sesion=fin, cierre=True)
    bd.agregar_acceso(FECHA, "c@ejemplo.com", final_sesion=fin)
    assert cliente_admin.get("/api/historial/resumen").json()["cerradasBoton"] == 2


def test_resumen_tiempos_de_sesion(cliente_admin, bd):
    inicio = datetime(2026, 10, 20, 12, 0)
    bd.agregar_acceso(inicio, "a@ejemplo.com", "Energía", final_sesion=inicio + timedelta(minutes=10))
    bd.agregar_acceso(inicio, "b@ejemplo.com", "Energía", final_sesion=inicio + timedelta(minutes=20))
    bd.agregar_acceso(inicio, "c@ejemplo.com", "MiraStock", final_sesion=inicio + timedelta(minutes=30),
                      en_curso=True)
    bd.agregar_acceso(inicio, "d@ejemplo.com", "MiraStock")  # sin latidos: no cuenta en los tiempos
    datos = cliente_admin.get("/api/historial/resumen").json()
    assert datos["tiempoPromedioSeg"] == 1200
    assert datos["tiempoTotalSeg"] == {"Energía": 1800, "MiraStock": 1800}
    assert datos["enCurso"] == 1


def test_resumen_agrupa_por_dia_local(cliente_admin, bd):
    # 02:00 UTC del 21 son las 23:00 del 20 en UTC-3.
    bd.agregar_acceso(datetime(2026, 10, 21, 2, 0), "a@ejemplo.com")
    datos = cliente_admin.get("/api/historial/resumen", params={"tz_offset_min": -180}).json()
    assert datos["porDia"] == [{"dia": "2026-10-20", "total": 1}]
    assert bd.llamadas_historial[-1][2] == -180


def test_resumen_aplica_filtros(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", "Energía", "OK")
    bd.agregar_acceso(FECHA, "b@ejemplo.com", "MiraStock", "OK")
    datos = cliente_admin.get("/api/historial/resumen", params={"portal": "MiraStock"}).json()
    assert datos["total"] == 1 and datos["porPortal"] == {"Energía": 0, "MiraStock": 1}


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def test_csv_formato(cliente_admin, bd):
    bd.agregar_acceso(datetime(2026, 10, 20, 8, 5, 9), "ana@ejemplo.com", usuario="Ana Pérez")
    bd.agregar_acceso(datetime(2026, 10, 19, 7, 0), "sin.nombre@ejemplo.com", "MiraStock", "Denegado")
    resp = cliente_admin.get("/api/historial/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert resp.headers["content-disposition"] == f'attachment; filename="historial_accesos_{hoy}.csv"'
    assert "x-historial-truncado" not in resp.headers
    assert resp.content.startswith(b"\xef\xbb\xbf")
    assert resp.content.decode("utf-8-sig").split("\r\n") == [
        "Fecha (UTC);Usuario;Correo;Portal;Resultado;Final de sesión (UTC);Tiempo de sesión (min);Cierre",
        "2026-10-20 08:05:09;Ana Pérez;ana@ejemplo.com;Energía;OK;;;",
        "2026-10-19 07:00:00;;sin.nombre@ejemplo.com;MiraStock;Denegado;;;",
        "",
    ]


def test_csv_columnas_de_sesion_minutos_enteros(cliente_admin, bd):
    inicio = datetime(2026, 10, 20, 8, 0, 0)
    bd.agregar_acceso(inicio, "a@ejemplo.com", final_sesion=inicio + timedelta(minutes=65, seconds=59))
    bd.agregar_acceso(inicio - timedelta(hours=1), "b@ejemplo.com", final_sesion=inicio - timedelta(minutes=59, seconds=20))
    lineas = cliente_admin.get("/api/historial/csv").content.decode("utf-8-sig").split("\r\n")
    assert lineas[1] == "2026-10-20 08:00:00;;a@ejemplo.com;Energía;OK;2026-10-20 09:05:59;65;Inactividad"
    assert lineas[2] == "2026-10-20 07:00:00;;b@ejemplo.com;Energía;OK;2026-10-20 07:00:40;0;Inactividad"


def test_csv_columna_cierre(cliente_admin, bd):
    inicio = datetime(2026, 10, 20, 8, 0, 0)
    fin = inicio + timedelta(minutes=10)
    bd.agregar_acceso(inicio, "boton@ejemplo.com", final_sesion=fin, cierre=True)
    bd.agregar_acceso(inicio - timedelta(minutes=1), "curso@ejemplo.com", final_sesion=fin, en_curso=True)
    bd.agregar_acceso(inicio - timedelta(minutes=2), "inactivo@ejemplo.com", final_sesion=fin)
    bd.agregar_acceso(inicio - timedelta(minutes=3), "sin.latidos@ejemplo.com")
    lineas = cliente_admin.get("/api/historial/csv").content.decode("utf-8-sig").split("\r\n")
    assert lineas[0].endswith(";Tiempo de sesión (min);Cierre")
    assert [linea.split(";")[-1] for linea in lineas[1:-1]] == ["Botón", "En curso", "Inactividad", ""]


def test_csv_neutraliza_formulas(cliente_admin, bd):
    peligrosos = ["=1+1", "+cmd", "-2", "@SUMA(A1)", "\tx"]
    for i, usuario in enumerate(peligrosos):
        bd.agregar_acceso(datetime(2026, 10, 20, 8, i), f"u{i}@ejemplo.com", usuario=usuario)
    bd.agregar_acceso(datetime(2026, 10, 20, 9, 0), "=hack@ejemplo.com", usuario="Normal")
    lineas = cliente_admin.get("/api/historial/csv").content.decode("utf-8-sig").split("\r\n")[1:-1]
    usuarios = [linea.split(";")[1] for linea in lineas]
    assert usuarios == ["Normal", "'\tx", "'@SUMA(A1)", "'-2", "'+cmd", "'=1+1"]
    assert lineas[0].split(";")[2] == "'=hack@ejemplo.com"


def test_csv_escapa_separador(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", usuario='Pérez; "Ana"')
    linea = cliente_admin.get("/api/historial/csv").content.decode("utf-8-sig").split("\r\n")[1]
    assert linea == '2026-10-20 15:30:00;"Pérez; ""Ana""";a@ejemplo.com;Energía;OK;;;'


def test_csv_aplica_filtros_sin_paginar(cliente_admin, bd):
    for i in range(60):
        bd.agregar_acceso(FECHA, f"u{i}@ejemplo.com", "MiraStock")
    bd.agregar_acceso(FECHA, "e@ejemplo.com", "Energía")
    lineas = cliente_admin.get("/api/historial/csv", params={"portal": "MiraStock"}).content.decode("utf-8-sig")
    assert len(lineas.split("\r\n")) == 1 + 60 + 1
    _, filtros, pagina, tamano = bd.llamadas_historial[-1]
    assert (filtros.portal, pagina, tamano) == ("MiraStock", 1, 50_000)


def test_csv_tope_avisa_truncado(cliente_admin, bd, monkeypatch):
    monkeypatch.setattr(main, "TOPE_CSV_HISTORIAL", 2)
    for i in range(3):
        bd.agregar_acceso(datetime(2026, 10, 20, 8, i), f"u{i}@ejemplo.com")
    resp = cliente_admin.get("/api/historial/csv")
    assert resp.headers["x-historial-truncado"] == "2"
    assert len(resp.content.decode("utf-8-sig").split("\r\n")) == 1 + 2 + 1


# ---------------------------------------------------------------------------
# SQL de db.py (sin BD: se verifica el texto y los parámetros)
# ---------------------------------------------------------------------------

def test_where_sin_filtros():
    assert db._where_historial(db.FiltrosHistorial()) == ("", [])


def test_where_con_todos_los_filtros_es_parametrizado():
    desde, hasta = datetime(2026, 10, 1), datetime(2026, 10, 2)
    filtros = db.FiltrosHistorial("Ana'; DROP TABLE x--", "Energía", "OK", desde, hasta)
    sql, params = db._where_historial(filtros)
    assert sql == (
        " WHERE Correo LIKE ? ESCAPE '\\' AND Portal = ? AND Resultado = ?"
        " AND Fecha >= ? AND Fecha < ?"
    )
    assert params == ["%ana'; drop table x--%", "Energía", "OK", desde, hasta]


def test_where_escapa_comodines_de_like():
    sql, params = db._where_historial(db.FiltrosHistorial(correo="a%b_c[d\\e"))
    assert params == ["%a\\%b\\_c\\[d\\\\e%"]


class CursorFalso:
    def __init__(self, uno, todos):
        self.ejecutados = []
        self._uno, self._todos = list(uno), list(todos)

    def execute(self, sql, *params):
        self.ejecutados.append((sql, params))

    def fetchone(self):
        return self._uno.pop(0)

    def fetchall(self):
        return self._todos.pop(0)


@pytest.fixture
def cursor_falso(monkeypatch):
    from contextlib import contextmanager

    estado = {}

    @contextmanager
    def conexion():
        class Conn:
            def cursor(self):
                return estado["cursor"]
        yield Conn()

    monkeypatch.setattr(db, "_conexion", conexion)
    return estado


def test_db_listar_historial_offset_y_usuario_nulo(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(
        uno=[(51,)], todos=[[(FECHA, None, "a@ejemplo.com", "Energía", "OK", FECHA + timedelta(minutes=5), 300, 1, 0)]]
    )
    filas, total = db.listar_historial(db.FiltrosHistorial(portal="Energía"), 2, 50)
    assert total == 51
    assert filas == [{
        "Fecha": FECHA, "Usuario": "", "Correo": "a@ejemplo.com", "Portal": "Energía", "Resultado": "OK",
        "FinalSesion": FECHA + timedelta(minutes=5), "TiempoSesionSeg": 300, "EnCurso": True,
        "CierreExplicito": False,
    }]
    (sql_total, p_total), (sql_filas, p_filas) = cur.ejecutados
    assert "FinalSesion, TiempoSesionSeg, ISNULL(EnCurso, 0) AS EnCurso" in sql_filas
    assert "ISNULL(CierreExplicito, 0) AS CierreExplicito" in sql_filas
    assert "core.vHistorialAccesos WHERE Portal = ?" in sql_total and p_total == ("Energía",)
    assert "ORDER BY Fecha DESC" in sql_filas and "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in sql_filas
    assert p_filas == ("Energía", 50, 50)


def test_db_resumen_historial(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(
        uno=[(5, 2, 3, 2, 1, 1500, 3000, 1500, 2, 1)], todos=[[(date(2026, 10, 20), 4), (date(2026, 10, 21), 1)]]
    )
    r = db.resumen_historial(db.FiltrosHistorial(resultado="OK"), -180)
    assert r == {
        "total": 5, "usuariosUnicos": 2, "porPortal": {"Energía": 3, "MiraStock": 2}, "denegados": 1,
        "tiempoPromedioSeg": 1500, "tiempoTotalSeg": {"Energía": 3000, "MiraStock": 1500}, "enCurso": 2,
        "cerradasBoton": 1,
        "porDia": [{"dia": "2026-10-20", "total": 4}, {"dia": "2026-10-21", "total": 1}],
    }
    sql_totales = cur.ejecutados[0][0]
    assert "AVG(CAST(TiempoSesionSeg AS BIGINT))" in sql_totales
    assert "SUM(CASE WHEN EnCurso = 1 THEN 1 ELSE 0 END)" in sql_totales
    assert "SUM(CASE WHEN CierreExplicito = 1 THEN 1 ELSE 0 END)" in sql_totales
    sql_dias, p_dias = cur.ejecutados[1]
    assert "DATEADD(minute, ?, Fecha)" in sql_dias and "GROUP BY Dia" in sql_dias
    assert p_dias == (-180, "OK")


def test_db_resumen_sin_latidos_promedio_nulo(cursor_falso):
    cursor_falso["cursor"] = CursorFalso(uno=[(0, 0, 0, 0, 0, None, 0, 0, 0, 0)], todos=[[]])
    r = db.resumen_historial(db.FiltrosHistorial(), 0)
    assert r["tiempoPromedioSeg"] is None and r["tiempoTotalSeg"] == {"Energía": 0, "MiraStock": 0}


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_con_cache_busting_v9(cliente_admin, ruta):
    texto = cliente_admin.get(ruta).text
    assert 'href="/static/styles.css?v=9"' in texto
    assert '.js"' not in texto and "?v=8" not in texto  # todo archivo local lleva ?v=9


def test_historial_columnas_e_indicadores_de_sesion(cliente_admin):
    texto = cliente_admin.get("/historial").text
    for marca in ("Final de sesión", "Tiempo de sesión", 'id="i-promedio"', 'id="i-tiempo-energia"',
                  'id="i-tiempo-mirastock"', 'id="i-en-curso"', '<th scope="col">Cierre</th>',
                  'id="i-cerradas-boton"'):
        assert marca in texto
