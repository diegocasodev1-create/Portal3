"""Cuentas de acceso al portal en Microsoft Entra External ID (tenant "MiraGroup Externos").

Graph con msal (client credentials). La cuenta se crea con la misma identidad que deja el autoregistro
con código por correo: {"signInType": "federated", "issuer": "mail", "issuerAssignedId": correo}, sin
contraseña. Así el usuario entra SOLO con código. Una identidad "emailAddress" del dominio del tenant es
una cuenta local con contraseña (formato antiguo de esta app): el portal le pide contraseña.

Con EXTID_ENABLED=false ninguna función llama a Graph: solo lo registran en DEBUG.
Los errores se informan con ErrorExternalId(motivo), con un motivo en español apto para el usuario.
"""

import logging
import threading
from dataclasses import dataclass

import httpx
import msal

from app.config import get_settings

log = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]

# Issuer de las identidades de código por correo (autoregistro con código de un solo uso).
ISSUER_CODIGO = "mail"

# Tipos de cuenta encontrada.
TIPO_CODIGO = "codigo"  # federated / mail: entra solo con código
TIPO_CONTRASENA = "contrasena"  # emailAddress del dominio: cuenta antigua con contraseña

# Estados que devuelve asegurar().
CREADA = "creada"
EXISTE_CODIGO = "existe_codigo"
EXISTE_CONTRASENA = "existe_contrasena"


