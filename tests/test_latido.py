"""POST /api/latido: latidos de sesión de MiraStock y Energía, CORS, validaciones y SQL de db.py."""

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import timedelta

import httpx
import pyodbc
import pytest

from app import db, main
from tests.conftest import CLAVE_PRIVADA, OTRA_CLAVE_PRIVADA, crear_token, crear_token_energia

RUTA = "/api/latido"
LLAVE = "3f2b8c1e-9d4a-4e7b-8a6c-1b2d3e4f5a6b"
CORREO = "usuario@ejemplo.com"
ORIGEN_ENERGIA = "https://energia.ejemplo.com"
ORIGEN_MIRASTOCK = "https://mirastock.ejemplo.com"  # configurado con barra final: se normaliza


def latir(cliente, cuerpo, **kwargs):
    return cliente.post(RUTA, json=cuerpo, **kwargs)


def mirastock(llave=LLAVE):
    return {"tipo": "mirastock", "t": llave}


def energia(token=None):
    return {"tipo": "energia", "token": token if token is not None else crear_token_energia(email=CORREO)}


# ---------------------------------------------------------------------------
# MiraStock
# ---------------------------------------------------------------------------

def test_mirastock_actualiza_final_de_sesion(cliente, bd):
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5))
    resp = latir(cliente, mirastock())
    assert resp.status_code == 204 and resp.content == b""
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == bd.ahora


def test_mirastock_no_exige_header_csrf_y_acepta_text_plain(cliente, bd):
    # navigator.sendBeacon envía text/plain y no puede agregar X-Requested-With.
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5))
    resp = cliente.post(RUTA, content=json.dumps(mirastock()), headers={"Content-Type": "text/plain;charset=UTF-8"})
    assert resp.status_code == 204
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == bd.ahora


def test_mirastock_guid_se_normaliza(cliente, bd):
    resp = latir(cliente, mirastock("{" + LLAVE.upper() + "}"))
    assert resp.status_code == 204
    assert bd.llamadas_latido == [("mirastock", LLAVE)]


@pytest.mark.parametrize("llave", ["", "abc", "3f2b8c1e-9d4a-4e7b-8a6c", LLAVE + "0", 123, None, [LLAVE], {"a": 1}])
def test_mirastock_guid_invalido_400(cliente, bd, llave):
    resp = latir(cliente, mirastock(llave))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "La llave de sesión no es válida."}
    assert bd.llamadas_latido == []


def test_mirastock_sin_llave_400(cliente, bd):
    assert latir(cliente, {"tipo": "mirastock"}).status_code == 400
    assert bd.llamadas_latido == []


def test_mirastock_llave_vencida_igual_acepta_el_latido(cliente, bd):
    # ExpiraEn solo controla la entrada al chat: la sesión puede seguir abierta después.
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(hours=3), expira_en=bd.ahora - timedelta(hours=2))
    assert latir(cliente, mirastock()).status_code == 204
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == bd.ahora


def test_mirastock_llave_de_mas_de_12_horas_no_se_actualiza(cliente, bd):
    final = bd.ahora - timedelta(hours=1)
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(hours=13), final_sesion=final)
    assert latir(cliente, mirastock()).status_code == 204
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == final


@pytest.mark.parametrize("hace_s, actualiza", [(30, False), (59, False), (61, True), (120, True)])
def test_mirastock_regla_de_60_segundos(cliente, bd, hace_s, actualiza):
    anterior = bd.ahora - timedelta(seconds=hace_s)
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=10), final_sesion=anterior)
    assert latir(cliente, mirastock()).status_code == 204
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == (bd.ahora if actualiza else anterior)


def test_mirastock_204_igual_exista_o_no_la_llave(cliente, bd):
    otra = str(uuid.uuid4())
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5))
    existe = latir(cliente, mirastock(LLAVE))
    no_existe = latir(cliente, mirastock(otra))
    assert existe.status_code == no_existe.status_code == 204
    assert existe.content == no_existe.content == b""
    sin_fecha = lambda r: {k: v for k, v in r.headers.items() if k != "date"}  # noqa: E731
    assert sin_fecha(existe) == sin_fecha(no_existe)
    assert otra not in bd.sesiones_agente


def test_mirastock_error_de_bd_503(cliente, monkeypatch):
    def falla(llave):
        raise pyodbc.OperationalError("08S01", "Sin conexión")

    monkeypatch.setattr(db, "latido_mirastock", falla)
    resp = latir(cliente, mirastock())
    assert resp.status_code == 503
    assert "base de datos" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Energía
# ---------------------------------------------------------------------------

