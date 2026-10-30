"""Identidad: login propio de administradores, sesión de la app, permisos de edición y tokens de Energía.

- Login con correo y contraseña contra core.AdministradoresPortal (los hash están en app/claves.py).
- La cookie firmada guarda el Id del administrador y una huella de su hash: si la contraseña cambia
  (en Portal3 o restablecida por SQL), las sesiones anteriores dejan de valer.
- Los tokens de Power Pages solo se validan para los latidos de Energía (modo token de /api/latido).
"""

import hashlib
import hmac
import logging
import threading
import time
from collections import deque
from typing import Any, Callable

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.responses import Response

from app import claves, db
from app.config import get_settings
from app.schemas import normalizar_correo

log = logging.getLogger(__name__)

COOKIE_SESION = "mira_admin_sesion"
_SAL_SESION = "mira-admin-sesion"
# Margen para diferencias de reloj entre el portal y la app.
_TOLERANCIA_RELOJ_S = 60
# Evita recargar la clave pública en cada token inválido (p. ej. ante tokens falsos repetidos).
_RECARGA_MINIMA_S = 60


class TokenInvalido(Exception):
    """El token de Energía no es válido (firma, expiración, emisor o sin correo)."""


class ClaveNoDisponible(TokenInvalido):
    """No se pudo descargar la clave pública del portal (problema nuestro o del portal, no del token)."""


# ---------------------------------------------------------------------------
# Claves públicas de los portales
# ---------------------------------------------------------------------------

class _ClavePortal:
    def __init__(self, url_base: Callable[[], str]) -> None:
        self._url_base = url_base
        self._clave = None
        self._cargada_en = 0.0
        self._lock = threading.Lock()

    def _descargar(self):
        url = f"{self._url_base()}/_services/auth/publickey"
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        return load_pem_public_key(resp.text.strip().encode())

    def obtener(self):
        with self._lock:
            if self._clave is None:
                self._clave = self._descargar()
                self._cargada_en = time.monotonic()
            return self._clave

    def recargar(self) -> bool:
        """Recarga la clave. Devuelve False si se recargó hace muy poco y no se volvió a intentar."""
        with self._lock:
            if self._clave is not None and time.monotonic() - self._cargada_en < _RECARGA_MINIMA_S:
                return False
            self._clave = self._descargar()
            self._cargada_en = time.monotonic()
            return True

    def limpiar(self) -> None:
        with self._lock:
            self._clave = None
            self._cargada_en = 0.0


# Sitio Energía (latidos de sesión en modo token).
clave_energia = _ClavePortal(lambda: get_settings().energia_portal_url)


def _normalizar_emisor(iss: str) -> str:
    iss = iss.strip().lower()
    for prefijo in ("https://", "http://"):
        if iss.startswith(prefijo):
            iss = iss[len(prefijo):]
    return iss.split("/", 1)[0]


def _decodificar(token: str, clave, audiencia: str | None) -> dict[str, Any]:
    opciones = {"require": ["exp", "iss"], "verify_aud": audiencia is not None}
    return jwt.decode(
        token,
        clave,
        algorithms=["RS256"],
        audience=audiencia,
        options=opciones,
        leeway=_TOLERANCIA_RELOJ_S,
    )


def _validar_token(token: str, clave_sitio: _ClavePortal, host_emisor: str, audiencia: str | None) -> str:
    """Valida un token de Power Pages contra la clave del sitio y devuelve el correo normalizado."""
    if not token:
        raise TokenInvalido("Token vacío")
    try:
        clave = clave_sitio.obtener()
    except Exception as e:
        log.error("No se pudo obtener la clave pública del portal: %s", type(e).__name__)
        raise ClaveNoDisponible("Clave pública no disponible") from None

    try:
        claims = _decodificar(token, clave, audiencia)
    except jwt.InvalidSignatureError:
        # La clave pudo haber rotado: se recarga una vez y se reintenta.
        try:
            recargada = clave_sitio.recargar()
        except Exception as e:
            log.error("No se pudo recargar la clave pública del portal: %s", type(e).__name__)
            raise ClaveNoDisponible("Clave pública no disponible") from None
        if not recargada:
            raise TokenInvalido("Firma inválida") from None
        try:
            claims = _decodificar(token, clave_sitio.obtener(), audiencia)
        except jwt.PyJWTError as e:
            raise TokenInvalido(type(e).__name__) from None
    except jwt.PyJWTError as e:
        raise TokenInvalido(type(e).__name__) from None

    # Solo los nombres de los claims, nunca sus valores.
    log.debug("Claims recibidos en el token: %s", sorted(claims.keys()))

    if _normalizar_emisor(str(claims.get("iss", ""))) != host_emisor:
        raise TokenInvalido("Emisor no válido")

    correo = claims.get("email") or claims.get("preferred_username")
    if not isinstance(correo, str) or not correo.strip():
        raise TokenInvalido("El token no trae correo")
    return normalizar_correo(correo)


