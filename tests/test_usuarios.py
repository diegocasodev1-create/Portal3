"""API de usuarios: validaciones, reglas de negocio y correo."""

import httpx
import pyodbc
import pytest

from app import db, externalid, mailer
from tests.conftest import ADMIN, CSRF


def nuevo(**cambios):
    datos = {
        "correo": "juan.perez@ejemplo.com", "nombre": "Juan", "apellido": "Pérez",
        "gerencia": "Gerencia Comercial", "portal1": True, "portal2": False, "portal3": False,
    }
    datos.update(cambios)
    return datos


def editar(**cambios):
    datos = nuevo(**cambios)
    datos.pop("correo")
    return datos


# --- listar / gerencias ---

def test_listar_usuarios(cliente_admin, bd):
    bd.agregar("otro@ejemplo.com", p1=True)
    lista = cliente_admin.get("/api/usuarios").json()
    assert [u["Correo"] for u in lista] == ["otro@ejemplo.com", ADMIN]
    assert set(lista[0]) == {
        "Id", "Correo", "Nombre", "Apellido", "Gerencia", "Portal1", "Portal2", "Portal3",
        "Activo", "InvitacionEnviada", "FechaAlta",
    }


def test_gerencias(cliente_admin):
    assert cliente_admin.get("/api/gerencias").json() == [
        "Gerencia Comercial", "Gerencia TI", "Gerencia de Operaciones",
    ]


# --- crear ---

def test_crear_solo_inserta(cliente_admin, bd):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    cuerpo = resp.json()
    assert set(cuerpo) == {"usuario", "mensaje", "avisoCuenta"}
    assert cuerpo["mensaje"] == "Usuario creado."
    assert cuerpo["avisoCuenta"] is False
    assert cuerpo["usuario"]["InvitacionEnviada"] is False
    assert cuerpo["usuario"]["Activo"] is True
    assert bd.usuarios[cuerpo["usuario"]["Id"]]["InvitacionEnviada"] is False


def test_crear_no_llama_al_mailer(cliente_admin, bd, envios):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    assert envios["enviados"] == []
    assert bd.usuarios[resp.json()["usuario"]["Id"]]["InvitacionEnviada"] is False


def test_correo_se_normaliza(cliente_admin, bd):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(correo="  Juan.PEREZ@Ejemplo.COM "), headers=CSRF)
    assert resp.json()["usuario"]["Correo"] == "juan.perez@ejemplo.com"


def test_correo_duplicado_409(cliente_admin):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(correo="ADMIN@ejemplo.com"), headers=CSRF)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Ese correo ya está registrado."


def test_correo_duplicado_por_indice_unico_409(cliente_admin, monkeypatch):
    # Carrera: la verificación previa pasa, pero el INSERT choca con UQ_UsuariosEntel_Correo.
    monkeypatch.setattr(db, "existe_correo", lambda correo: False)
    resp = cliente_admin.post("/api/usuarios", json=nuevo(correo=ADMIN), headers=CSRF)
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "cambios,campo,mensaje",
    [
        ({"correo": ""}, "correo", "El correo es obligatorio."),
        ({"correo": "sin-arroba"}, "correo", "El correo no tiene un formato válido."),
        ({"correo": "a@b"}, "correo", "El correo no tiene un formato válido."),
        ({"correo": "con espacio@ejemplo.com"}, "correo", "El correo no tiene un formato válido."),
        ({"nombre": "   "}, "nombre", "El nombre es obligatorio."),
        ({"nombre": "x" * 101}, "nombre", "El nombre no puede superar 100 caracteres."),
        ({"apellido": "x" * 101}, "apellido", "El apellido no puede superar 100 caracteres."),
        ({"gerencia": ""}, "gerencia", "La gerencia es obligatoria."),
        ({"gerencia": "Gerencia Inventada"}, "gerencia", "La gerencia seleccionada no es válida."),
        ({"portal1": False, "portal2": False, "portal3": False}, "portales", "Debes marcar al menos un portal."),
    ],
)
def test_validaciones_al_crear(cliente_admin, bd, cambios, campo, mensaje):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(**cambios), headers=CSRF)
    assert resp.status_code == 422
    cuerpo = resp.json()
    assert cuerpo["detail"] == mensaje
    assert cuerpo["errores"][campo] == mensaje
    assert len(bd.usuarios) == 1