def test_energia_sin_sesion_previa_inserta(cliente, bd):
    assert latir(cliente, energia()).status_code == 204
    assert bd.accesos == [
        {"Correo": CORREO, "Portal": "Energía", "Resultado": "OK", "Fecha": bd.ahora, "FinalSesion": bd.ahora,
         "CierreExplicito": False}
    ]


def test_energia_correo_del_token_se_normaliza(cliente, bd):
    token = crear_token_energia(email="  Usuario@Ejemplo.COM ")
    assert latir(cliente, energia(token)).status_code == 204
    assert bd.llamadas_latido == [("energia", CORREO)]


def test_energia_usa_preferred_username_si_no_hay_email(cliente, bd):
    token = crear_token_energia(email=None, preferred_username=CORREO)
    assert latir(cliente, energia(token)).status_code == 204
    assert bd.llamadas_latido == [("energia", CORREO)]


def test_energia_actualiza_la_fila_del_ingreso_reciente(cliente, bd):
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=20))
    assert latir(cliente, energia()).status_code == 204
    assert fila["FinalSesion"] == bd.ahora and len(bd.accesos) == 1


def test_energia_extiende_sesion_larga_por_su_ultimo_latido(cliente, bd):
    # Entró hace 2 h, pero el último latido fue hace 10 min: la ventana de 30 min cuenta desde FinalSesion.
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(hours=2), bd.ahora - timedelta(minutes=10))
    assert latir(cliente, energia()).status_code == 204
    assert fila["FinalSesion"] == bd.ahora and len(bd.accesos) == 1


def test_energia_actualiza_solo_la_ultima_fila(cliente, bd):
    vieja = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=25), bd.ahora - timedelta(minutes=20))
    nueva = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=15))
    latir(cliente, energia())
    assert nueva["FinalSesion"] == bd.ahora
    assert vieja["FinalSesion"] == bd.ahora - timedelta(minutes=20)


@pytest.mark.parametrize("fecha_min, final_min", [(31, None), (120, 31)])
def test_energia_despues_de_30_minutos_inserta_otra_fila(cliente, bd, fecha_min, final_min):
    final = bd.ahora - timedelta(minutes=final_min) if final_min else None
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=fecha_min), final)
    assert latir(cliente, energia()).status_code == 204
    assert fila["FinalSesion"] == final
    assert len(bd.accesos) == 2 and bd.accesos[1]["Fecha"] == bd.ahora


@pytest.mark.parametrize("cambio", [{"Resultado": "Denegado"}, {"Portal": "MiraStock"}, {"Correo": "otro@ejemplo.com"}])
def test_energia_ignora_filas_que_no_son_su_ingreso_ok(cliente, bd, cambio):
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=5))
    fila.update(cambio)
    latir(cliente, energia())
    assert fila["FinalSesion"] is None
    assert len(bd.accesos) == 2


@pytest.mark.parametrize("hace_s, actualiza", [(30, False), (61, True)])
def test_energia_regla_de_60_segundos(cliente, bd, hace_s, actualiza):
    anterior = bd.ahora - timedelta(seconds=hace_s)
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=10), anterior)
    assert latir(cliente, energia()).status_code == 204
    assert fila["FinalSesion"] == (bd.ahora if actualiza else anterior)
    assert len(bd.accesos) == 1  # un latido seguido nunca crea otra fila


@pytest.mark.parametrize("token", [
    "no-es-un-jwt",
    crear_token_energia(clave=OTRA_CLAVE_PRIVADA),           # firma de otra clave
    crear_token(email=CORREO, clave=CLAVE_PRIVADA),          # token del Portal Externo (otro emisor y clave)
    crear_token_energia(clave=CLAVE_PRIVADA),                # emisor Energía firmado con la clave del Portal Externo
    crear_token_energia(iss="otro.ejemplo.com"),             # emisor distinto
    crear_token_energia(exp=1),                              # vencido
    crear_token_energia(email=None),                         # sin correo
])
def test_energia_token_invalido_401(cliente, bd, token):
    resp = latir(cliente, energia(token))
    assert resp.status_code == 401
    assert resp.json() == {"detail": "El token de sesión no es válido."}
    assert bd.llamadas_latido == [] and bd.accesos == []


@pytest.mark.parametrize("token", ["", "   ", None, 123])
def test_energia_sin_token_400(cliente, bd, token):
    resp = latir(cliente, {"tipo": "energia", "token": token})
    assert resp.status_code == 400
    assert bd.llamadas_latido == []


def test_energia_clave_publica_no_disponible_503(cliente, bd, clave_de_energia):
    clave_de_energia["error"] = httpx.ConnectError("sin red")
    resp = latir(cliente, energia())
    assert resp.status_code == 503
    assert bd.llamadas_latido == []