class ErrorExternalId(Exception):
    """No se pudo completar la operación en External ID. `motivo` es apto para mostrar."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Cuenta:
    id: str
    tipo: str  # TIPO_CODIGO o TIPO_CONTRASENA


_app_msal: msal.ConfidentialClientApplication | None = None
_lock = threading.Lock()


def habilitado() -> bool:
    return get_settings().extid_enabled


def verificar_configuracion() -> None:
    """Lanza ErrorExternalId si External ID está deshabilitado o le faltan datos."""
    s = get_settings()
    if not s.extid_enabled:
        raise ErrorExternalId("External ID está deshabilitado (EXTID_ENABLED=false)")
    if not (s.extid_tenant_id and s.extid_client_id and s.extid_domain and s.extid_client_secret.get_secret_value()):
        raise ErrorExternalId("Faltan las credenciales de External ID en la configuración")


def _cliente_msal() -> msal.ConfidentialClientApplication:
    global _app_msal
    with _lock:
        if _app_msal is None:
            s = get_settings()
            _app_msal = msal.ConfidentialClientApplication(
                s.extid_client_id,
                authority=f"https://login.microsoftonline.com/{s.extid_tenant_id}",
                client_credential=s.extid_client_secret.get_secret_value(),
            )
        return _app_msal


def _token() -> str:
    verificar_configuracion()
    try:
        token = _cliente_msal().acquire_token_for_client(scopes=_SCOPE)
    except Exception as e:
        log.error("Error al obtener el token de External ID: %s", type(e).__name__)
        raise ErrorExternalId("No se pudo autenticar con Microsoft Graph (External ID)") from None
    if "access_token" not in token:
        log.error("External ID no entregó token: %s", token.get("error"))
        raise ErrorExternalId(
            f"No se pudo autenticar con Microsoft Graph ({token.get('error', 'error desconocido')})"
        )
    return token["access_token"]


def _graph(metodo: str, ruta: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {_token()}"}
    try:
        return httpx.request(metodo, f"{_GRAPH}{ruta}", headers=headers, timeout=20, **kwargs)
    except httpx.HTTPError as e:
        log.error("Error de red con Graph (External ID): %s", type(e).__name__)
        raise ErrorExternalId("No se pudo conectar con Microsoft Graph") from None


def _codigo_error(resp: httpx.Response) -> str:
    try:
        return resp.json().get("error", {}).get("code", "") or ""
    except ValueError:
        return ""


def _error_graph(resp: httpx.Response, operacion: str, cuerpo_en_log: bool = False) -> ErrorExternalId:
    codigo = _codigo_error(resp)
    if cuerpo_en_log:
        # Respuesta completa de Graph (código, mensaje, request-id). No contiene tokens ni secretos.
        log.error("Graph rechazó %s en External ID: HTTP %s %s", operacion, resp.status_code, resp.text)
    else:
        log.error("Graph rechazó %s en External ID: HTTP %s %s", operacion, resp.status_code, codigo)
    return ErrorExternalId(f"Microsoft Graph respondió {resp.status_code}{f' ({codigo})' if codigo else ''}")


def _escapar(valor: str) -> str:
    return valor.replace("'", "''")


def _usuarios_con_identidad(correo: str, issuer: str) -> list[dict]:
    filtro = "identities/any(c:c/issuerAssignedId eq '{0}' and c/issuer eq '{1}')".format(
        _escapar(correo), _escapar(issuer)
    )
    resp = _graph("GET", "/users", params={"$filter": filtro, "$select": "id,identities"})
    if resp.status_code != 200:
        raise _error_graph(resp, "la búsqueda")
    try:
        return resp.json().get("value", [])
    except ValueError:
        raise ErrorExternalId("Microsoft Graph entregó una respuesta inválida") from None


def _tipo(usuario: dict, correo: str) -> str | None:
    """Clasifica según las identidades que trae la cuenta (no según el filtro: Graph ignora el issuer
    al filtrar identidades emailAddress)."""
    correo = correo.lower()
    identidades = [i for i in usuario.get("identities") or [] if (i.get("issuerAssignedId") or "").lower() == correo]
    if any(i.get("signInType") == "federated" and i.get("issuer") == ISSUER_CODIGO for i in identidades):
        return TIPO_CODIGO
    if any(i.get("signInType") == "emailAddress" for i in identidades):
        return TIPO_CONTRASENA
    return None


def buscar_por_correo(correo: str) -> Cuenta | None:
    """Busca la cuenta de este correo: primero la de código (issuer 'mail'); si no hay, la antigua con
    contraseña (emailAddress del dominio). Devuelve None si no existe ninguna."""
    if not habilitado():
        log.debug("External ID deshabilitado: no se busca la cuenta")
        return None
    dominio = get_settings().extid_domain
    for issuer in (ISSUER_CODIGO, dominio):
        encontrados = [(u["id"], _tipo(u, correo)) for u in _usuarios_con_identidad(correo, issuer)]
        # Si hay más de una, gana la de código.
        for tipo in (TIPO_CODIGO, TIPO_CONTRASENA):
            for id_cuenta, t in encontrados:
                if t == tipo:
                    return Cuenta(id_cuenta, tipo)
    return None


def _datos_nombre(nombre: str, apellido: str) -> dict:
    return {
        "displayName": f"{nombre} {apellido}".strip(),
        "givenName": nombre,
        # Graph no acepta cadena vacía; null deja el apellido sin valor.
        "surname": apellido or None,
    }


def crear(correo: str, nombre: str, apellido: str) -> str | None:
    """Crea la cuenta para ingresar solo con código (identidad federated/mail, sin contraseña). Devuelve su id."""
    if not habilitado():
        log.debug("External ID deshabilitado: no se crea la cuenta")
        return None
    datos = {
        "accountEnabled": True,
        **_datos_nombre(nombre, apellido),
        "mail": correo,
        "identities": [{"signInType": "federated", "issuer": ISSUER_CODIGO, "issuerAssignedId": correo}],
    }
    if datos["surname"] is None:
        del datos["surname"]

    resp = _graph("POST", "/users", json=datos)
    if resp.status_code != 201:
        raise _error_graph(resp, "la creación", cuerpo_en_log=True)
    id_cuenta = resp.json()["id"]
    log.info("Cuenta de External ID creada para ingreso con código (id=%s)", id_cuenta)
    return id_cuenta


def asegurar(correo: str, nombre: str, apellido: str) -> tuple[str | None, str | None]:
    """Busca la cuenta y, si no existe ninguna, la crea. Devuelve (id, estado), con estado CREADA,
    EXISTE_CODIGO o EXISTE_CONTRASENA (cuenta antigua: no se crea otra). Deshabilitado: (None, None)."""
    if not habilitado():
        log.debug("External ID deshabilitado: no se asegura la cuenta")
        return None, None
    existente = buscar_por_correo(correo)
    if existente is None:
        return crear(correo, nombre, apellido), CREADA
    if existente.tipo == TIPO_CONTRASENA:
        log.warning(
            "La cuenta de External ID ya existe con contraseña (formato antiguo, id=%s): no se crea otra. "
            "Para que entre solo con código hay que eliminarla y volver a crearla.",
            existente.id,
        )
        return existente.id, EXISTE_CONTRASENA
    return existente.id, EXISTE_CODIGO


def actualizar_nombre(correo: str, nombre: str, apellido: str) -> bool:
    """Actualiza displayName, givenName y surname. Devuelve False si la cuenta no existe."""
    if not habilitado():
        log.debug("External ID deshabilitado: no se actualiza el nombre")
        return False
    cuenta = buscar_por_correo(correo)
    if cuenta is None:
        return False
    resp = _graph("PATCH", f"/users/{cuenta.id}", json=_datos_nombre(nombre, apellido))
    if resp.status_code != 204:
        raise _error_graph(resp, "la actualización")
    return True


def eliminar(correo: str) -> bool:
    """Elimina la cuenta (de código o antigua con contraseña). Devuelve False si no existía."""
    if not habilitado():
        log.debug("External ID deshabilitado: no se elimina la cuenta")
        return False
    cuenta = buscar_por_correo(correo)
    if cuenta is None:
        return False
    resp = _graph("DELETE", f"/users/{cuenta.id}")
    if resp.status_code == 404:
        return False
    if resp.status_code != 204:
        raise _error_graph(resp, "la eliminación")
    return True
