"""Centro de administración principal (/administradores, v12): lista, verificación por card y ficha."""

import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth, claves
from app.main import app
from tests.conftest import ADMIN, CLAVE_ADMIN, CSRF, ingresar, poner_sesion

CLAVE_OTRO = "Otra#Clave2026"
NUEVA = "Nueva#Clave2026"


@pytest.fixture
def otro(bd):
    """Segundo administrador activo (Id 2)."""
    return bd.agregar_admin("otro@miragroup.cl", "Bruno Otro", CLAVE_OTRO, ultimo_acceso=bd.ahora - timedelta(days=1))


def verificar(cliente, aid, contrasena):
    return cliente.post(f"/api/administradores/{aid}/verificar", json={"contrasena": contrasena}, headers=CSRF)


def editar(cliente, aid, permiso, **datos):
    cuerpo = {"permiso": permiso, "nombre": "Bruno Otro", "correo": "otro@miragroup.cl", **datos}
    return cliente.put(f"/api/administradores/{aid}", json=cuerpo, headers=CSRF)


def permiso_de(cliente, aid, contrasena):
    resp = verificar(cliente, aid, contrasena)
    assert resp.status_code == 200, resp.json()
    return resp.json()["permiso"]


# ---------------------------------------------------------------------------
# Página y lista
# ---------------------------------------------------------------------------

def test_pagina(cliente_admin):
    resp = cliente_admin.get("/administradores")
    assert resp.status_code == 200
    for marca in ('id="lista-admins"', 'id="modal-verificar"', 'id="modal-ficha"', 'id="reglas"',
                  '<script src="/static/comun.js?v=18"', '<script src="/static/administradores.js?v=18"'):
        assert marca in resp.text


def test_lista_de_administradores(cliente_admin, bd, otro):
    bd.agregar_admin("bloq@miragroup.cl", "Carla Bloqueada", bloqueado_hasta=bd.ahora + timedelta(minutes=5))
    bd.agregar_admin("inac@miragroup.cl", "Diego Inactivo", activo=False)
    lista = cliente_admin.get("/api/administradores").json()
    assert [a["nombre"] for a in lista] == ["Ana Admin", "Bruno Otro", "Carla Bloqueada", "Diego Inactivo"]
    assert lista[0] == {
        "id": 1, "nombre": "Ana Admin", "correo": ADMIN, "ultimoAcceso": None, "estado": "activo",
        "bloqueadoHasta": None, "esYo": True,
    }
    assert lista[1]["ultimoAcceso"] == "2026-10-27T15:00:00Z" and lista[1]["esYo"] is False
    assert lista[2]["estado"] == "bloqueado" and lista[2]["bloqueadoHasta"] == "2026-10-28T15:05:00Z"
    assert lista[3]["estado"] == "inactivo"


def test_lista_no_expone_hash_ni_sal(cliente_admin, bd):
    texto = cliente_admin.get("/api/administradores").text
    assert "Contrasena" not in texto and "Sal" not in texto and "Algoritmo" not in texto
    assert bd.admins[1]["ContrasenaHash"].hex() not in texto


def test_bloqueo_vencido_se_muestra_activo(cliente_admin, bd, otro):
    bd.admins[otro]["BloqueadoHasta"] = bd.ahora - timedelta(minutes=1)
    estado = {a["id"]: a for a in cliente_admin.get("/api/administradores").json()}[otro]
    assert estado["estado"] == "activo" and estado["bloqueadoHasta"] is None


# ---------------------------------------------------------------------------
# Verificación en la card
# ---------------------------------------------------------------------------

def test_verificar_entrega_permiso(cliente_admin, bd, otro):
    bd.admins[otro]["IntentosFallidos"] = 2
    resp = verificar(cliente_admin, otro, CLAVE_OTRO)
    assert resp.status_code == 200
    datos = resp.json()
    assert datos["expiraEnSeg"] == 300
    assert datos["administrador"] == {"id": otro, "nombre": "Bruno Otro", "correo": "otro@miragroup.cl"}
    assert isinstance(datos["permiso"], str) and datos["permiso"]
    assert bd.admins[otro]["IntentosFallidos"] == 0
    assert bd.admins[otro]["UltimoAcceso"] == bd.ahora - timedelta(days=1)  # no es un ingreso