def test_energia_usa_su_propia_clave_y_no_la_del_portal(cliente, bd, clave_del_portal, clave_de_energia):
    latir(cliente, energia())
    assert clave_de_energia["descargas"] == 1 and clave_del_portal["descargas"] == 0


def test_energia_error_de_bd_503(cliente, monkeypatch):
    def falla(correo):
        raise pyodbc.OperationalError("08S01", "Sin conexión")

    monkeypatch.setattr(db, "latido_energia", falla)
    assert latir(cliente, energia()).status_code == 503


# ---------------------------------------------------------------------------
# Body inválido
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cuerpo", [{}, {"tipo": "otro"}, {"tipo": "MiraStock", "t": LLAVE}, {"t": LLAVE}, [], "texto", 1])
def test_tipo_invalido_400(cliente, bd, cuerpo):
    assert latir(cliente, cuerpo).status_code == 400
    assert bd.llamadas_latido == []


@pytest.mark.parametrize("contenido", [b"", b"{no es json", b"\xff\xfe", b"null"])
def test_json_invalido_400(cliente, bd, contenido):
    resp = cliente.post(RUTA, content=contenido, headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert "detail" in resp.json()


@pytest.mark.parametrize("tipo", ["application/x-www-form-urlencoded", "multipart/form-data", ""])
def test_content_type_no_permitido_400(cliente, bd, tipo):
    resp = cliente.post(RUTA, content=json.dumps(mirastock()), headers={"Content-Type": tipo})
    assert resp.status_code == 400
    assert bd.llamadas_latido == []


def test_body_de_mas_de_8_kb_400(cliente, bd):
    cuerpo = {**mirastock(), "relleno": "x" * (8 * 1024)}
    resp = latir(cliente, cuerpo)
    assert resp.status_code == 400
    assert bd.llamadas_latido == []


def test_body_de_8_kb_justos_se_acepta(cliente, bd):
    base = json.dumps({**mirastock(), "r": ""})
    contenido = json.dumps({**mirastock(), "r": "x" * (8 * 1024 - len(base))}).encode()
    assert len(contenido) == 8 * 1024
    resp = cliente.post(RUTA, content=contenido, headers={"Content-Type": "application/json"})
    assert resp.status_code == 204


def test_body_grande_sin_content_length_400(cliente, bd):
    def trozos():
        yield b'{"tipo": "mirastock", "t": "' + LLAVE.encode() + b'", "r": "'
        yield b"x" * (9 * 1024)
        yield b'"}'

    resp = cliente.post(RUTA, content=trozos(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert bd.llamadas_latido == []


def test_solo_acepta_post(cliente):
    assert cliente.get(RUTA).status_code == 405


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def preflight(cliente, origen, metodo="POST", headers="content-type", ruta=RUTA):
    return cliente.options(ruta, headers={
        "Origin": origen, "Access-Control-Request-Method": metodo, "Access-Control-Request-Headers": headers,
    })


@pytest.mark.parametrize("origen", [ORIGEN_ENERGIA, ORIGEN_MIRASTOCK, "HTTPS://Energia.Ejemplo.com"])
def test_preflight_origen_permitido(cliente, origen):
    resp = preflight(cliente, origen)
    assert resp.status_code == 204
    assert resp.headers["access-control-allow-origin"] == origen
    assert resp.headers["access-control-allow-methods"] == "POST"
    assert resp.headers["access-control-allow-headers"] == "Content-Type"
    assert resp.headers["access-control-max-age"] == "600"
    assert resp.headers["vary"] == "Origin"
    assert "access-control-allow-credentials" not in resp.headers


@pytest.mark.parametrize("origen", ["https://malo.ejemplo.com", "http://energia.ejemplo.com", "null",
                                    "https://energia.ejemplo.com.malo.com"])
def test_preflight_origen_no_permitido_403(cliente, origen):
    resp = preflight(cliente, origen)
    assert resp.status_code == 403
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize("metodo", ["PUT", "DELETE", "GET"])
def test_preflight_solo_post(cliente, metodo):
    resp = preflight(cliente, ORIGEN_ENERGIA, metodo)
    assert resp.status_code == 403
    assert "access-control-allow-origin" not in resp.headers


def test_post_desde_origen_permitido_trae_allow_origin(cliente, bd):
    resp = latir(cliente, mirastock(), headers={"Origin": ORIGEN_MIRASTOCK})
    assert resp.status_code == 204
    assert resp.headers["access-control-allow-origin"] == ORIGEN_MIRASTOCK
    assert "access-control-allow-credentials" not in resp.headers


def test_errores_desde_origen_permitido_tambien_traen_allow_origin(cliente, bd):
    # Así el JS del portal puede leer el 400/401 en lugar de un error de CORS.
    resp = latir(cliente, energia("malo"), headers={"Origin": ORIGEN_ENERGIA})
    assert resp.status_code == 401
    assert resp.headers["access-control-allow-origin"] == ORIGEN_ENERGIA


def test_post_desde_origen_no_permitido_403(cliente, bd):
    resp = latir(cliente, mirastock(), headers={"Origin": "https://malo.ejemplo.com"})
    assert resp.status_code == 403
    assert "access-control-allow-origin" not in resp.headers
    assert bd.llamadas_latido == []


def test_post_sin_origin_se_procesa(cliente, bd):
    resp = latir(cliente, mirastock())
    assert resp.status_code == 204
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize("ruta", ["/api/usuarios", "/api/me", "/api/historial"])
def test_resto_de_la_api_sin_cors(cliente_admin, ruta):
    assert "access-control-allow-origin" not in preflight(cliente_admin, ORIGEN_ENERGIA, ruta=ruta).headers
    resp = cliente_admin.get(ruta, headers={"Origin": ORIGEN_ENERGIA})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_resto_de_la_api_sigue_exigiendo_csrf(cliente_admin):
    resp = cliente_admin.post("/api/usuarios", json={}, headers={"Origin": ORIGEN_ENERGIA})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Solicitud rechazada por seguridad."}


# ---------------------------------------------------------------------------
# Logs: nunca la llave ni el token; /api/latido fuera del access log
# ---------------------------------------------------------------------------

def test_logs_no_contienen_llave_ni_token(cliente, bd, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    token_malo = crear_token_energia(clave=OTRA_CLAVE_PRIVADA)
    token_bueno = crear_token_energia(email=CORREO)
    latir(cliente, mirastock())
    latir(cliente, energia(token_bueno))
    latir(cliente, energia(token_malo))

    def falla(llave):
        raise pyodbc.OperationalError("08S01", "Sin conexión")

    monkeypatch.setattr(db, "latido_mirastock", falla)
    latir(cliente, mirastock())
    texto = caplog.text + " ".join(str(r.args) for r in caplog.records)
    for secreto in (LLAVE, token_bueno, token_malo):
        assert secreto not in texto


def _registro_access(ruta):
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5678", "POST", ruta, "1.1", 204), None,
    )


@pytest.mark.parametrize("ruta, se_registra", [
    ("/api/latido", False), ("/api/latido?x=1", False), ("/api/usuarios", True), ("/health", True),
])
def test_filtro_access_log(ruta, se_registra):
    assert main._SinLatidos().filter(_registro_access(ruta)) is se_registra


def test_filtro_access_log_instalado_en_uvicorn():
    assert any(isinstance(f, main._SinLatidos) for f in logging.getLogger("uvicorn.access").filters)


# ---------------------------------------------------------------------------
# SQL de db.py (sin BD: se verifica el texto y los parámetros)
# ---------------------------------------------------------------------------

class CursorLatido:
    def __init__(self, rowcount=0, uno=None):
        self.ejecutados = []
        self.rowcount = rowcount
        self._uno = uno

    def execute(self, sql, *params):
        self.ejecutados.append((sql, params))

    def fetchone(self):
        return self._uno


@pytest.fixture
def cursor_latido(monkeypatch):
    estado = {}

    @contextmanager
    def conexion():
        class Conn:
            def cursor(self):
                return estado["cursor"]
        yield Conn()

    monkeypatch.setattr(db, "_conexion", conexion)
    return estado


@pytest.mark.parametrize("rowcount, esperado", [(1, True), (0, False)])
def test_db_latido_mirastock_sql(cursor_latido, rowcount, esperado):
    cursor_latido["cursor"] = cur = CursorLatido(rowcount=rowcount)
    assert db.latido_mirastock(LLAVE) is esperado
    [(sql, params)] = cur.ejecutados
    assert params == (LLAVE,)
    assert sql.startswith("UPDATE core.SesionesAgente SET FinalSesion = SYSUTCDATETIME()")
    assert "WHERE Token = ? AND CreadoEn >= DATEADD(HOUR, -12, SYSUTCDATETIME())" in sql
    assert "(FinalSesion IS NULL OR FinalSesion < DATEADD(SECOND, -60, SYSUTCDATETIME()))" in sql
    assert "AND COALESCE(CierreExplicito, 0) = 0" in sql
    assert "ExpiraEn" not in sql and "CierreExplicito = 1" not in sql


@pytest.mark.parametrize("fila, insertada", [((True,), True), ((False,), False)])
def test_db_latido_energia_sql(cursor_latido, fila, insertada):
    cursor_latido["cursor"] = cur = CursorLatido(uno=fila)
    assert db.latido_energia(CORREO) is insertada
    [(sql, params)] = cur.ejecutados
    assert params == (CORREO,)
    assert sql.count("?") == 1
    assert "WITH (UPDLOCK, HOLDLOCK)" in sql
    assert "Portal = N'Energía' AND Resultado = N'OK'" in sql
    assert "DECLARE @ahora DATETIME2 = SYSUTCDATETIME();" in sql
    assert "COALESCE(FinalSesion, Fecha) >= DATEADD(MINUTE, -30, @ahora)" in sql
    assert "ORDER BY Fecha DESC" in sql
    # La búsqueda toma la fila más reciente sin filtrar por cierre; el estado se decide después.
    busqueda = sql[sql.index("WITH ult AS"):sql.index("ORDER BY Fecha DESC")]
    assert "CierreExplicito, 0) = 0" not in busqueda
    assert "WHEN COALESCE(CierreExplicito, 0) = 0" in sql
    assert "FinalSesion < DATEADD(SECOND, -60, @ahora)" in sql
    assert "OUTPUT COALESCE(deleted.CierreExplicito, 0), deleted.FinalSesion INTO @previa" in sql
    assert "IF NOT EXISTS (SELECT 1 FROM @previa)" in sql
    assert "WHERE Cerrada = 1" in sql
    assert "INSERT INTO core.HistorialAccesos (Correo, Portal, Resultado, Fecha, FinalSesion)" in sql
    assert "SET XACT_ABORT ON" in sql


@pytest.mark.parametrize("rowcount, esperado", [(1, True), (0, False)])
def test_db_cierre_mirastock_sql(cursor_latido, rowcount, esperado):
    cursor_latido["cursor"] = cur = CursorLatido(rowcount=rowcount)
    assert db.cierre_mirastock(LLAVE) is esperado
    [(sql, params)] = cur.ejecutados
    assert params == (LLAVE,)
    assert sql.startswith("UPDATE core.SesionesAgente SET FinalSesion = SYSUTCDATETIME(),")
    assert "ExpiraEn = CASE WHEN ExpiraEn > SYSUTCDATETIME() THEN SYSUTCDATETIME() ELSE ExpiraEn END" in sql
    assert "CierreExplicito = 1" in sql
    assert ("WHERE Token = ? AND CreadoEn >= DATEADD(HOUR, -12, SYSUTCDATETIME())"
            " AND COALESCE(CierreExplicito, 0) = 0") in sql
    assert "SECOND, -60" not in sql  # sin la regla de 60 s


@pytest.mark.parametrize("fila, cerro", [((True,), True), ((False,), False)])
def test_db_cierre_energia_sql(cursor_latido, fila, cerro):
    cursor_latido["cursor"] = cur = CursorLatido(uno=fila)
    assert db.cierre_energia(CORREO) is cerro
    [(sql, params)] = cur.ejecutados
    assert params == (CORREO,) and sql.count("?") == 1
    assert "WITH (UPDLOCK, HOLDLOCK)" in sql
    assert "COALESCE(FinalSesion, Fecha) >= DATEADD(MINUTE, -30, @ahora)" in sql
    assert "CierreExplicito = CASE WHEN COALESCE(CierreExplicito, 0) = 0 THEN 1 ELSE CierreExplicito END" in sql
    assert "INSERT" not in sql


# ---------------------------------------------------------------------------
# Cierre explícito (v9): «Atrás» o «Cerrar sesión»
# ---------------------------------------------------------------------------

def cierre_mirastock(llave=LLAVE):
    return {**mirastock(llave), "cierre": True}


def cierre_energia(token=None):
    return {**energia(token), "cierre": True}


def test_cierre_mirastock_por_sendbeacon_text_plain(cliente, bd):
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5))
    resp = cliente.post(RUTA, content=json.dumps(cierre_mirastock()), headers={"Content-Type": "text/plain;charset=UTF-8"})
    assert resp.status_code == 204
    sesion = bd.sesiones_agente[LLAVE]
    assert sesion["CierreExplicito"] is True and sesion["FinalSesion"] == bd.ahora
    assert bd.llamadas_latido == [("cierre_mirastock", LLAVE)]


def test_cierre_mirastock_anula_expira_en(cliente, bd):
    # La llave vencía en 5 min: queda vencida en el momento del cierre.
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5), expira_en=bd.ahora + timedelta(minutes=5))
    latir(cliente, cierre_mirastock())
    assert bd.sesiones_agente[LLAVE]["ExpiraEn"] == bd.ahora