def validar_token_energia(token: str) -> str:
    """Valida el token del sitio Energía (latidos), sin exigir audiencia."""
    return _validar_token(token, clave_energia, get_settings().energia_host, None)


# ---------------------------------------------------------------------------
# Sesión de la app (cookie firmada: Id del administrador + huella de su hash)
# ---------------------------------------------------------------------------

MSG_SESION_INVALIDA = "Tu sesión venció o no es válida. Vuelve a ingresar."
MSG_CAMBIO_REQUERIDO = "Debes cambiar tu contraseña antes de continuar."


class CambioContrasenaRequerido(Exception):
    """El administrador entró con DebeCambiarContrasena = 1: solo puede ir a /cambiar-contrasena."""


def _serializador(sal: str = _SAL_SESION) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret.get_secret_value(), salt=sal)


def huella(hash_: bytes) -> str:
    """Huella del hash de la contraseña (HMAC con SESSION_SECRET): no permite deducir el hash."""
    secreto = get_settings().session_secret.get_secret_value().encode()
    return hmac.new(secreto, b"huella-contrasena:" + hash_, hashlib.sha256).hexdigest()[:32]


def datos_sesion(admin: dict) -> dict:
    return {"id": admin["Id"], "h": huella(admin["ContrasenaHash"])}


def crear_cookie_sesion(response: Response, datos: dict) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_SESION,
        _serializador().dumps(datos),
        max_age=s.session_max_age_s,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def borrar_cookie_sesion(response: Response) -> None:
    response.delete_cookie(COOKIE_SESION, path="/", httponly=True, secure=True, samesite="lax")


def leer_sesion(request: Request) -> dict | None:
    """Devuelve {id, h} si la cookie es válida y no venció por inactividad. No consulta la BD."""
    valor = request.cookies.get(COOKIE_SESION)
    if not valor:
        return None
    try:
        datos = _serializador().loads(valor, max_age=get_settings().session_max_age_s)
    except BadSignature:
        return None
    if not isinstance(datos, dict):
        return None
    admin_id, h = datos.get("id"), datos.get("h")
    # bool es subclase de int: se descarta explícitamente.
    if type(admin_id) is not int or not isinstance(h, str) or not h:
        return None
    return {"id": admin_id, "h": h}


def admin_de_sesion(sesion: dict | None) -> dict | None:
    """El administrador de la sesión, o None si ya no existe, está inactivo o cambió su contraseña."""
    if not sesion:
        return None
    admin = db.obtener_admin(sesion["id"])
    if admin is None or not admin["Activo"]:
        return None
    if not hmac.compare_digest(huella(admin["ContrasenaHash"]), sesion["h"]):
        return None
    return admin


# ---------------------------------------------------------------------------
# Login y verificación de contraseñas
# ---------------------------------------------------------------------------

class CredencialesInvalidas(Exception):
    """Correo o contraseña incorrectos, administrador inactivo o bloqueado. El motivo es solo para el log."""


class ContrasenaPorDefectoVencida(Exception):
    """La contraseña por defecto pasó su plazo (db.HORAS_CONTRASENA_POR_DEFECTO): hay que restablecerla por SQL."""


def comprobar_contrasena(admin: dict, clave: str, es_ingreso: bool) -> dict:
    """Verifica la contraseña de un administrador activo y no bloqueado.

    Un fallo suma un intento (y puede bloquearlo). Un acierto reinicia los intentos y, si la contraseña
    ya no es la por defecto y sigue en SHA2_512, la pasa a PBKDF2. Devuelve el administrador con el hash vigente.
    """
    if not claves.verificar(admin["AlgoritmoHash"], clave, admin["ContrasenaSal"], admin["ContrasenaHash"]):
        db.registrar_fallo_admin(admin["Id"])
        raise CredencialesInvalidas(f"contraseña incorrecta (Id={admin['Id']})")
    if admin["DebeCambiarContrasena"] and admin["PorDefectoVencida"]:
        raise ContrasenaPorDefectoVencida()
    db.registrar_exito_admin(admin["Id"], es_ingreso)
    if admin["AlgoritmoHash"] == claves.ALGORITMO_SQL and not admin["DebeCambiarContrasena"]:
        hash_, sal, algoritmo = claves.nuevo_hash(clave)
        if db.migrar_hash_admin(admin["Id"], admin["ContrasenaHash"], hash_, sal, algoritmo):
            log.info("Contraseña del administrador Id=%s migrada a %s", admin["Id"], algoritmo)
            admin = {**admin, "ContrasenaHash": hash_, "ContrasenaSal": sal, "AlgoritmoHash": algoritmo}
    return admin


