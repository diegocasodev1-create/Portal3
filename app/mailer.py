"""Correo de bienvenida vía Microsoft Graph (client credentials con msal)."""

import logging
import threading
from dataclasses import dataclass
from html import escape

import httpx
import msal

from app.config import get_settings

log = logging.getLogger(__name__)

ASUNTO = "Tu acceso al Portal Corporativo MiraGroup"
_SCOPE = ["https://graph.microsoft.com/.default"]

NOMBRES_PORTALES = {
    "Portal1": "Portal de Energía",
    "Portal2": "Portal MiraStock",
    "Portal3": "Administración de usuarios",
}


@dataclass
class ResultadoEnvio:
    enviado: bool
    mensaje: str
    # True cuando no se intentó enviar porque el correo está deshabilitado o sin credenciales (503);
    # False cuando se intentó y falló Graph (502).
    no_configurado: bool = False


_app_msal: msal.ConfidentialClientApplication | None = None
_lock = threading.Lock()


def _cliente_msal() -> msal.ConfidentialClientApplication:
    global _app_msal
    with _lock:
        if _app_msal is None:
            s = get_settings()
            _app_msal = msal.ConfidentialClientApplication(
                s.graph_client_id,
                authority=f"https://login.microsoftonline.com/{s.graph_tenant_id}",
                client_credential=s.graph_client_secret.get_secret_value(),
            )
        return _app_msal


def portales_habilitados(usuario: dict) -> list[str]:
    return [nombre for campo, nombre in NOMBRES_PORTALES.items() if usuario.get(campo)]


def construir_html(nombre: str, correo: str, portales: list[str]) -> str:
    portal_url = escape(get_settings().portal_base_url, quote=True)
    nombre_h = escape(nombre)
    correo_h = escape(correo)
    items = "".join(
        f'<li style="margin:0 0 6px 0;color:#0a1a33;">{escape(p)}</li>' for p in portales
    )
    fuente = "font-family:'Segoe UI',Arial,Helvetica,sans-serif;"
    paso = f'style="margin:0 0 8px 0;{fuente}font-size:15px;line-height:22px;color:#0a1a33;"'
    parrafo = f'style="margin:16px 0 0 0;{fuente}font-size:15px;line-height:22px;color:#0a1a33;"'
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(ASUNTO)}</title>
</head>
<body style="margin:0;padding:0;background-color:#f2f6fa;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f2f6fa;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background-color:#ffffff;border:1px solid #d7e3ee;border-radius:12px;">
<tr><td style="height:6px;background-color:#29b8ec;border-radius:12px 12px 0 0;font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:32px 32px 8px 32px;{fuente}">
<h1 style="margin:0 0 16px 0;{fuente}font-size:22px;line-height:28px;color:#0a1a33;">Hola {nombre_h},</h1>
<p style="margin:0 0 16px 0;{fuente}font-size:15px;line-height:22px;color:#0a1a33;">Se te dio acceso al <strong>Portal Corporativo MiraGroup</strong>. Tienes habilitados los siguientes portales:</p>
<ul style="margin:0 0 24px 0;padding:0 0 0 20px;{fuente}font-size:15px;line-height:22px;">{items}</ul>
</td></tr>
<tr><td align="center" style="padding:0 32px 24px 32px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center" bgcolor="#29b8ec" style="border-radius:24px;">
<a href="{portal_url}" target="_blank" style="display:inline-block;padding:12px 32px;{fuente}font-size:16px;font-weight:bold;color:#0a1a33;text-decoration:none;border-radius:24px;">Ingresar al portal</a>
</td></tr>
</table>
</td></tr>
<tr><td style="padding:0 32px 32px 32px;{fuente}">
<p style="margin:0 0 12px 0;{fuente}font-size:15px;line-height:22px;color:#0a1a33;"><strong>Cómo ingresar:</strong></p>
<p {paso}>1. Haz clic en &quot;Ingresar al portal&quot; y luego en &quot;Iniciar sesión&quot;.</p>
<p {paso}>2. Escribe este correo: <strong style="color:#0a1a33;">{correo_h}</strong> y haz clic en &quot;Siguiente&quot;.</p>
<p {paso}>3. Revisa tu correo: te llegará un código de verificación de Microsoft. Escríbelo en la pantalla y haz clic en &quot;Iniciar sesión&quot;.</p>
<p {paso}>4. ¡Listo! Verás los portales que tienes habilitados.</p>
<p {parrafo}>No necesitas contraseña ni crear una cuenta: tu acceso ya está creado. Cada vez que ingreses recibirás un código nuevo en tu correo.</p>
</td></tr>
<tr><td style="padding:16px 32px 24px 32px;border-top:1px solid #d7e3ee;{fuente}">
<p style="margin:0;{fuente}font-size:12px;line-height:18px;color:#5b6b80;">Este es un mensaje automático, no respondas a este correo.</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def enviar_bienvenida(usuario: dict) -> ResultadoEnvio:
    s = get_settings()
    if not s.mail_enabled:
        return ResultadoEnvio(False, "Envío de correo deshabilitado", no_configurado=True)
    if not s.graph_client_id or not s.graph_client_secret.get_secret_value():
        return ResultadoEnvio(False, "Faltan las credenciales de Microsoft Graph en la configuración", no_configurado=True)

    try:
        token = _cliente_msal().acquire_token_for_client(scopes=_SCOPE)
    except Exception as e:
        log.error("Error al obtener el token de Graph: %s", type(e).__name__)
        return ResultadoEnvio(False, "No se pudo autenticar con Microsoft Graph")
    if "access_token" not in token:
        log.error("Graph no entregó token: %s", token.get("error"))
        return ResultadoEnvio(False, f"No se pudo autenticar con Microsoft Graph ({token.get('error', 'error desconocido')})")

    correo = usuario["Correo"]
    mensaje = {
        "message": {
            "subject": ASUNTO,
            "body": {
                "contentType": "HTML",
                "content": construir_html(usuario["Nombre"], correo, portales_habilitados(usuario)),
            },
            "toRecipients": [{"emailAddress": {"address": correo}}],
        },
        "saveToSentItems": False,
    }
    try:
        resp = httpx.post(
            f"https://graph.microsoft.com/v1.0/users/{s.mail_sender}/sendMail",
            json=mensaje,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            timeout=20,
        )
    except httpx.HTTPError as e:
        log.error("Error de red al enviar correo con Graph: %s", type(e).__name__)
        return ResultadoEnvio(False, "No se pudo conectar con Microsoft Graph")

    if resp.status_code == 202:
        log.info("Correo de bienvenida enviado (usuario Id=%s)", usuario.get("Id"))
        return ResultadoEnvio(True, "Correo enviado")

    try:
        codigo = resp.json().get("error", {}).get("code", "")
    except ValueError:
        codigo = ""
    log.error("Graph rechazó el envío: HTTP %s %s", resp.status_code, codigo)
    return ResultadoEnvio(False, f"Microsoft Graph respondió {resp.status_code}{f' ({codigo})' if codigo else ''}")