def test_cierre_mirastock_no_mueve_expira_en_ya_vencido(cliente, bd):
    vencida = bd.ahora - timedelta(hours=1)
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(hours=2), expira_en=vencida)
    latir(cliente, cierre_mirastock())
    assert bd.sesiones_agente[LLAVE]["ExpiraEn"] == vencida
    assert bd.sesiones_agente[LLAVE]["CierreExplicito"] is True


def test_cierre_mirastock_ignora_la_regla_de_60_segundos(cliente, bd):
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5), final_sesion=bd.ahora - timedelta(seconds=10))
    latir(cliente, cierre_mirastock())
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == bd.ahora
    assert bd.sesiones_agente[LLAVE]["CierreExplicito"] is True


def test_cierre_mirastock_no_vuelve_a_cerrar(cliente, bd):
    cerrada = bd.ahora - timedelta(minutes=3)
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=10), final_sesion=cerrada,
                             expira_en=cerrada, cierre=True)
    assert latir(cliente, cierre_mirastock()).status_code == 204
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == cerrada


def test_latido_mirastock_despues_del_cierre_no_cambia_final(cliente, bd):
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=10))
    latir(cliente, cierre_mirastock())
    cerrada = bd.sesiones_agente[LLAVE]["FinalSesion"]
    bd.ahora += timedelta(minutes=2)
    assert latir(cliente, mirastock()).status_code == 204
    assert bd.sesiones_agente[LLAVE]["FinalSesion"] == cerrada