def autenticar(correo: str, clave: str) -> dict:
    """Login: devuelve el administrador o lanza CredencialesInvalidas / ContrasenaPorDefectoVencida."""
    admin = db.obtener_admin_por_correo(correo) if correo else None
    motivo = None
    if admin is None:
        motivo = "correo desconocido"
    elif not admin["Activo"]:
        motivo = f"administrador inactivo (Id={admin['Id']})"
    elif admin["Bloqueado"]:
        motivo = f"administrador bloqueado (Id={admin['Id']})"
    if motivo:
        # Mismo costo que una verificación real: el tiempo de respuesta no revela qué correos existen.
        claves.gastar_tiempo(clave)
        raise CredencialesInvalidas(motivo)
    return comprobar_contrasena(admin, clave, es_ingreso=True)


# ---------------------------------------------------------------------------
# Permiso de edición de /administradores (5 minutos, atado al administrador y a la sesión)
# ---------------------------------------------------------------------------

_SAL_PERMISO = "mira-admin-permiso-edicion"
DURACION_PERMISO_S = 5 * 60


def crear_permiso(destino: dict, sesion_id: int) -> str:
    return _serializador(_SAL_PERMISO).dumps(
        {"d": destino["Id"], "p": sesion_id, "h": huella(destino["ContrasenaHash"])}
    )


def permiso_valido(permiso: Any, destino: dict, sesion_id: int) -> bool:
    """El permiso debe ser de este administrador, de esta sesión y anterior a cualquier cambio de su contraseña."""
    if not isinstance(permiso, str) or not permiso:
        return False
    try:
        datos = _serializador(_SAL_PERMISO).loads(permiso, max_age=DURACION_PERMISO_S)
    except BadSignature:
        return False
    return (
        isinstance(datos, dict)
        and datos.get("d") == destino["Id"]
        and datos.get("p") == sesion_id
        and isinstance(datos.get("h"), str)
        and hmac.compare_digest(datos["h"], huella(destino["ContrasenaHash"]))
    )


# ---------------------------------------------------------------------------
# Límite simple de intentos por IP (login y verificación en las cards)
# ---------------------------------------------------------------------------

class LimitePorIp:
    """Ventana deslizante en memoria (la app corre en una sola réplica)."""

    def __init__(self, maximo: int, ventana_s: int) -> None:
        self.maximo = maximo
        self.ventana_s = ventana_s
        self._intentos: dict[str, deque] = {}
        self._lock = threading.Lock()

    def permitir(self, ip: str) -> bool:
        """Registra un intento. False si la IP ya llegó al máximo dentro de la ventana."""
        ahora = time.monotonic()
        limite = ahora - self.ventana_s
        with self._lock:
            if len(self._intentos) > 10_000:
                # Limpieza de IPs sin intentos recientes, para que el diccionario no crezca sin fin.
                for clave in [k for k, v in self._intentos.items() if not v or v[-1] < limite]:
                    del self._intentos[clave]
            cola = self._intentos.setdefault(ip, deque())
            while cola and cola[0] < limite:
                cola.popleft()
            if len(cola) >= self.maximo:
                return False
            cola.append(ahora)
            return True

    def limpiar(self) -> None:
        with self._lock:
            self._intentos.clear()


limite_intentos = LimitePorIp(maximo=20, ventana_s=15 * 60)


def ip_cliente(request: Request) -> str:
    """IP real del cliente: la última de X-Forwarded-For es la que agregó el ingress de Container Apps.

    No se usa request.client: uvicorn corre con --forwarded-allow-ips "*" y tomaría la primera,
    que el cliente puede inventar.
    """
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada.strip():
        return reenviada.split(",")[-1].strip()
    return request.client.host if request.client else "desconocida"


# ---------------------------------------------------------------------------
# Dependencias para /api/*
# ---------------------------------------------------------------------------

def require_sesion(request: Request) -> dict:
    """Administrador con sesión válida, aunque todavía deba cambiar su contraseña."""
    admin = getattr(request.state, "admin", None)
    if admin is None:
        admin = admin_de_sesion(getattr(request.state, "sesion", None))
        if admin is None:
            raise HTTPException(status_code=401, detail=MSG_SESION_INVALIDA)
        request.state.admin = admin
    return admin


def require_admin(request: Request) -> dict:
    # Se vuelve a leer en cada request: si lo desactivan o cambia su contraseña, se corta en el momento.
    admin = require_sesion(request)
    if admin["DebeCambiarContrasena"]:
        raise CambioContrasenaRequerido()
    return admin