def test_apellido_es_opcional(cliente_admin):
    datos = nuevo()
    del datos["apellido"]
    resp = cliente_admin.post("/api/usuarios", json=datos, headers=CSRF)
    assert resp.status_code == 201
    assert resp.json()["usuario"]["Apellido"] == ""


def test_se_pueden_marcar_los_tres_portales(cliente_admin):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(portal2=True, portal3=True), headers=CSRF)
    u = resp.json()["usuario"]
    assert (u["Portal1"], u["Portal2"], u["Portal3"]) == (True, True, True)


def test_gerencia_se_guarda_con_el_valor_exacto_de_la_bd(cliente_admin):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(gerencia="gerencia comercial"), headers=CSRF)
    assert resp.json()["usuario"]["Gerencia"] == "Gerencia Comercial"


def test_json_invalido(cliente_admin):
    resp = cliente_admin.post(
        "/api/usuarios", content="{no es json", headers={**CSRF, "Content-Type": "application/json"}
    )
    assert resp.status_code == 422
    assert "JSON" in resp.json()["detail"]


# --- editar ---

def test_editar_usuario(cliente_admin, bd):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.put(f"/api/usuarios/{u['Id']}", json=editar(nombre="Pedro", portal2=True), headers=CSRF)
    assert resp.status_code == 200
    assert resp.json()["usuario"]["Nombre"] == "Pedro"
    assert bd.usuarios[u["Id"]]["Portal2"] is True


def test_editar_no_cambia_el_correo(cliente_admin, bd):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    cliente_admin.put(f"/api/usuarios/{u['Id']}", json=nuevo(correo="cambiado@ejemplo.com"), headers=CSRF)
    assert bd.usuarios[u["Id"]]["Correo"] == "otro@ejemplo.com"