def test_cierre_mirastock_llave_inexistente_204(cliente, bd):
    assert latir(cliente, cierre_mirastock(str(uuid.uuid4()))).status_code == 204


def test_cierre_energia_cierra_la_fila_activa(cliente, bd):
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=10), bd.ahora - timedelta(seconds=20))
    assert latir(cliente, cierre_energia()).status_code == 204
    assert fila["FinalSesion"] == bd.ahora and fila["CierreExplicito"] is True
    assert len(bd.accesos) == 1


def test_cierre_energia_sin_fila_activa_no_inserta(cliente, bd):
    vieja = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(hours=2), bd.ahora - timedelta(minutes=45))
    assert latir(cliente, cierre_energia()).status_code == 204
    assert bd.accesos == [vieja] and vieja["CierreExplicito"] is False


def test_cierre_energia_ya_cerrada_no_hace_nada(cliente, bd):
    cerrada = bd.ahora - timedelta(minutes=5)
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=20), cerrada, cierre=True)
    latir(cliente, cierre_energia())
    assert fila["FinalSesion"] == cerrada and len(bd.accesos) == 1


def test_cierre_energia_mira_solo_la_fila_mas_reciente(cliente, bd):
    # La más reciente ya está cerrada; la anterior sigue abierta pero no se toca.
    abierta = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=25), bd.ahora - timedelta(minutes=10))
    bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=15), bd.ahora - timedelta(minutes=5), cierre=True)
    latir(cliente, cierre_energia())
    assert abierta["CierreExplicito"] is False and abierta["FinalSesion"] == bd.ahora - timedelta(minutes=10)