def test_verificar_contrasena_incorrecta_suma_al_bloqueo_de_ese_admin(cliente_admin, bd, otro):
    for i in range(5):
        resp = verificar(cliente_admin, otro, "Mala#Clave2026")
        assert resp.status_code == 422
        assert resp.json()["errores"] == {"contrasena": "La contraseña no es correcta."}
    assert bd.admins[otro]["BloqueadoHasta"] == bd.ahora + timedelta(minutes=15)
    assert bd.admins[1]["IntentosFallidos"] == 0  # el que hace los intentos no se ve afectado
    resp = verificar(cliente_admin, otro, CLAVE_OTRO)
    assert resp.status_code == 423
    assert bd.admins[otro]["IntentosFallidos"] == 5
    # Bloqueado también para el login.
    with TestClient(app, base_url="https://testserver") as c:
        assert ingresar(c, "otro@miragroup.cl", CLAVE_OTRO).status_code == 401


def test_verificar_vacia_no_suma(cliente_admin, bd, otro):
    resp = verificar(cliente_admin, otro, "")
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"contrasena": "Ingresa la contraseña."}
    assert bd.admins[otro]["IntentosFallidos"] == 0


def test_verificar_inactivo_403_e_inexistente_404(cliente_admin, bd):
    inactivo = bd.agregar_admin("inac@miragroup.cl", "Inactivo", activo=False)
    assert verificar(cliente_admin, inactivo, CLAVE_ADMIN).status_code == 403
    assert verificar(cliente_admin, 999, CLAVE_ADMIN).status_code == 404


def test_verificar_con_contrasena_por_defecto_vencida(cliente_admin, bd):
    aid = bd.agregar_admin("nuevo@miragroup.cl", "Nuevo", "Admin@123456", algoritmo="SHA2_512",
                           debe_cambiar=True, fecha_alta=bd.ahora - timedelta(hours=80))
    resp = verificar(cliente_admin, aid, "Admin@123456")
    assert resp.status_code == 422
    assert "venció" in resp.json()["errores"]["contrasena"]


def test_verificar_respeta_el_limite_por_ip(cliente_admin, otro):
    for _ in range(20):
        verificar(cliente_admin, otro, "Mala#Clave2026")
    assert verificar(cliente_admin, otro, CLAVE_OTRO).status_code == 429


def test_verificar_propia_card_que_migra_el_hash_mantiene_la_sesion(cliente, bd):
    aid = bd.agregar_admin("sql@miragroup.cl", "Desde SQL", "Propia#Clave2026", algoritmo="SHA2_512")
    poner_sesion(cliente, bd.admins[aid])
    resp = verificar(cliente, aid, "Propia#Clave2026")
    assert resp.status_code == 200
    assert bd.admins[aid]["AlgoritmoHash"] == "PBKDF2_SHA256"
    assert auth.COOKIE_SESION in resp.cookies
    assert cliente.get("/api/me").status_code == 200
    assert editar(cliente, aid, resp.json()["permiso"], nombre="SQL", correo="sql@miragroup.cl").status_code == 200


# ---------------------------------------------------------------------------
# Ficha: el permiso
# ---------------------------------------------------------------------------

def test_editar_sin_permiso_403(cliente_admin, bd, otro):
    for permiso in ("", "basura", None, 123):
        resp = editar(cliente_admin, otro, permiso, nombre="Hackeado")
        assert resp.status_code == 403
        assert resp.json()["permisoVencido"] is True
    assert bd.admins[otro]["Nombre"] == "Bruno Otro"


def test_permiso_atado_al_admin_verificado(cliente_admin, bd, otro):
    tercero = bd.agregar_admin("tercero@miragroup.cl", "Tercero", "Tercera#Clave2026")
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    resp = editar(cliente_admin, tercero, permiso, nombre="X", correo="tercero@miragroup.cl")
    assert resp.status_code == 403
    assert bd.admins[tercero]["Nombre"] == "Tercero"


