"""Plantilla y envío del correo de bienvenida (Graph simulado)."""

import httpx
import pytest

from app import mailer
from app.config import get_settings

USUARIO = {
    "Id": 7, "Correo": "juan@ejemplo.com", "Nombre": "Juan <b>", "Apellido": "",
    "Portal1": True, "Portal2": False, "Portal3": True,
}


def test_html_contiene_textos_y_portales():
    html = mailer.construir_html("Juan", "juan@ejemplo.com", ["Portal de Energía", "Administración de usuarios"])
    assert "Hola Juan," in html
    assert "Se te dio acceso al <strong>Portal Corporativo MiraGroup</strong>." in html
    assert "Portal de Energía" in html and "Administración de usuarios" in html
    assert "Portal MiraStock" not in html
    assert "Ingresar al portal" in html
    assert 'href="https://portal.ejemplo.com"' in html
    assert "1. Haz clic en &quot;Ingresar al portal&quot; y luego en &quot;Iniciar sesión&quot;." in html
    assert ("2. Escribe este correo: <strong style=\"color:#0a1a33;\">juan@ejemplo.com</strong> "
            "y haz clic en &quot;Siguiente&quot;.") in html
    assert ("3. Revisa tu correo: te llegará un código de verificación de Microsoft. "
            "Escríbelo en la pantalla y haz clic en &quot;Iniciar sesión&quot;.") in html
    assert "4. ¡Listo! Verás los portales que tienes habilitados." in html
    assert ("No necesitas contraseña ni crear una cuenta: tu acceso ya está creado. "
            "Cada vez que ingreses recibirás un código nuevo en tu correo.") in html
    assert "adjunt" not in html
    assert "Este es un mensaje automático, no respondas a este correo." in html
    assert "#29b8ec" in html and "#0a1a33" in html


def test_html_sin_menciones_al_flujo_antiguo():
    html = mailer.construir_html("Juan", "juan@ejemplo.com", ["Portal de Energía"])
    for texto in ("Cree una", "Ha olvidado", "Si ya tienes cuenta", "define tu contraseña", "Regístrate"):
        assert texto not in html
    # La única mención a "contraseña" es la que dice que no se necesita.
    assert html.count("contraseña") == 1


def test_html_escapa_datos():
    html = mailer.construir_html("<script>alert(1)</script>", "x@y.com", [])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_portales_habilitados():
    assert mailer.portales_habilitados(USUARIO) == ["Portal de Energía", "Administración de usuarios"]


def test_mail_deshabilitado_no_envia(monkeypatch):
    def no_llamar(*a, **k):
        raise AssertionError("no debería llamar a Graph")

    monkeypatch.setattr(httpx, "post", no_llamar)
    r = mailer.enviar_bienvenida(USUARIO)
    assert r.enviado is False
    assert r.mensaje == "Envío de correo deshabilitado"
    assert r.no_configurado is True


@pytest.fixture
def graph(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mail_enabled", True)
    monkeypatch.setattr(s, "graph_client_id", "cliente")
    monkeypatch.setattr(s, "graph_client_secret", type(s.graph_client_secret)("secreto"))

    class MsalFalso:
        def acquire_token_for_client(self, scopes):
            return {"access_token": "token-falso"}

    monkeypatch.setattr(mailer, "_cliente_msal", lambda: MsalFalso())
    llamadas = []
    estado = {"respuesta": httpx.Response(202)}

    def post(url, json, headers, timeout):
        llamadas.append({"url": url, "json": json, "headers": headers})
        return estado["respuesta"]

    monkeypatch.setattr(httpx, "post", post)
    return {"llamadas": llamadas, "estado": estado}


def test_envio_exitoso(graph):
    r = mailer.enviar_bienvenida(USUARIO)
    assert r.enviado is True
    llamada = graph["llamadas"][0]
    assert llamada["url"] == "https://graph.microsoft.com/v1.0/users/no-reply@ejemplo.com/sendMail"
    assert llamada["json"]["saveToSentItems"] is False
    msg = llamada["json"]["message"]
    assert msg["subject"] == "Tu acceso al Portal Corporativo MiraGroup"
    assert msg["toRecipients"] == [{"emailAddress": {"address": "juan@ejemplo.com"}}]
    assert msg["body"]["contentType"] == "HTML"
    assert "Juan &lt;b&gt;" in msg["body"]["content"]
    # El correo va sin adjuntos.
    assert "attachments" not in msg


def test_envio_rechazado_por_graph(graph):
    graph["estado"]["respuesta"] = httpx.Response(403, json={"error": {"code": "ErrorAccessDenied", "message": "x"}})
    r = mailer.enviar_bienvenida(USUARIO)
    assert r.enviado is False
    assert r.mensaje == "Microsoft Graph respondió 403 (ErrorAccessDenied)"
    assert r.no_configurado is False


def test_sin_credenciales_graph(monkeypatch):
    monkeypatch.setattr(get_settings(), "mail_enabled", True)
    r = mailer.enviar_bienvenida(USUARIO)
    assert r.enviado is False
    assert "credenciales" in r.mensaje
    assert r.no_configurado is True