def test_editar_sin_portales_422(cliente_admin, bd):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.put(
        f"/api/usuarios/{u['Id']}", json=editar(portal1=False, portal2=False, portal3=False), headers=CSRF
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Debes marcar al menos un portal."
    assert bd.usuarios[u["Id"]]["Portal1"] is True


def test_editar_gerencia_invalida_422(cliente_admin, bd):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.put(f"/api/usuarios/{u['Id']}", json=editar(gerencia="No existe"), headers=CSRF)
    assert resp.status_code == 422


def test_admin_no_puede_quitarse_portal3(cliente_admin, bd):
    resp = cliente_admin.put("/api/usuarios/1", json=editar(portal1=True, portal3=False), headers=CSRF)
    assert resp.status_code == 400
    assert "propio acceso" in resp.json()["detail"]
    assert bd.usuarios[1]["Portal3"] is True


def test_admin_puede_editar_sus_otros_datos(cliente_admin, bd):
    resp = cliente_admin.put("/api/usuarios/1", json=editar(nombre="Ana María", portal3=True), headers=CSRF)
    assert resp.status_code == 200
    assert bd.usuarios[1]["Nombre"] == "Ana María"


def test_admin_puede_quitar_portal3_a_otro(cliente_admin, bd):
    u = bd.agregar("otro.admin@ejemplo.com", p3=True)
    resp = cliente_admin.put(f"/api/usuarios/{u['Id']}", json=editar(portal1=True, portal3=False), headers=CSRF)
    assert resp.status_code == 200
    assert bd.usuarios[u["Id"]]["Portal3"] is False


def test_editar_inexistente_404(cliente_admin):
    resp = cliente_admin.put("/api/usuarios/999", json=editar(), headers=CSRF)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Usuario no encontrado."


# --- eliminar ---

def test_eliminar_usuario(cliente_admin, bd):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.delete(f"/api/usuarios/{u['Id']}", headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert u["Id"] not in bd.usuarios


def test_admin_no_puede_eliminarse(cliente_admin, bd):
    resp = cliente_admin.delete("/api/usuarios/1", headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No puedes eliminar tu propio usuario."
    assert 1 in bd.usuarios


def test_eliminar_inexistente_404(cliente_admin):
    resp = cliente_admin.delete("/api/usuarios/999", headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 404


# --- enviar correo (primer envío y reenvío) ---

def test_enviar_correo_exitoso_marca_invitacion(cliente_admin, bd, envios):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 200
    assert resp.json() == {"correoEnviado": True, "mensaje": "Correo enviado a otro@ejemplo.com."}
    assert envios["enviados"] == ["otro@ejemplo.com"]
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is True


def test_reenviar_correo_ya_enviado(cliente_admin, bd, envios):
    u = bd.agregar("otro@ejemplo.com", p1=True, invitacion=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 200
    assert envios["enviados"] == ["otro@ejemplo.com"]
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is True


def test_enviar_correo_fallido_no_marca_y_responde_502(cliente_admin, bd, envios):
    envios["resultado"] = mailer.ResultadoEnvio(False, "Microsoft Graph respondió 403 (ErrorAccessDenied)")
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 502
    assert resp.json() == {"detail": "No se pudo enviar el correo: Microsoft Graph respondió 403 (ErrorAccessDenied)"}
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is False


def test_enviar_correo_fallido_no_desmarca_un_envio_anterior(cliente_admin, bd, envios):
    envios["resultado"] = mailer.ResultadoEnvio(False, "No se pudo conectar con Microsoft Graph")
    u = bd.agregar("otro@ejemplo.com", p1=True, invitacion=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 502
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is True


def test_enviar_correo_con_mail_deshabilitado_503(cliente_admin, bd):
    # Sin el fixture `envios`: usa el mailer real, que con MAIL_ENABLED=false no envía.
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "No se pudo enviar el correo: Envío de correo deshabilitado"}
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is False


def test_enviar_correo_error_inesperado_502(cliente_admin, bd, monkeypatch):
    def explota(usuario):
        raise RuntimeError("fallo")

    monkeypatch.setattr(mailer, "enviar_bienvenida", explota)
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 502
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is False


def test_enviar_correo_inexistente_404(cliente_admin, envios):
    assert cliente_admin.post("/api/usuarios/999/enviar-correo", json={}, headers=CSRF).status_code == 404
    assert envios["enviados"] == []


def test_ruta_reenviar_antigua_ya_no_existe(cliente_admin, bd, envios):
    resp = cliente_admin.post("/api/usuarios/1/reenviar", json={}, headers=CSRF)
    assert resp.status_code == 404
    assert envios["enviados"] == []


# --- cuenta de acceso en External ID ---

BORRAR = {**CSRF, "Content-Type": "application/json"}


def test_crear_crea_la_cuenta_de_acceso(cliente_admin, bd, cuentas):
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    assert resp.json()["mensaje"] == "Usuario creado."
    assert resp.json()["avisoCuenta"] is False
    assert cuentas.cuentas["juan.perez@ejemplo.com"] == {
        "id": "id-juan.perez@ejemplo.com", "nombre": "Juan", "apellido": "Pérez",
    }


def test_crear_con_cuenta_ya_existente_no_la_duplica(cliente_admin, bd, cuentas):
    cuentas.cuentas["juan.perez@ejemplo.com"] = {"id": "previa", "nombre": "Juan", "apellido": "Pérez"}
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    assert resp.json()["avisoCuenta"] is False
    assert cuentas.cuentas["juan.perez@ejemplo.com"]["id"] == "previa"
    assert len(cuentas.cuentas) == 1


def test_crear_con_cuenta_antigua_con_contrasena_no_crea_otra(cliente_admin, bd, cuentas):
    cuentas.cuentas["juan.perez@ejemplo.com"] = {"id": "antigua", "nombre": "Juan", "apellido": "Pérez",
                                                "contrasena": True}
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    assert len(cuentas.cuentas) == 1
    assert cuentas.cuentas["juan.perez@ejemplo.com"]["id"] == "antigua"


def test_crear_con_fallo_de_graph_no_revierte_el_insert(cliente_admin, bd, cuentas):
    cuentas.fallar["asegurar"] = "Microsoft Graph respondió 403 (Authorization_RequestDenied)"
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    cuerpo = resp.json()
    assert cuerpo["mensaje"] == (
        "Usuario creado, pero no se pudo crear su cuenta de acceso: "
        "Microsoft Graph respondió 403 (Authorization_RequestDenied). Se reintentará al enviar el correo."
    )
    assert cuerpo["avisoCuenta"] is True
    assert bd.usuarios[cuerpo["usuario"]["Id"]]["Correo"] == "juan.perez@ejemplo.com"


def test_crear_con_error_inesperado_en_external_id_no_revierte(cliente_admin, bd, monkeypatch):
    def explota(*a):
        raise RuntimeError("fallo")

    monkeypatch.setattr(externalid, "asegurar", explota)
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    assert "error inesperado" in resp.json()["mensaje"]
    assert bd.existe_correo("juan.perez@ejemplo.com")


def test_enviar_correo_asegura_la_cuenta_antes(cliente_admin, bd, envios, cuentas):
    u = bd.agregar("otro@ejemplo.com", "Otro", "Usuario", p1=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 200
    assert "otro@ejemplo.com" in cuentas.cuentas
    assert envios["enviados"] == ["otro@ejemplo.com"]


def test_enviar_correo_si_falla_la_cuenta_502_y_no_envia(cliente_admin, bd, envios, cuentas):
    cuentas.fallar["asegurar"] = "No se pudo conectar con Microsoft Graph"
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 502
    assert resp.json() == {"detail": "No se pudo crear la cuenta de acceso: No se pudo conectar con Microsoft Graph"}
    assert envios["enviados"] == []
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is False


def test_enviar_correo_con_cuenta_antigua_con_contrasena_409_y_no_envia(cliente_admin, bd, envios, cuentas):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    cuentas.cuentas["otro@ejemplo.com"] = {"id": "antigua", "nombre": "Nombre", "apellido": "", "contrasena": True}
    resp = cliente_admin.post(f"/api/usuarios/{u['Id']}/enviar-correo", json={}, headers=CSRF)
    assert resp.status_code == 409
    assert resp.json() == {"detail": "La cuenta de acceso es antigua (con contraseña): elimínala y vuelve a intentar"}
    assert envios["enviados"] == []
    assert bd.usuarios[u["Id"]]["InvitacionEnviada"] is False
    assert len(cuentas.cuentas) == 1  # no se creó otra


def test_editar_nombre_actualiza_la_cuenta(cliente_admin, bd, cuentas):
    u = bd.agregar("otro@ejemplo.com", "Juan", "Pérez", p1=True)
    cuentas.cuentas["otro@ejemplo.com"] = {"id": "x", "nombre": "Juan", "apellido": "Pérez"}
    resp = cliente_admin.put(f"/api/usuarios/{u['Id']}", json=editar(nombre="Pedro", apellido="Soto"), headers=CSRF)
    assert resp.status_code == 200
    assert resp.json()["avisoCuenta"] is False
    assert cuentas.cuentas["otro@ejemplo.com"] == {"id": "x", "nombre": "Pedro", "apellido": "Soto"}


def test_editar_sin_cambio_de_nombre_no_llama_a_external_id(cliente_admin, bd, cuentas):
    u = bd.agregar("otro@ejemplo.com", "Juan", "Pérez", p1=True)
    resp = cliente_admin.put(f"/api/usuarios/{u['Id']}", json=editar(portal2=True), headers=CSRF)
    assert resp.status_code == 200
    assert cuentas.llamadas == []


def test_editar_nombre_con_fallo_guarda_igual_y_avisa(cliente_admin, bd, cuentas):
    cuentas.fallar["actualizar_nombre"] = "Microsoft Graph respondió 500"
    u = bd.agregar("otro@ejemplo.com", "Juan", "Pérez", p1=True)
    resp = cliente_admin.put(f"/api/usuarios/{u['Id']}", json=editar(nombre="Pedro"), headers=CSRF)
    assert resp.status_code == 200
    assert resp.json()["avisoCuenta"] is True
    assert resp.json()["mensaje"] == (
        "Usuario actualizado, pero no se pudo actualizar el nombre en su cuenta de acceso: "
        "Microsoft Graph respondió 500."
    )
    assert bd.usuarios[u["Id"]]["Nombre"] == "Pedro"


def test_eliminar_borra_la_cuenta(cliente_admin, bd, cuentas):
    u = bd.agregar("otro@ejemplo.com", p1=True)
    cuentas.cuentas["otro@ejemplo.com"] = {"id": "x", "nombre": "Nombre", "apellido": ""}
    resp = cliente_admin.delete(f"/api/usuarios/{u['Id']}", headers=BORRAR)
    assert resp.status_code == 200
    assert resp.json() == {"mensaje": "Usuario eliminado", "avisoCuenta": False}
    assert "otro@ejemplo.com" not in cuentas.cuentas


def test_eliminar_con_fallo_de_la_cuenta_borra_en_sql_y_avisa(cliente_admin, bd, cuentas):
    cuentas.fallar["eliminar"] = "Microsoft Graph respondió 403 (Authorization_RequestDenied)"
    u = bd.agregar("otro@ejemplo.com", p1=True)
    resp = cliente_admin.delete(f"/api/usuarios/{u['Id']}", headers=BORRAR)
    assert resp.status_code == 200
    assert resp.json() == {
        "mensaje": "Usuario eliminado, pero no se pudo eliminar su cuenta de acceso: "
                   "Microsoft Graph respondió 403 (Authorization_RequestDenied).",
        "avisoCuenta": True,
    }
    assert u["Id"] not in bd.usuarios


def test_admin_que_no_puede_eliminarse_no_toca_la_cuenta(cliente_admin, bd, cuentas):
    assert cliente_admin.delete("/api/usuarios/1", headers=BORRAR).status_code == 400
    assert cuentas.llamadas == []


def test_external_id_deshabilitado_no_llama_a_graph(cliente_admin, bd, envios, monkeypatch):
    # Sin el fixture `cuentas`: usa el módulo real, que con EXTID_ENABLED=false no hace nada.
    def no_llamar(*a, **k):
        raise AssertionError("no debería llamar a Graph")

    monkeypatch.setattr(httpx, "request", no_llamar)
    resp = cliente_admin.post("/api/usuarios", json=nuevo(), headers=CSRF)
    assert resp.status_code == 201
    assert resp.json()["mensaje"] == "Usuario creado."
    uid = resp.json()["usuario"]["Id"]
    assert cliente_admin.put(f"/api/usuarios/{uid}", json=editar(nombre="Pedro"), headers=CSRF).json()["avisoCuenta"] is False
    assert cliente_admin.post(f"/api/usuarios/{uid}/enviar-correo", json={}, headers=CSRF).status_code == 200
    assert cliente_admin.delete(f"/api/usuarios/{uid}", headers=BORRAR).json()["avisoCuenta"] is False


# --- errores de infraestructura ---

def test_error_de_bd_responde_503_en_espanol(cliente_admin, monkeypatch):
    def falla():
        raise pyodbc.OperationalError("08001", "sin conexión")

    monkeypatch.setattr(db, "listar_usuarios", falla)
    resp = cliente_admin.get("/api/usuarios")
    assert resp.status_code == 503
    assert resp.json()["detail"].startswith("No se pudo conectar con la base de datos")


def test_ruta_inexistente_404_en_espanol(cliente):
    resp = cliente.get("/api/no-existe")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "No encontrado."}