def test_cierre_energia_token_invalido_401(cliente, bd):
    assert latir(cliente, cierre_energia("malo")).status_code == 401
    assert bd.llamadas_latido == []


@pytest.mark.parametrize("hace_s, inserta", [(30, False), (59, False), (61, True), (600, True)])
def test_latido_energia_despues_del_cierre(cliente, bd, hace_s, inserta):
    # Cerrada hace menos de 60 s: es un latido que venía en camino y se ignora. Después crea una sesión nueva.
    cerrada = bd.ahora - timedelta(seconds=hace_s)
    fila = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=20), cerrada, cierre=True)
    assert latir(cliente, energia()).status_code == 204
    assert fila["FinalSesion"] == cerrada
    assert len(bd.accesos) == (2 if inserta else 1)
    if inserta:
        assert bd.accesos[1]["Fecha"] == bd.ahora and bd.accesos[1]["CierreExplicito"] is False


def test_latido_energia_ultima_cerrada_y_anterior_abierta_crea_fila_nueva(cliente, bd):
    abierta = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=25), bd.ahora - timedelta(minutes=10))
    bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=15), bd.ahora - timedelta(minutes=5), cierre=True)
    latir(cliente, energia())
    assert abierta["FinalSesion"] == bd.ahora - timedelta(minutes=10)  # la fila vieja no se extiende
    assert len(bd.accesos) == 3 and bd.accesos[2]["Fecha"] == bd.ahora


@pytest.mark.parametrize("cierre", [None, "true", "false", 1, 0, [], {}, 1.0])
@pytest.mark.parametrize("cuerpo", [mirastock, energia])
def test_cierre_de_tipo_invalido_400(cliente, bd, cuerpo, cierre):
    resp = latir(cliente, {**cuerpo(), "cierre": cierre})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "El campo «cierre» debe ser true o false."}
    assert bd.llamadas_latido == []


