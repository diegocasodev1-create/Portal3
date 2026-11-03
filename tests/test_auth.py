"""Sesión propia (v12): redirecciones de las páginas, 401 de la API, cookie y cierre de sesión."""

import time
from unittest.mock import patch

import pyodbc
import pytest

from app import auth, claves, db
from tests.conftest import ADMIN, CLAVE_ADMIN, CSRF, ingresar

PAGINAS = ["/", "/contactos", "/historial", "/estadisticas", "/administradores"]
APIS = [
    "/api/me", "/api/usuarios", "/api/gerencias", "/api/historial", "/api/historial/resumen",
    "/api/estadisticas/portales", "/api/administradores",
]


def test_health_es_publico(cliente):
    resp = cliente.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- sin sesión ---

@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_sin_sesion_redirigen_al_login(cliente, ruta):
    resp = cliente.get(ruta, follow_redirects=False)
    assert resp.status_code == 303
    esperado = "/login" if ruta == "/" else f"/login?siguiente={ruta}"
    assert resp.headers["location"] == esperado


@pytest.mark.parametrize("ruta", APIS)
def test_api_sin_sesion_401(cliente, ruta):
    resp = cliente.get(ruta)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Tu sesión venció o no es válida. Vuelve a ingresar."


@pytest.mark.parametrize("metodo, ruta", [
    ("POST", "/api/usuarios"), ("PUT", "/api/usuarios/1"), ("DELETE", "/api/usuarios/1"),
    ("POST", "/api/usuarios/1/enviar-correo"), ("POST", "/api/administradores/1/verificar"),
    ("PUT", "/api/administradores/1"), ("POST", "/api/auth/cambiar-contrasena"),
])
def test_api_de_escritura_sin_sesion_401(cliente, bd, metodo, ruta):
    # La sesión se revisa antes que el body: aunque los datos sean inválidos, responde 401.
    assert cliente.request(metodo, ruta, json={}, headers=CSRF).status_code == 401
    assert 1 in bd.usuarios


def test_login_es_publico(cliente):
    resp = cliente.get("/login")
    assert resp.status_code == 200
    assert 'id="form-ingreso"' in resp.text
    assert '<script src="/static/login.js?v=14"' in resp.text


