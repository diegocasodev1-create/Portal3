"""Identidad: validación del token del portal, sesión propia de la app y dependencia require_admin."""

import logging
import threading
import time
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.responses import Response

from app import db
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
    """El token del portal no es válido (firma, expiración, emisor, audiencia o sin correo)."""


# ---------------------------------------------------------------------------
# Clave pública del portal
# ---------------------------------------------------------------------------

class _ClavePortal:
    def __init__(self) -> None:
        self._clave = None
        self._cargada_en = 0.0
        self._lock = threading.Lock()

    def _descargar(self):
        url = f"{get_settings().portal_base_url}/_services/auth/publickey"
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


clave_portal = _ClavePortal()


def _normalizar_emisor(iss: str) -> str:
    iss = iss.strip().lower()
    for prefijo in ("https://", "http://"):
        if iss.startswith(prefijo):
            iss = iss[len(prefijo):]
    return iss.split("/", 1)[0]


def _decodificar(token: str, clave) -> dict[str, Any]:
    s = get_settings()
    opciones = {"require": ["exp", "iss"], "verify_aud": s.token_audience is not None}
    return jwt.decode(
        token,
        clave,
        algorithms=["RS256"],
        audience=s.token_audience,
        options=opciones,
        leeway=_TOLERANCIA_RELOJ_S,
    )


def validar_token_portal(token: str) -> str:
    """Valida el token del portal y devuelve el correo normalizado."""
    if not token:
        raise TokenInvalido("Token vacío")
    try:
        clave = clave_portal.obtener()
    except Exception as e:
        log.error("No se pudo obtener la clave pública del portal: %s", type(e).__name__)
        raise TokenInvalido("Clave pública no disponible") from None

    try:
        claims = _decodificar(token, clave)
    except jwt.InvalidSignatureError:
        # La clave pudo haber rotado: se recarga una vez y se reintenta.
        try:
            recargada = clave_portal.recargar()
        except Exception as e:
            log.error("No se pudo recargar la clave pública del portal: %s", type(e).__name__)
            raise TokenInvalido("Clave pública no disponible") from None
        if not recargada:
            raise TokenInvalido("Firma inválida") from None
        try:
            claims = _decodificar(token, clave_portal.obtener())
        except jwt.PyJWTError as e:
            raise TokenInvalido(type(e).__name__) from None
    except jwt.PyJWTError as e:
        raise TokenInvalido(type(e).__name__) from None

    # Solo los nombres de los claims, nunca sus valores.
    log.debug("Claims recibidos en el token del portal: %s", sorted(claims.keys()))

    if _normalizar_emisor(str(claims.get("iss", ""))) != get_settings().portal_host:
        raise TokenInvalido("Emisor no válido")

    correo = claims.get("email") or claims.get("preferred_username")
    if not isinstance(correo, str) or not correo.strip():
        raise TokenInvalido("El token no trae correo")
    return normalizar_correo(correo)


# ---------------------------------------------------------------------------
# Sesión de la app (cookie firmada, solo guarda el correo)
# ---------------------------------------------------------------------------

def _serializador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret.get_secret_value(), salt=_SAL_SESION)


def crear_cookie_sesion(response: Response, correo: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_SESION,
        _serializador().dumps({"correo": correo}),
        max_age=s.session_max_age_s,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def borrar_cookie_sesion(response: Response) -> None:
    response.delete_cookie(COOKIE_SESION, path="/", httponly=True, secure=True, samesite="lax")


def leer_sesion(request: Request) -> str | None:
    """Devuelve el correo de la sesión si la cookie es válida y no venció por inactividad."""
    valor = request.cookies.get(COOKIE_SESION)
    if not valor:
        return None
    try:
        datos = _serializador().loads(valor, max_age=get_settings().session_max_age_s)
    except BadSignature:
        return None
    correo = datos.get("correo") if isinstance(datos, dict) else None
    return correo if isinstance(correo, str) and correo else None


# ---------------------------------------------------------------------------
# Dependencia para /api/*
# ---------------------------------------------------------------------------

def require_admin(request: Request) -> str | None:
    # Con AUTH_ENABLED=false no hay usuario identificado: se permite el acceso y se devuelve None.
    if not get_settings().auth_enabled:
        return None
    correo = getattr(request.state, "correo", None)
    if not correo:
        raise HTTPException(status_code=401, detail="Tu sesión venció o no es válida. Vuelve a ingresar desde el Portal Corporativo.")
    # Se vuelve a verificar en cada request: si le quitaron el permiso, se corta en el momento.
    if not db.es_admin(correo):
        raise HTTPException(status_code=403, detail="No tienes permisos de administrador.")
    return correo