def test_cierre_false_es_un_latido_normal(cliente, bd):
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=5))
    assert latir(cliente, {**mirastock(), "cierre": False}).status_code == 204
    assert bd.llamadas_latido == [("mirastock", LLAVE)]
    assert bd.sesiones_agente[LLAVE]["CierreExplicito"] is False


def test_cierre_error_de_bd_503(cliente, monkeypatch):
    def falla(llave):
        raise pyodbc.OperationalError("08S01", "Sin conexión")

    monkeypatch.setattr(db, "cierre_mirastock", falla)
    assert latir(cliente, cierre_mirastock()).status_code == 503


# ---------------------------------------------------------------------------
# Energía por llave (v10): {"tipo": "energia", "t": <guid>}
# ---------------------------------------------------------------------------

def energia_llave(llave=LLAVE, **extra):
    return {"tipo": "energia", "t": llave, **extra}


def fila_llave(bd, hace_min=10, final_sesion=None, **kwargs):
    kwargs.setdefault("token", LLAVE)
    return bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=hace_min), final_sesion, **kwargs)


def test_energia_llave_actualiza_final_de_sesion(cliente, bd):
    fila = fila_llave(bd)
    resp = latir(cliente, energia_llave())
    assert resp.status_code == 204 and resp.content == b""
    assert fila["FinalSesion"] == bd.ahora and fila["CierreExplicito"] is False
    assert bd.llamadas_latido == [("energia_llave", LLAVE)]


def test_energia_llave_cierre_por_sendbeacon_text_plain(cliente, bd):
    fila = fila_llave(bd)
    resp = cliente.post(RUTA, content=json.dumps(energia_llave(cierre=True)),
                        headers={"Content-Type": "text/plain;charset=UTF-8", "Origin": ORIGEN_ENERGIA})
    assert resp.status_code == 204
    assert resp.headers["access-control-allow-origin"] == ORIGEN_ENERGIA
    assert fila["CierreExplicito"] is True


def test_energia_llave_guid_se_normaliza(cliente, bd):
    assert latir(cliente, energia_llave("{" + LLAVE.upper() + "}")).status_code == 204
    assert bd.llamadas_latido == [("energia_llave", LLAVE)]


@pytest.mark.parametrize("hace_s, actualiza", [(30, False), (59, False), (61, True), (600, True)])
def test_energia_llave_regla_de_60_segundos(cliente, bd, hace_s, actualiza):
    anterior = bd.ahora - timedelta(seconds=hace_s)
    fila = fila_llave(bd, final_sesion=anterior)
    assert latir(cliente, energia_llave()).status_code == 204
    assert fila["FinalSesion"] == (bd.ahora if actualiza else anterior)


def test_energia_llave_no_toca_sesion_cerrada(cliente, bd):
    cerrada = bd.ahora - timedelta(minutes=5)
    fila = fila_llave(bd, final_sesion=cerrada, cierre=True)
    assert latir(cliente, energia_llave()).status_code == 204
    assert latir(cliente, energia_llave(cierre=True)).status_code == 204
    assert fila["FinalSesion"] == cerrada and len(bd.accesos) == 1


def test_energia_llave_sin_fila_no_inserta(cliente, bd):
    assert latir(cliente, energia_llave()).status_code == 204
    assert latir(cliente, energia_llave(cierre=True)).status_code == 204
    assert bd.accesos == []


def test_energia_llave_no_toca_filas_sin_llave_del_mismo_correo(cliente, bd):
    # Con «t» solo cuenta la llave: un ingreso reciente sin llave (modo token) no se toca ni se inserta otro.
    otra = bd.agregar_fila_acceso(CORREO, bd.ahora - timedelta(minutes=5))
    latir(cliente, energia_llave())
    assert bd.accesos == [otra] and otra["FinalSesion"] is None


@pytest.mark.parametrize("cambio", [
    {"hace_min": 12 * 60 + 1},                          # creada hace más de 12 h
    {"portal": "MiraStock"},
    {"resultado": "Denegado"},
    {"token": "00000000-0000-0000-0000-000000000000"},  # otra llave
])
def test_energia_llave_ignora_filas_que_no_corresponden(cliente, bd, cambio):
    fila = fila_llave(bd, **cambio)
    latir(cliente, energia_llave())
    latir(cliente, energia_llave(cierre=True))
    assert fila["FinalSesion"] is None and fila["CierreExplicito"] is False


