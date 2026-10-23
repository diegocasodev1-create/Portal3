"""Entrada desde el portal, sesión y autorización."""

import time
from unittest.mock import patch

import jwt
import pytest

from app import auth
from tests.conftest import ADMIN, CSRF, OTRA_CLAVE_PRIVADA, OTRA_CLAVE_PUBLICA, CLAVE_PUBLICA, crear_token


def test_health_es_publico(cliente):
    resp = cliente.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_inicio_sin_sesion_muestra_ingresar_desde_portal(cliente):
    resp = cliente.get("/")
    assert resp.status_code == 200
    assert "Ingresa desde el Portal Corporativo" in resp.text
    assert "https://portal.ejemplo.com" in resp.text


def test_api_sin_sesion_responde_401(cliente):
    resp = cliente.get("/api/me")
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_token_valido_crea_sesion_y_redirige(cliente):
    resp = cliente.post("/auth/portal", data={"token": crear_token()}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    cookie = resp.headers["set-cookie"].lower()
    assert auth.COOKIE_SESION in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie

    assert cliente.get("/api/me").json() == {"correo": ADMIN}
    pagina = cliente.get("/")
    assert pagina.status_code == 200
    assert "Administración de usuarios" in pagina.text


def test_correo_se_normaliza_y_usa_preferred_username(cliente):
    token = crear_token(email=None, preferred_username="  ADMIN@Ejemplo.com ")
    resp = cliente.post("/auth/portal", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 303
    assert cliente.get("/api/me").json() == {"correo": ADMIN}


def test_usuario_sin_portal3_ve_sin_permisos(cliente, bd):
    bd.agregar("comun@ejemplo.com", p1=True)
    resp = cliente.post("/auth/portal", data={"token": crear_token(email="comun@ejemplo.com")}, follow_redirects=False)
    assert resp.status_code == 403
    assert "No tienes permisos de administrador" in resp.text
    assert "https://portal.ejemplo.com" in resp.text
    assert cliente.get("/api/me").status_code == 401


def test_admin_inactivo_no_entra(cliente, bd):
    bd.agregar("inactivo@ejemplo.com", p3=True, activo=False)
    resp = cliente.post("/auth/portal", data={"token": crear_token(email="inactivo@ejemplo.com")}, follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "token",
    [
        "",
        "no-es-un-jwt",
        crear_token(clave=OTRA_CLAVE_PRIVADA),                # firma de otra clave
        crear_token(exp=int(time.time()) - 3600),             # vencido
        crear_token(iss="otro-portal.ejemplo.com"),           # emisor distinto
        crear_token(iss=None),                                # sin emisor
        crear_token(email=None),                              # sin correo
    ],
    ids=["vacio", "basura", "firma", "vencido", "emisor", "sin-emisor", "sin-correo"],
)
def test_token_invalido_rechazado(cliente, token):
    resp = cliente.post("/auth/portal", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers
    assert cliente.get("/api/me").status_code == 401


def test_token_hs256_rechazado(cliente):
    # Ataque de confusión de algoritmo: firmar con HS256 usando la clave pública como secreto.
    token = jwt.encode({"iss": "portal.ejemplo.com", "exp": int(time.time()) + 600, "email": ADMIN},
                       "cualquier-secreto-de-al-menos-32-bytes!!", algorithm="HS256")
    resp = cliente.post("/auth/portal", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 401


def test_emisor_con_https_aceptado(cliente):
    token = crear_token(iss="https://portal.ejemplo.com/")
    assert cliente.post("/auth/portal", data={"token": token}, follow_redirects=False).status_code == 303


def test_clave_rotada_se_recarga_una_vez(cliente, clave_del_portal, monkeypatch):
    monkeypatch.setattr(auth, "_RECARGA_MINIMA_S", 0)
    clave_del_portal["claves"] = [CLAVE_PUBLICA, OTRA_CLAVE_PUBLICA]
    token = crear_token(clave=OTRA_CLAVE_PRIVADA)
    resp = cliente.post("/auth/portal", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 303
    assert clave_del_portal["descargas"] == 2


def test_clave_se_cachea(cliente, clave_del_portal):
    for _ in range(3):
        cliente.post("/auth/portal", data={"token": crear_token()}, follow_redirects=False)
    assert clave_del_portal["descargas"] == 1


def test_audiencia_configurada_se_exige(cliente, monkeypatch):
    monkeypatch.setattr(auth.get_settings(), "token_audience", "mira-admin")
    assert cliente.post("/auth/portal", data={"token": crear_token()}, follow_redirects=False).status_code == 401
    token = crear_token(aud="mira-admin")
    assert cliente.post("/auth/portal", data={"token": token}, follow_redirects=False).status_code == 303


def test_permiso_revocado_corta_en_el_momento(cliente_admin, bd):
    assert cliente_admin.get("/api/me").status_code == 200
    bd.usuarios[1]["Portal3"] = False
    resp = cliente_admin.get("/api/usuarios")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "No tienes permisos de administrador."


def test_sesion_se_renueva_en_cada_request(cliente_admin):
    resp = cliente_admin.get("/api/me")
    assert auth.COOKIE_SESION in resp.headers.get("set-cookie", "")


def test_sesion_reciente_es_valida(cliente, bd):
    # Control del test siguiente: la misma cookie, sin vencer, sí se acepta.
    cliente.cookies.set(auth.COOKIE_SESION, auth._serializador().dumps({"correo": ADMIN}),
                        domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 200


def test_sesion_vencida_por_inactividad(cliente, bd):
    ahora = time.time()
    with patch("time.time", return_value=ahora - 61 * 60):
        valor = auth._serializador().dumps({"correo": ADMIN})
    cliente.cookies.set(auth.COOKIE_SESION, valor, domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


def test_cookie_manipulada_no_sirve(cliente):
    cliente.cookies.set(auth.COOKIE_SESION, "eyJjb3JyZW8iOiJhZG1pbkBlamVtcGxvLmNvbSJ9.falsa.firma",
                        domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


def test_logout_borra_la_sesion(cliente_admin):
    resp = cliente_admin.post("/auth/logout", json={}, headers=CSRF)
    assert resp.status_code == 200
    assert resp.json()["redirect"] == "https://portal.ejemplo.com"
    assert cliente_admin.get("/api/me").status_code == 401


def test_headers_de_seguridad(cliente):
    for ruta in ("/", "/health", "/api/me"):
        resp = cliente.get(ruta)
        csp = resp.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "https://fonts.googleapis.com" in csp and "https://fonts.gstatic.com" in csp
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "no-referrer"


def test_log_no_contiene_token_ni_valores_de_claims(cliente, caplog):
    token = crear_token()
    with caplog.at_level("DEBUG"):
        cliente.post("/auth/portal", data={"token": token}, follow_redirects=False)
    texto = caplog.text
    assert token not in texto
    assert ADMIN not in texto
    assert "email" in texto  # se registran los nombres de los claims