def test_cambiar_contrasena_sin_sesion_redirige(cliente):
    resp = cliente.get("/cambiar-contrasena", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_ruta_antigua_auth_portal_ya_no_existe(cliente):
    assert cliente.post("/auth/portal", data={"token": "x"}).status_code in (404, 405)
    assert cliente.post("/auth/logout", json={}, headers=CSRF).status_code in (404, 405)


# --- con sesión ---

@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_con_sesion(cliente_admin, ruta):
    resp = cliente_admin.get(ruta)
    assert resp.status_code == 200
    assert 'id="admin-nombre"' in resp.text
    assert 'id="btn-logout"' in resp.text
    assert 'href="/login"' in resp.text  # aviso de sesión vencida
    assert "PORTAL_URL" not in resp.text and "Volver al portal" not in resp.text


def test_login_con_sesion_va_al_inicio(cliente_admin):
    resp = cliente_admin.get("/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_api_me(cliente_admin):
    assert cliente_admin.get("/api/me").json() == {
        "id": 1, "nombre": "Ana Admin", "correo": ADMIN, "debeCambiarContrasena": False,
    }


def test_sesion_se_renueva_en_cada_request(cliente_admin):
    resp = cliente_admin.get("/api/me")
    assert auth.COOKIE_SESION in resp.headers.get("set-cookie", "")


def test_cookie_de_sesion_tiene_los_atributos_seguros(cliente, bd):
    resp = ingresar(cliente)
    cookie = resp.headers["set-cookie"].lower()
    assert auth.COOKIE_SESION in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "max-age=3600" in cookie


def test_cookie_no_trae_el_correo_ni_el_hash(cliente, bd):
    valor = ingresar(cliente).cookies[auth.COOKIE_SESION]
    datos = auth._serializador().loads(valor)
    assert set(datos) == {"id", "h"}
    assert datos["id"] == 1
    assert bd.admins[1]["ContrasenaHash"].hex() not in datos["h"]


def test_sesion_vencida_por_inactividad(cliente, bd):
    ahora = time.time()
    with patch("time.time", return_value=ahora - 61 * 60):
        valor = auth._serializador().dumps(auth.datos_sesion(bd.admins[1]))
    cliente.cookies.set(auth.COOKIE_SESION, valor, domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


def test_cookie_manipulada_no_sirve(cliente):
    cliente.cookies.set(auth.COOKIE_SESION, "eyJpZCI6MX0.falsa.firma", domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


def test_cookie_antigua_con_correo_no_sirve(cliente, bd):
    # Formato de v11 ({"correo": ...}): ya no identifica a nadie.
    cliente.cookies.set(auth.COOKIE_SESION, auth._serializador().dumps({"correo": ADMIN}),
                        domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


@pytest.mark.parametrize("datos", [{"id": True, "h": "x"}, {"id": "1", "h": "x"}, {"id": 1}, ["id", 1]])
def test_cookie_con_datos_raros_no_sirve(cliente, bd, datos):
    cliente.cookies.set(auth.COOKIE_SESION, auth._serializador().dumps(datos), domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


def test_admin_desactivado_corta_en_el_momento(cliente_admin, bd):
    assert cliente_admin.get("/api/usuarios").status_code == 200
    bd.admins[1]["Activo"] = False
    assert cliente_admin.get("/api/usuarios").status_code == 401
    resp = cliente_admin.get("/contactos", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?siguiente=/contactos"
    assert 'mira_admin_sesion=""' in resp.headers["set-cookie"]  # se borra la cookie


def test_admin_eliminado_corta_en_el_momento(cliente_admin, bd):
    del bd.admins[1]
    assert cliente_admin.get("/api/me").status_code == 401


def test_contrasena_restablecida_por_sql_cierra_las_sesiones(cliente_admin, bd):
    # sp_RestablecerContrasenaAdmin: sal y hash nuevos → la huella de la cookie ya no coincide.
    sal = b"\x07" * 32
    bd.admins[1].update(ContrasenaSal=sal, ContrasenaHash=claves.calcular("SHA2_512", "Admin@123456", sal),
                        AlgoritmoHash="SHA2_512", DebeCambiarContrasena=True)
    assert cliente_admin.get("/api/me").status_code == 401


def test_sesion_de_un_admin_no_sirve_para_otro(cliente, bd):
    otro = bd.agregar_admin("otro@ejemplo.com", "Otro")
    datos = {"id": otro, "h": auth.huella(bd.admins[1]["ContrasenaHash"])}
    cliente.cookies.set(auth.COOKIE_SESION, auth._serializador().dumps(datos), domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


def test_pagina_con_error_de_bd_503(cliente_admin, monkeypatch):
    def falla(aid):
        raise pyodbc.Error("08001", "sin conexión")

    monkeypatch.setattr(db, "obtener_admin", falla)
    resp = cliente_admin.get("/contactos")
    assert resp.status_code == 503
    assert "No se pudo verificar tu acceso" in resp.text
    assert 'href="/login"' in resp.text


def test_api_con_error_de_bd_503(cliente_admin, monkeypatch):
    def falla(aid):
        raise pyodbc.Error("08001", "sin conexión")

    monkeypatch.setattr(db, "obtener_admin", falla)
    assert cliente_admin.get("/api/usuarios").status_code == 503


# --- cierre de sesión ---

def test_logout_borra_la_sesion(cliente_admin):
    resp = cliente_admin.post("/api/auth/logout", json={}, headers=CSRF)
    assert resp.status_code == 200
    assert resp.json() == {"redirect": "/login"}
    assert cliente_admin.get("/api/me").status_code == 401


def test_logout_exige_csrf(cliente_admin):
    assert cliente_admin.post("/api/auth/logout", json={}).status_code == 403
    assert cliente_admin.get("/api/me").status_code == 200


def test_logout_sin_sesion_responde_igual(cliente):
    assert cliente.post("/api/auth/logout", json={}, headers=CSRF).status_code == 200


# --- seguridad general ---

def test_headers_de_seguridad(cliente):
    for ruta in ("/login", "/health", "/api/me"):
        resp = cliente.get(ruta)
        csp = resp.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "no-referrer"
        assert resp.headers["cache-control"] == "no-store"


def test_paginas_nuevas_sin_scripts_ni_estilos_inline(cliente_admin, cliente):
    for ruta in ("/administradores", "/cambiar-contrasena"):
        texto = cliente_admin.get(ruta).text
        assert "<script>" not in texto and "style=" not in texto and "onclick" not in texto
    texto = cliente.get("/login").text
    assert "<script>" not in texto and "style=" not in texto


def test_log_no_contiene_contrasena_ni_correo(cliente, bd, caplog):
    with caplog.at_level("DEBUG"):
        ingresar(cliente)
        ingresar(cliente, contrasena="Incorrecta#2026")
        ingresar(cliente, correo="nadie@ejemplo.com", contrasena="OtraMas#2026")
    texto = caplog.text
    assert CLAVE_ADMIN not in texto and "Incorrecta#2026" not in texto and "OtraMas#2026" not in texto
    assert ADMIN not in texto and "nadie@ejemplo.com" not in texto
    assert "Ingreso aceptado (administrador Id=1)" in texto
    assert "Ingreso rechazado: correo desconocido" in texto


# --- botón «ojo» para mostrar u ocultar contraseñas (lo agrega comun.js en cada input[type="password"]) ---

@pytest.mark.parametrize("ruta, propio, campos", [
    ("/login", "login.js", 1),
    ("/cambiar-contrasena", "cambiar.js", 3),
    ("/administradores", "administradores.js", 3),  # card + nueva + confirmación de la ficha
])
def test_paginas_con_contrasenas_cargan_comun_js_primero(cliente, bd, ruta, propio, campos):
    if ruta != "/login":
        from tests.conftest import poner_sesion
        poner_sesion(cliente, bd.admins[1])
    texto = cliente.get(ruta).text
    comun = texto.index('<script src="/static/comun.js?v=14" defer></script>')
    assert comun < texto.index(f'<script src="/static/{propio}?v=14" defer></script>')
    assert texto.count('type="password"') == campos


def test_boton_ojo_en_comun_js_y_estilos():
    from pathlib import Path

    static = Path(__file__).resolve().parent.parent / "app" / "static"
    js = (static / "comun.js").read_text(encoding="utf-8")
    for marca in ('input[type="password"]', '"Mostrar contraseña"', '"Ocultar contraseña"', '"aria-pressed"',
                  'type: "button"', "setSelectionRange", 'addEventListener("submit"', "ocultarClaves(modalActivo)"):
        assert marca in js
    css = (static / "styles.css").read_text(encoding="utf-8")
    assert ".campo-clave input { padding-right: 48px; }" in css
    assert '.btn-ojo[aria-pressed="true"] .ojo-tachado' in css