def test_permiso_atado_a_la_sesion(cliente_admin, bd, otro):
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    tercero = bd.agregar_admin("tercero@miragroup.cl", "Tercero", "Tercera#Clave2026")
    with TestClient(app, base_url="https://testserver") as c:
        poner_sesion(c, bd.admins[tercero])
        assert editar(c, otro, permiso, nombre="Robado").status_code == 403
    assert bd.admins[otro]["Nombre"] == "Bruno Otro"


def test_permiso_vence_a_los_5_minutos(cliente_admin, bd, otro):
    ahora = time.time()
    with patch("time.time", return_value=ahora - 301):
        permiso = auth.crear_permiso(bd.admins[otro], 1)
    assert editar(cliente_admin, otro, permiso).status_code == 403
    with patch("time.time", return_value=ahora - 290):
        permiso = auth.crear_permiso(bd.admins[otro], 1)
    assert editar(cliente_admin, otro, permiso).status_code == 200


def test_permiso_deja_de_valer_si_cambia_la_contrasena(cliente_admin, bd, otro):
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    h, s, a = claves.nuevo_hash("Restablecida#2026")
    bd.cambiar_contrasena_admin(otro, h, s, a)
    assert editar(cliente_admin, otro, permiso).status_code == 403


def test_permiso_firmado_con_otra_sal_no_sirve(cliente_admin, bd, otro):
    # Una cookie de sesión no sirve como permiso (y viceversa): las sales son distintas.
    falso = auth._serializador().dumps({"d": otro, "p": 1, "h": auth.huella(bd.admins[otro]["ContrasenaHash"])})
    assert editar(cliente_admin, otro, falso).status_code == 403


def test_permiso_no_sirve_como_cookie_de_sesion(cliente, bd, otro):
    with TestClient(app, base_url="https://testserver") as admin:
        poner_sesion(admin, bd.admins[1])
        permiso = permiso_de(admin, otro, CLAVE_OTRO)
    cliente.cookies.set(auth.COOKIE_SESION, permiso, domain="testserver.local", path="/")
    assert cliente.get("/api/me").status_code == 401


# ---------------------------------------------------------------------------
# Ficha: nombre, correo y contraseña
# ---------------------------------------------------------------------------

def test_editar_nombre_y_correo(cliente_admin, bd, otro):
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    resp = editar(cliente_admin, otro, permiso, nombre="  Bruno Nuevo ", correo=" Bruno.Nuevo@MiraGroup.cl ")
    assert resp.status_code == 200
    assert resp.json()["mensaje"] == "Administrador actualizado."
    assert resp.json()["administrador"]["correo"] == "bruno.nuevo@miragroup.cl"
    assert (bd.admins[otro]["Nombre"], bd.admins[otro]["Correo"]) == ("Bruno Nuevo", "bruno.nuevo@miragroup.cl")
    # La contraseña no cambió y el permiso sigue sirviendo para otro guardado dentro de los 5 minutos.
    assert claves.verificar("PBKDF2_SHA256", CLAVE_OTRO, bd.admins[otro]["ContrasenaSal"], bd.admins[otro]["ContrasenaHash"])
    assert editar(cliente_admin, otro, permiso, nombre="B", correo="bruno.nuevo@miragroup.cl").status_code == 200


def test_editar_correo_duplicado_409(cliente_admin, bd, otro):
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    resp = editar(cliente_admin, otro, permiso, correo=ADMIN)
    assert resp.status_code == 409
    assert resp.json()["errores"] == {"correo": "Ese correo ya pertenece a otro administrador."}


@pytest.mark.parametrize("cambios, campo", [
    ({"nombre": ""}, "nombre"), ({"nombre": "x" * 151}, "nombre"),
    ({"correo": ""}, "correo"), ({"correo": "no-es-correo"}, "correo"),
])
def test_editar_validaciones(cliente_admin, bd, otro, cambios, campo):
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    resp = editar(cliente_admin, otro, permiso, **cambios)
    assert resp.status_code == 422
    assert campo in resp.json()["errores"]


