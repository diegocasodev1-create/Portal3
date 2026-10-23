"""AUTH_ENABLED: con false la app funciona sin sesión; con true se comporta como siempre."""

from app import auth
from tests.conftest import ADMIN, CSRF, crear_token
from tests.test_usuarios import editar, nuevo

JSON_CSRF = {**CSRF, "Content-Type": "application/json"}


# --- AUTH_ENABLED=false ---

def test_inicio_muestra_la_app_sin_sesion(cliente_sin_auth):
    resp = cliente_sin_auth.get("/")
    assert resp.status_code == 200
    assert '<script src="/static/app.js"' in resp.text
    assert 'id="tabla-cuerpo"' in resp.text
    assert "Ingresa desde el Portal Corporativo" not in resp.text


def test_api_usuarios_responde_sin_sesion(cliente_sin_auth, bd):
    bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_sin_auth.get("/api/usuarios")
    assert resp.status_code == 200
    assert [u["Correo"] for u in resp.json()] == ["otro@ejemplo.com", ADMIN]


def test_api_me_indica_auth_desactivada(cliente_sin_auth):
    resp = cliente_sin_auth.get("/api/me")
    assert resp.status_code == 200
    assert resp.json() == {"correo": None, "authEnabled": False}


def test_no_revisa_portal3_en_la_bd(cliente_sin_auth, bd, monkeypatch):
    llamadas = []
    monkeypatch.setattr("app.db.es_admin", lambda correo: llamadas.append(correo) or False)
    assert cliente_sin_auth.get("/api/gerencias").status_code == 200
    assert llamadas == []


def test_crear_editar_y_eliminar_sin_sesion(cliente_sin_auth, bd):
    resp = cliente_sin_auth.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    uid = resp.json()["usuario"]["Id"]
    resp = cliente_sin_auth.put(f"/api/usuarios/{uid}", json=editar(nombre="Juan Carlos"), headers=CSRF)
    assert resp.status_code == 200
    assert bd.usuarios[uid]["Nombre"] == "Juan Carlos"
    assert cliente_sin_auth.delete(f"/api/usuarios/{uid}", headers=JSON_CSRF).status_code == 200
    assert uid not in bd.usuarios


def test_reglas_del_propio_admin_no_aplican(cliente_sin_auth, bd):
    # Aunque haya una cookie válida del admin, se ignora: no hay usuario identificado.
    cliente_sin_auth.cookies.set(
        auth.COOKIE_SESION, auth._serializador().dumps({"correo": ADMIN}), domain="testserver.local"
    )
    resp = cliente_sin_auth.put("/api/usuarios/1", json=editar(portal1=True, portal3=False), headers=CSRF)
    assert resp.status_code == 200
    assert bd.usuarios[1]["Portal3"] is False
    assert cliente_sin_auth.delete("/api/usuarios/1", headers=JSON_CSRF).status_code == 200
    assert 1 not in bd.usuarios


def test_no_renueva_ni_crea_cookie(cliente_sin_auth):
    resp = cliente_sin_auth.get("/api/me")
    assert auth.COOKIE_SESION not in resp.headers.get("set-cookie", "")


def test_csrf_se_mantiene(cliente_sin_auth, bd):
    resp = cliente_sin_auth.post("/api/usuarios", json=nuevo())
    assert resp.status_code == 403
    resp = cliente_sin_auth.post(
        "/api/usuarios", content="{}", headers={**CSRF, "Content-Type": "text/plain"}
    )
    assert resp.status_code == 403
    assert len(bd.usuarios) == 1


def test_headers_de_seguridad_se_mantienen(cliente_sin_auth):
    for ruta in ("/", "/api/me"):
        resp = cliente_sin_auth.get(ruta)
        assert "script-src 'self'" in resp.headers["content-security-policy"]
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "no-referrer"


# --- AUTH_ENABLED=true (valor por defecto): igual que antes ---

def test_con_auth_inicio_sin_sesion_pide_ingresar(cliente):
    resp = cliente.get("/")
    assert resp.status_code == 200
    assert "Ingresa desde el Portal Corporativo" in resp.text


def test_con_auth_api_sin_sesion_401(cliente):
    assert cliente.get("/api/usuarios").status_code == 401
    assert cliente.get("/api/me").status_code == 401


def test_con_auth_api_me_mantiene_su_respuesta(cliente):
    assert cliente.post("/auth/portal", data={"token": crear_token()}, follow_redirects=False).status_code == 303
    assert cliente.get("/api/me").json() == {"correo": ADMIN}


def test_con_auth_reglas_del_propio_admin_aplican(cliente_admin, bd):
    resp = cliente_admin.put("/api/usuarios/1", json=editar(portal1=True, portal3=False), headers=CSRF)
    assert resp.status_code == 400
    assert cliente_admin.delete("/api/usuarios/1", headers=JSON_CSRF).status_code == 400