def test_energia_llave_cierre_sin_regla_de_60_segundos(cliente, bd):
    fila = fila_llave(bd, final_sesion=bd.ahora - timedelta(seconds=10))
    assert latir(cliente, energia_llave(cierre=True)).status_code == 204
    assert fila["FinalSesion"] == bd.ahora and fila["CierreExplicito"] is True
    assert bd.llamadas_latido == [("cierre_energia_llave", LLAVE)]


def test_energia_llave_latido_despues_del_cierre_no_cambia_final(cliente, bd):
    fila = fila_llave(bd)
    latir(cliente, energia_llave(cierre=True))
    cerrada = bd.ahora
    bd.ahora += timedelta(minutes=5)
    latir(cliente, energia_llave())
    assert fila["FinalSesion"] == cerrada and len(bd.accesos) == 1


@pytest.mark.parametrize("llave", ["", "abc", LLAVE + "0", 123, None, [LLAVE], {"a": 1}])
def test_energia_llave_invalida_400(cliente, bd, llave):
    resp = latir(cliente, energia_llave(llave))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "La llave de sesión no es válida."}
    assert bd.llamadas_latido == []


@pytest.mark.parametrize("cuerpo", [
    {"tipo": "energia", "t": LLAVE, "token": "x"},
    {"tipo": "energia", "t": LLAVE, "token": None},
    {"tipo": "energia"},
    {"tipo": "energia", "cierre": True},
])
def test_energia_llave_y_token_juntos_o_ninguno_400(cliente, bd, cuerpo):
    resp = latir(cliente, cuerpo)
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Envía la llave (t) o el token, no ambos."}
    assert bd.llamadas_latido == []


def test_energia_llave_cierre_de_tipo_invalido_400(cliente, bd):
    resp = latir(cliente, energia_llave(cierre=1))
    assert resp.status_code == 400 and bd.llamadas_latido == []


def test_energia_modo_token_sigue_igual(cliente, bd):
    assert latir(cliente, energia()).status_code == 204
    assert latir(cliente, cierre_energia()).status_code == 204
    assert bd.llamadas_latido == [("energia", CORREO), ("cierre_energia", CORREO)]


def test_energia_llave_error_de_bd_503(cliente, monkeypatch):
    def falla(llave):
        raise pyodbc.OperationalError("08S01", "Sin conexión")

    monkeypatch.setattr(db, "latido_energia_llave", falla)
    assert latir(cliente, energia_llave()).status_code == 503


def test_energia_llave_no_va_al_log(cliente, bd, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    latir(cliente, energia_llave())

    def falla(llave):
        raise pyodbc.OperationalError("08S01", "Sin conexión")

    monkeypatch.setattr(db, "cierre_energia_llave", falla)
    latir(cliente, energia_llave(cierre=True))
    texto = caplog.text + " ".join(str(r.args) for r in caplog.records)
    assert LLAVE not in texto


@pytest.mark.parametrize("rowcount, esperado", [(1, True), (0, False)])
def test_db_latido_energia_llave_sql(cursor_latido, rowcount, esperado):
    cursor_latido["cursor"] = cur = CursorLatido(rowcount=rowcount)
    assert db.latido_energia_llave(LLAVE) is esperado
    [(sql, params)] = cur.ejecutados
    assert params == (LLAVE,) and sql.count("?") == 1
    assert sql.startswith("UPDATE core.HistorialAccesos SET FinalSesion = SYSUTCDATETIME()")
    assert ("WHERE Token = ? AND Portal = N'Energía' AND Resultado = N'OK'"
            " AND Fecha >= DATEADD(HOUR, -12, SYSUTCDATETIME())") in sql
    assert "AND COALESCE(CierreExplicito, 0) = 0" in sql
    assert "(FinalSesion IS NULL OR FinalSesion < DATEADD(SECOND, -60, SYSUTCDATETIME()))" in sql
    assert "CierreExplicito = 1" not in sql and "INSERT" not in sql


@pytest.mark.parametrize("rowcount, esperado", [(1, True), (0, False)])
def test_db_cierre_energia_llave_sql(cursor_latido, rowcount, esperado):
    cursor_latido["cursor"] = cur = CursorLatido(rowcount=rowcount)
    assert db.cierre_energia_llave(LLAVE) is esperado
    [(sql, params)] = cur.ejecutados
    assert params == (LLAVE,) and sql.count("?") == 1
    assert sql.startswith("UPDATE core.HistorialAccesos SET FinalSesion = SYSUTCDATETIME(), CierreExplicito = 1")
    assert ("WHERE Token = ? AND Portal = N'Energía' AND Resultado = N'OK'"
            " AND Fecha >= DATEADD(HOUR, -12, SYSUTCDATETIME())"
            " AND COALESCE(CierreExplicito, 0) = 0") in sql
    assert "SECOND, -60" not in sql and "INSERT" not in sql
