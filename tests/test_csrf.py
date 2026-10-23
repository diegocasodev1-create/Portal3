"""Protección CSRF de /api/*."""

import pytest

from tests.conftest import CSRF

DATOS = {"correo": "nuevo@ejemplo.com", "nombre": "Nuevo", "gerencia": "Gerencia TI", "portal1": True}


@pytest.mark.parametrize(
    "metodo,ruta",
    [("post", "/api/usuarios"), ("put", "/api/usuarios/1"), ("delete", "/api/usuarios/1"),
     ("post", "/api/usuarios/1/enviar-correo")],
)
def test_sin_header_x_requested_with_rechaza(cliente_admin, bd, metodo, ruta):
    resp = cliente_admin.request(metodo.upper(), ruta, json=DATOS)
    assert resp.status_code == 403
    assert 1 in bd.usuarios  # no se tocó nada


def test_header_con_valor_incorrecto_rechaza(cliente_admin):
    resp = cliente_admin.post("/api/usuarios", json=DATOS, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 403


def test_formulario_en_vez_de_json_rechaza(cliente_admin, bd):
    resp = cliente_admin.post("/api/usuarios", data=DATOS, headers=CSRF)
    assert resp.status_code == 403
    assert not bd.existe_correo("nuevo@ejemplo.com")


def test_text_plain_rechaza(cliente_admin):
    resp = cliente_admin.post(
        "/api/usuarios", content='{"correo":"x@y.com"}', headers={**CSRF, "Content-Type": "text/plain"}
    )
    assert resp.status_code == 403


def test_get_no_exige_header(cliente_admin):
    assert cliente_admin.get("/api/usuarios").status_code == 200


def test_con_headers_correctos_pasa(cliente_admin, envios):
    assert cliente_admin.post("/api/usuarios", json=DATOS, headers=CSRF).status_code == 201