def test_editar_contrasena_cierra_las_sesiones_de_ese_admin(cliente_admin, bd, otro):
    with TestClient(app, base_url="https://testserver") as sesion_del_otro:
        poner_sesion(sesion_del_otro, bd.admins[otro])
        permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
        resp = editar(cliente_admin, otro, permiso, nuevaContrasena=NUEVA, confirmacion=NUEVA)
        assert resp.status_code == 200
        assert "sus otras sesiones se cerraron" in resp.json()["mensaje"]
        a = bd.admins[otro]
        assert a["AlgoritmoHash"] == "PBKDF2_SHA256" and a["DebeCambiarContrasena"] is False
        assert claves.verificar(a["AlgoritmoHash"], NUEVA, a["ContrasenaSal"], a["ContrasenaHash"])
        assert sesion_del_otro.get("/api/me").status_code == 401
    assert cliente_admin.get("/api/me").status_code == 200  # quien editó sigue conectado


def test_editar_su_propia_contrasena_sigue_conectado(cliente_admin, bd):
    permiso = permiso_de(cliente_admin, 1, CLAVE_ADMIN)
    resp = editar(cliente_admin, 1, permiso, nombre="Ana Admin", correo=ADMIN, nuevaContrasena=NUEVA, confirmacion=NUEVA)
    assert resp.status_code == 200
    assert cliente_admin.get("/api/me").status_code == 200
    cliente_admin.cookies.clear()
    assert ingresar(cliente_admin, contrasena=NUEVA).status_code == 200


@pytest.mark.parametrize("nueva, confirmacion, errores", [
    ("Corta#1", "Corta#1", {"nuevaContrasena": "La contraseña debe tener al menos 10 caracteres."}),
    ("Admin@123456", "Admin@123456", {"nuevaContrasena": "No puedes usar la contraseña por defecto."}),
    (NUEVA, "Distinta#2026", {"confirmacion": "Las contraseñas no coinciden."}),
    ("", NUEVA, {"nuevaContrasena": "La contraseña debe tener al menos 10 caracteres.",
                 "confirmacion": "Las contraseñas no coinciden."}),
    (CLAVE_OTRO, CLAVE_OTRO, {"nuevaContrasena": "La contraseña nueva debe ser distinta de la actual."}),
])
def test_editar_contrasena_politica(cliente_admin, bd, otro, nueva, confirmacion, errores):
    hash_antes = bd.admins[otro]["ContrasenaHash"]
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    resp = editar(cliente_admin, otro, permiso, nombre="No Cambia", nuevaContrasena=nueva, confirmacion=confirmacion)
    assert resp.status_code == 422
    assert resp.json()["errores"] == errores
    assert bd.admins[otro]["ContrasenaHash"] == hash_antes
    assert bd.admins[otro]["Nombre"] == "Bruno Otro"


def test_editar_admin_desactivado_entre_medio_403(cliente_admin, bd, otro):
    permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
    bd.admins[otro]["Activo"] = False
    assert editar(cliente_admin, otro, permiso).status_code == 403


def test_admin_que_debe_cambiar_no_usa_el_centro(cliente, bd, otro):
    aid = bd.agregar_admin("nuevo@miragroup.cl", "Nuevo", "Admin@123456", algoritmo="SHA2_512", debe_cambiar=True)
    poner_sesion(cliente, bd.admins[aid])
    assert cliente.get("/api/administradores").json()["cambioRequerido"] is True
    assert verificar(cliente, otro, CLAVE_OTRO).status_code == 403
    assert bd.admins[otro]["IntentosFallidos"] == 0


def test_log_de_la_card_sin_contrasenas_ni_correos(cliente_admin, bd, otro, caplog):
    with caplog.at_level("INFO"):
        verificar(cliente_admin, otro, "Mala#Clave2026")
        permiso = permiso_de(cliente_admin, otro, CLAVE_OTRO)
        editar(cliente_admin, otro, permiso, nuevaContrasena=NUEVA, confirmacion=NUEVA)
    texto = caplog.text
    for secreto in ("Mala#Clave2026", CLAVE_OTRO, NUEVA, "otro@miragroup.cl", permiso):
        assert secreto not in texto
    assert f"Permiso de edición entregado (administrador Id={otro}, por Id=1)" in texto
