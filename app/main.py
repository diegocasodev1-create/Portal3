"""App FastAPI: middlewares de sesión y seguridad, login propio, API y archivos estáticos."""

import csv
import io
import json
import logging
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

import pyodbc
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth, claves, consulta_bd, db, externalid, mailer
from app.auth import require_admin
from app.config import get_settings
from app.schemas import (
    AdministradorEditar,
    CambioContrasena,
    Ingreso,
    UsuarioCrear,
    UsuarioEditar,
    VerificarAdministrador,
)

settings = get_settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Estas librerías pueden registrar detalles de requests en DEBUG; se limitan a WARNING.
for _ruidoso in ("msal", "httpx", "httpcore", "urllib3"):
    logging.getLogger(_ruidoso).setLevel(logging.WARNING)
log = logging.getLogger("mira_admin")

RUTA_LATIDO = "/api/latido"


class _SinLatidos(logging.Filter):
    """Saca /api/latido del access log de uvicorn: llega cada 2 minutos por usuario y llenaría Log Analytics."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Formato de uvicorn.access: (cliente, método, ruta con query, versión HTTP, status).
        args = record.args
        return not (isinstance(args, tuple) and len(args) >= 3 and str(args[2]).startswith(RUTA_LATIDO))


logging.getLogger("uvicorn.access").addFilter(_SinLatidos())

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

MSG_BD_NO_DISPONIBLE = "No se pudo verificar tu acceso en este momento. Intenta nuevamente en unos minutos."

app = FastAPI(title="Administración de usuarios - MiraGroup", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Páginas HTML simples
# ---------------------------------------------------------------------------

def _leer_plantilla(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


_INICIO_HTML = _leer_plantilla(STATIC_DIR / "inicio.html")
_CONTACTOS_HTML = _leer_plantilla(STATIC_DIR / "contactos.html")
_HISTORIAL_HTML = _leer_plantilla(STATIC_DIR / "historial.html")
_ESTADISTICAS_HTML = _leer_plantilla(STATIC_DIR / "estadisticas.html")
_ESTADISTICAS_GENERAL_HTML = _leer_plantilla(STATIC_DIR / "estadisticas-general.html")
_ESTADISTICAS_PORTAL_HTML = _leer_plantilla(STATIC_DIR / "estadisticas-portal.html")
_ADMINISTRADORES_HTML = _leer_plantilla(STATIC_DIR / "administradores.html")
_CONSULTA_BD_HTML = _leer_plantilla(STATIC_DIR / "consulta-bd.html")
_LOGIN_HTML = _leer_plantilla(STATIC_DIR / "login.html")
_CAMBIAR_HTML = _leer_plantilla(STATIC_DIR / "cambiar-contrasena.html")
_ERROR_HTML = _leer_plantilla(TEMPLATES_DIR / "error.html")


def _pagina_error(mensaje: str, status_code: int) -> HTMLResponse:
    return HTMLResponse(_ERROR_HTML.replace("{{MENSAJE}}", escape(mensaje)), status_code=status_code)


# ---------------------------------------------------------------------------
# Middlewares (el último registrado es el más externo)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def proteccion_csrf(request: Request, call_next):
    # /api/latido llega desde otros sitios, no usa cookies y lleva su autorización en el body (llave o token).
    path = request.url.path
    if path.startswith("/api/") and path != RUTA_LATIDO and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        tipo = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if tipo != "application/json" or request.headers.get("x-requested-with") != "mira-admin":
            return JSONResponse({"detail": "Solicitud rechazada por seguridad."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def sesion(request: Request, call_next):
    # Solo se lee la firma de la cookie; el administrador se consulta en la BD en cada página o /api/*.
    datos = auth.leer_sesion(request)
    request.state.sesion = datos
    request.state.admin = None
    response = await call_next(request)
    # Expiración por inactividad: cada request válido renueva la cookie, salvo que la respuesta ya
    # la cambie (login, logout, contraseña nueva o sesión inválida).
    ya_la_cambia = any(
        v.startswith(f"{auth.COOKIE_SESION}=") for v in response.headers.getlist("set-cookie")
    )
    path = request.url.path
    if datos and not ya_la_cambia and not path.startswith("/static/") and response.status_code not in (401, 403):
        auth.crear_cookie_sesion(response, datos)
    return response


@app.middleware("http")
async def cors_latido(request: Request, call_next):
    """CORS solo para /api/latido (orígenes de LATIDO_ORIGINS, solo POST, sin credenciales)."""
    if request.url.path != RUTA_LATIDO:
        return await call_next(request)
    origen = request.headers.get("origin")
    permitido = origen is not None and origen.strip().rstrip("/").lower() in settings.latido_origenes

    if request.method == "OPTIONS":
        if not permitido or request.headers.get("access-control-request-method", "").upper() != "POST":
            return Response(status_code=403, headers={"Vary": "Origin"})
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origen,
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            },
        )
    # Sin Origin (llamadas de servidor) se procesa; con un Origin no permitido se rechaza.
    if origen is not None and not permitido:
        return JSONResponse({"detail": "Origen no permitido."}, status_code=403, headers={"Vary": "Origin"})
    response = await call_next(request)
    if permitido:
        response.headers["Access-Control-Allow-Origin"] = origen
        response.headers["Vary"] = "Origin"
    return response


@app.middleware("http")
async def headers_seguridad(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Manejo de errores: siempre {"detail": "mensaje en español"}
# ---------------------------------------------------------------------------

class ErrorCampo(Exception):
    """Error de negocio asociado a un campo del formulario."""

    def __init__(self, status_code: int, campo: str, mensaje: str):
        self.status_code = status_code
        self.campo = campo
        self.mensaje = mensaje


class ErrorValidacion(Exception):
    """Varios campos inválidos a la vez (422 con todos los errores)."""

    def __init__(self, errores: dict[str, str]):
        self.errores = errores


_TRADUCCIONES = {
    404: "No encontrado.",
    405: "Método no permitido.",
}


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if not isinstance(detail, str) or detail == HTTPStatus(exc.status_code).phrase:
        detail = _TRADUCCIONES.get(exc.status_code, "Ocurrió un error.")
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _error_validacion(request: Request, exc: RequestValidationError):
    errores: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "path", "query")]
        tipo = err.get("type", "")
        if tipo == "json_invalid":
            campo, mensaje = "_", "El cuerpo de la solicitud no es un JSON válido."
        elif tipo == "missing" and not loc:
            campo, mensaje = "_", "Faltan los datos de la solicitud."
        elif tipo == "value_error":
            campo, mensaje = (loc[0] if loc else "portales"), str(err.get("ctx", {}).get("error", "Valor inválido."))
        else:
            campo, mensaje = (loc[0] if loc else "_"), "Valor inválido."
        errores.setdefault(campo, mensaje)
    detail = next(iter(errores.values()), "Datos inválidos.")
    return JSONResponse({"detail": detail, "errores": errores}, status_code=422)


@app.exception_handler(auth.CambioContrasenaRequerido)
async def _cambio_requerido(request: Request, exc: auth.CambioContrasenaRequerido):
    return JSONResponse({"detail": auth.MSG_CAMBIO_REQUERIDO, "cambioRequerido": True}, status_code=403)


@app.exception_handler(ErrorCampo)
async def _error_campo(request: Request, exc: ErrorCampo):
    return JSONResponse({"detail": exc.mensaje, "errores": {exc.campo: exc.mensaje}}, status_code=exc.status_code)


@app.exception_handler(ErrorValidacion)
async def _error_validacion_campos(request: Request, exc: ErrorValidacion):
    return JSONResponse(
        {"detail": next(iter(exc.errores.values()), "Datos inválidos."), "errores": exc.errores}, status_code=422
    )


@app.exception_handler(pyodbc.Error)
async def _error_bd(request: Request, exc: pyodbc.Error):
    log.error("Error de base de datos en %s %s: %s", request.method, request.url.path, exc.args[:1])
    return JSONResponse(
        {"detail": "No se pudo conectar con la base de datos. Intenta nuevamente en unos minutos."},
        status_code=503,
    )


@app.exception_handler(Exception)
async def _error_inesperado(request: Request, exc: Exception):
    log.error("Error inesperado en %s %s: %s", request.method, request.url.path, type(exc).__name__)
    return JSONResponse({"detail": "Ocurrió un error inesperado. Intenta nuevamente."}, status_code=500)


# ---------------------------------------------------------------------------
# Rutas públicas y páginas
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


def _a_login(request: Request) -> RedirectResponse:
    """303 a /login, recordando la página pedida para volver a ella después de ingresar."""
    ruta = request.url.path
    destino = "/login" if ruta == "/" else f"/login?siguiente={quote(ruta, safe='/')}"
    return RedirectResponse(destino, status_code=303)


def _admin_de_pagina(request: Request) -> dict | None:
    """Administrador de la sesión para las páginas (deja request.state.admin listo). Puede lanzar pyodbc.Error."""
    admin = auth.admin_de_sesion(request.state.sesion)
    request.state.admin = admin
    return admin


def _pagina_protegida(request: Request, html: str, status_code: int = 200) -> HTMLResponse | RedirectResponse:
    """Sin sesión → /login; debe cambiar la contraseña → /cambiar-contrasena; si no, la página."""
    if not request.state.sesion:
        return _a_login(request)
    try:
        admin = _admin_de_pagina(request)
    except pyodbc.Error as e:
        log.error("Error de base de datos al verificar la sesión: %s", e.args[:1])
        return _pagina_error(MSG_BD_NO_DISPONIBLE, 503)
    if admin is None:
        # Inactivo, eliminado o con otra contraseña: la cookie ya no sirve.
        resp = _a_login(request)
        auth.borrar_cookie_sesion(resp)
        return resp
    if admin["DebeCambiarContrasena"]:
        return RedirectResponse("/cambiar-contrasena", status_code=303)
    return HTMLResponse(html, status_code=status_code)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    return _pagina_protegida(request, _INICIO_HTML)


@app.get("/contactos", response_class=HTMLResponse)
def contactos(request: Request):
    return _pagina_protegida(request, _CONTACTOS_HTML)


@app.get("/historial", response_class=HTMLResponse)
def historial(request: Request):
    return _pagina_protegida(request, _HISTORIAL_HTML)


@app.get("/estadisticas", response_class=HTMLResponse)
def estadisticas(request: Request):
    return _pagina_protegida(request, _ESTADISTICAS_HTML)


@app.get("/estadisticas/general", response_class=HTMLResponse)
def estadisticas_general(request: Request):
    return _pagina_protegida(request, _ESTADISTICAS_GENERAL_HTML)


# Slug de portal en la URL: minúsculas ASCII, números y guiones (p. ej. «energia», «bodega-norte», «portal-2»).
_SLUG_VALIDO = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_LARGO_SLUG = 64


@app.get("/estadisticas/portal/{slug}", response_class=HTMLResponse)
def estadisticas_portal(request: Request, slug: str):
    # La página resuelve el slug con /api/estadisticas/portales y muestra «Portal no encontrado» si no existe.
    # Un slug con otro formato ni siquiera puede existir: la misma página, con 404.
    valido = len(slug) <= MAX_LARGO_SLUG and _SLUG_VALIDO.fullmatch(slug) is not None
    return _pagina_protegida(request, _ESTADISTICAS_PORTAL_HTML, 200 if valido else 404)


@app.get("/administradores", response_class=HTMLResponse)
def administradores(request: Request):
    return _pagina_protegida(request, _ADMINISTRADORES_HTML)


@app.get("/consulta-bd", response_class=HTMLResponse)
def consulta_bd_pagina(request: Request):
    return _pagina_protegida(request, _CONSULTA_BD_HTML)


@app.get("/login", response_class=HTMLResponse)
def login(request: Request):
    # Con una sesión válida no tiene sentido el formulario: se sigue de largo.
    if not request.state.sesion:
        return HTMLResponse(_LOGIN_HTML)
    try:
        admin = _admin_de_pagina(request)
    except pyodbc.Error:
        return HTMLResponse(_LOGIN_HTML)
    if admin is not None:
        return RedirectResponse("/cambiar-contrasena" if admin["DebeCambiarContrasena"] else "/", status_code=303)
    resp = HTMLResponse(_LOGIN_HTML)
    auth.borrar_cookie_sesion(resp)
    return resp


@app.get("/cambiar-contrasena", response_class=HTMLResponse)
def cambiar_contrasena(request: Request):
    if not request.state.sesion:
        return RedirectResponse("/login", status_code=303)
    try:
        admin = _admin_de_pagina(request)
    except pyodbc.Error as e:
        log.error("Error de base de datos al verificar la sesión: %s", e.args[:1])
        return _pagina_error(MSG_BD_NO_DISPONIBLE, 503)
    if admin is None:
        resp = RedirectResponse("/login", status_code=303)
        auth.borrar_cookie_sesion(resp)
        return resp
    return HTMLResponse(_CAMBIAR_HTML)


# ---------------------------------------------------------------------------
# Login, cierre de sesión y cambio de contraseña
# ---------------------------------------------------------------------------

MSG_CREDENCIALES = "Correo o contraseña incorrectos."
MSG_DEMASIADOS_INTENTOS = "Demasiados intentos desde tu conexión. Espera unos minutos e intenta nuevamente."
MSG_POR_DEFECTO_VENCIDA = (
    "La contraseña por defecto venció. Pide que la restablezcan e ingresa dentro de las "
    f"{db.HORAS_CONTRASENA_POR_DEFECTO} horas siguientes."
)


def _siguiente_seguro(siguiente: str | None) -> str:
    """Solo rutas internas: evita usar /login para redirigir a otro sitio (//otro.com, /\\otro.com)."""
    if not siguiente or not siguiente.startswith("/") or siguiente.startswith(("//", "/\\")):
        return "/"
    if any(c in siguiente for c in "\\\r\n\t") or siguiente.startswith(("/login", "/cambiar-contrasena", "/api/")):
        return "/"
    return siguiente


def _controlar_intentos(request: Request) -> None:
    if not auth.limite_intentos.permitir(auth.ip_cliente(request)):
        log.warning("Límite de intentos por IP alcanzado en %s", request.url.path)
        raise StarletteHTTPException(status_code=429, detail=MSG_DEMASIADOS_INTENTOS)


@app.post("/api/auth/login")
def api_login(request: Request, datos: Ingreso, siguiente: str | None = Query(None)):
    _controlar_intentos(request)
    try:
        admin = auth.autenticar(datos.correo, datos.contrasena)
    except auth.CredencialesInvalidas as e:
        log.info("Ingreso rechazado: %s", e)
        raise StarletteHTTPException(status_code=401, detail=MSG_CREDENCIALES) from None
    except auth.ContrasenaPorDefectoVencida:
        log.warning("Ingreso rechazado: contraseña por defecto vencida")
        raise StarletteHTTPException(status_code=401, detail=MSG_POR_DEFECTO_VENCIDA) from None

    log.info("Ingreso aceptado (administrador Id=%s)", admin["Id"])
    destino = "/cambiar-contrasena" if admin["DebeCambiarContrasena"] else _siguiente_seguro(siguiente)
    resp = JSONResponse({"redirect": destino, "debeCambiarContrasena": admin["DebeCambiarContrasena"]})
    auth.crear_cookie_sesion(resp, auth.datos_sesion(admin))
    return resp


@app.post("/api/auth/logout")
def api_logout():
    resp = JSONResponse({"redirect": "/login"})
    auth.borrar_cookie_sesion(resp)
    return resp


MSG_IGUAL_A_LA_ACTUAL = "La contraseña nueva debe ser distinta de la actual."


def _errores_contrasena_nueva(nueva: str, confirmacion: str) -> dict[str, str]:
    """Política + confirmación. La comparación con la actual la hace cada endpoint después de verificar
    la contraseña: antes serviría para adivinarla sin sumar intentos fallidos."""
    errores: dict[str, str] = {}
    mensaje = claves.error_politica(nueva)
    if mensaje:
        errores["nueva"] = mensaje
    if nueva != confirmacion:
        errores["confirmacion"] = "Las contraseñas no coinciden."
    return errores


@app.post("/api/auth/cambiar-contrasena")
def api_cambiar_contrasena(datos: CambioContrasena, admin: dict = Depends(auth.require_sesion)):
    errores: dict[str, str] = {}
    if not datos.actual:
        errores["actual"] = "Ingresa tu contraseña actual."
    errores.update(_errores_contrasena_nueva(datos.nueva, datos.confirmacion))
    if errores:
        raise ErrorValidacion(errores)
    try:
        auth.comprobar_contrasena(admin, datos.actual, es_ingreso=False)
    except auth.CredencialesInvalidas:
        log.info("Cambio de contraseña rechazado: contraseña actual incorrecta (Id=%s)", admin["Id"])
        raise ErrorCampo(422, "actual", "La contraseña actual no es correcta.") from None
    except auth.ContrasenaPorDefectoVencida:
        raise ErrorCampo(422, "actual", MSG_POR_DEFECTO_VENCIDA) from None
    if datos.nueva == datos.actual:
        raise ErrorCampo(422, "nueva", MSG_IGUAL_A_LA_ACTUAL)

    hash_, sal, algoritmo = claves.nuevo_hash(datos.nueva)
    db.cambiar_contrasena_admin(admin["Id"], hash_, sal, algoritmo)
    log.info("Contraseña cambiada (administrador Id=%s)", admin["Id"])
    resp = JSONResponse({"mensaje": "Contraseña actualizada.", "redirect": "/"})
    # La cookie anterior queda inválida (otra huella): se emite una nueva para seguir conectado.
    auth.crear_cookie_sesion(resp, {"id": admin["Id"], "h": auth.huella(hash_)})
    return resp


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _gerencia_valida(gerencia: str) -> str:
    """Devuelve la gerencia tal como está en la BD (el agente MiraStock compara contra ese valor)."""
    buscada = gerencia.strip().casefold()
    for valor in db.listar_gerencias():
        if valor.strip().casefold() == buscada:
            return valor
    raise ErrorCampo(422, "gerencia", "La gerencia seleccionada no es válida.")


def _cuenta(operacion, *args) -> tuple[object, str | None]:
    """Ejecuta una operación de External ID. Devuelve (resultado, None) si salió bien, o (None, motivo del fallo)."""
    try:
        return operacion(*args), None
    except externalid.ErrorExternalId as e:
        return None, e.motivo
    except Exception as e:
        log.error("Error inesperado en External ID: %s", type(e).__name__)
        return None, "error inesperado"


def _usuario_o_404(usuario_id: int) -> dict:
    usuario = db.obtener_usuario(usuario_id)
    if usuario is None:
        raise StarletteHTTPException(status_code=404, detail="Usuario no encontrado.")
    return usuario


@app.get("/api/me")
def api_me(admin: dict = Depends(auth.require_sesion)):
    # Responde aunque deba cambiar la contraseña: la página de cambio muestra el nombre.
    return {
        "id": admin["Id"],
        "nombre": admin["Nombre"],
        "correo": admin["Correo"],
        "debeCambiarContrasena": admin["DebeCambiarContrasena"],
    }


@app.get("/api/gerencias")
def api_gerencias(admin: dict = Depends(require_admin)):
    return db.listar_gerencias()


@app.get("/api/usuarios")
def api_listar_usuarios(admin: dict = Depends(require_admin)):
    return db.listar_usuarios()


@app.post("/api/usuarios", status_code=201)
def api_crear_usuario(datos: UsuarioCrear, admin: dict = Depends(require_admin)):
    gerencia = _gerencia_valida(datos.gerencia)
    if db.existe_correo(datos.correo):
        raise ErrorCampo(409, "correo", "Ese correo ya está registrado.")
    try:
        usuario = db.crear_usuario(
            datos.correo, datos.nombre, datos.apellido, gerencia, datos.cliente,
            datos.portal1, datos.portal2, datos.portal3,
        )
    except db.CorreoDuplicado:
        raise ErrorCampo(409, "correo", "Ese correo ya está registrado.") from None

    log.info("Usuario creado (Id=%s)", usuario["Id"])
    # El correo de bienvenida ya no se envía al crear: se envía con POST /api/usuarios/{id}/enviar-correo.
    # Si falla la cuenta de acceso no se revierte el INSERT: se reintenta al enviar el correo.
    _, motivo = _cuenta(externalid.asegurar, usuario["Correo"], usuario["Nombre"], usuario["Apellido"])
    if motivo:
        log.warning("Usuario creado (Id=%s) sin cuenta de acceso: %s", usuario["Id"], motivo)
        return {
            "usuario": usuario,
            "mensaje": f"Usuario creado, pero no se pudo crear su cuenta de acceso: {motivo}. "
                       "Se reintentará al enviar el correo.",
            "avisoCuenta": True,
        }
    return {"usuario": usuario, "mensaje": "Usuario creado.", "avisoCuenta": False}


@app.put("/api/usuarios/{usuario_id}")
def api_editar_usuario(usuario_id: int, datos: UsuarioEditar, admin: dict = Depends(require_admin)):
    actual = _usuario_o_404(usuario_id)
    gerencia = _gerencia_valida(datos.gerencia)
    if not db.actualizar_usuario(
        usuario_id, datos.nombre, datos.apellido, gerencia, datos.cliente, datos.portal1, datos.portal2, datos.portal3
    ):
        raise StarletteHTTPException(status_code=404, detail="Usuario no encontrado.")
    log.info("Usuario actualizado (Id=%s)", usuario_id)
    usuario = _usuario_o_404(usuario_id)
    if (usuario["Nombre"], usuario["Apellido"]) != (actual["Nombre"], actual["Apellido"]):
        _, motivo = _cuenta(externalid.actualizar_nombre, usuario["Correo"], usuario["Nombre"], usuario["Apellido"])
        if motivo:
            log.warning("No se actualizó el nombre en la cuenta de acceso (Id=%s): %s", usuario_id, motivo)
            return {
                "usuario": usuario,
                "mensaje": f"Usuario actualizado, pero no se pudo actualizar el nombre en su cuenta de acceso: {motivo}.",
                "avisoCuenta": True,
            }
    return {"usuario": usuario, "mensaje": "Usuario actualizado", "avisoCuenta": False}


@app.delete("/api/usuarios/{usuario_id}")
def api_eliminar_usuario(usuario_id: int, admin: dict = Depends(require_admin)):
    actual = _usuario_o_404(usuario_id)
    if not db.eliminar_usuario(usuario_id):
        raise StarletteHTTPException(status_code=404, detail="Usuario no encontrado.")
    log.info("Usuario eliminado (Id=%s)", usuario_id)
    _, motivo = _cuenta(externalid.eliminar, actual["Correo"])
    if motivo:
        log.warning("No se eliminó la cuenta de acceso (Id=%s): %s", usuario_id, motivo)
        return {
            "mensaje": f"Usuario eliminado, pero no se pudo eliminar su cuenta de acceso: {motivo}.",
            "avisoCuenta": True,
        }
    return {"mensaje": "Usuario eliminado", "avisoCuenta": False}


@app.post("/api/usuarios/{usuario_id}/enviar-correo")
def api_enviar_correo(usuario_id: int, admin: dict = Depends(require_admin)):
    """Envía (o reenvía) el correo de bienvenida. Solo si sale bien marca InvitacionEnviada=1."""
    usuario = _usuario_o_404(usuario_id)
    # Sin cuenta de acceso el usuario no podría ingresar: no se envía el correo.
    resultado_cuenta, motivo = _cuenta(externalid.asegurar, usuario["Correo"], usuario["Nombre"], usuario["Apellido"])
    if motivo:
        log.warning("No se envió el correo (Id=%s): falló la cuenta de acceso: %s", usuario_id, motivo)
        raise StarletteHTTPException(status_code=502, detail=f"No se pudo crear la cuenta de acceso: {motivo}")
    # Una cuenta antigua con contraseña no entra solo con código: el correo diría algo falso.
    if resultado_cuenta and resultado_cuenta[1] == externalid.EXISTE_CONTRASENA:
        log.warning("No se envió el correo (Id=%s): la cuenta de acceso es antigua (con contraseña)", usuario_id)
        raise StarletteHTTPException(
            status_code=409, detail="La cuenta de acceso es antigua (con contraseña): elimínala y vuelve a intentar"
        )
    try:
        resultado = mailer.enviar_bienvenida(usuario)
    except Exception as e:
        log.error("Error inesperado al enviar correo: %s", type(e).__name__)
        resultado = mailer.ResultadoEnvio(False, "Error inesperado al enviar el correo")

    if not resultado.enviado:
        # 503: correo deshabilitado o sin credenciales. 502: Graph rechazó o no respondió.
        raise StarletteHTTPException(
            status_code=503 if resultado.no_configurado else 502,
            detail=f"No se pudo enviar el correo: {resultado.mensaje}",
        )

    try:
        db.marcar_invitacion_enviada(usuario_id)
    except pyodbc.Error as e:
        # El correo ya salió: se informa el éxito igual para no inducir un reenvío duplicado.
        log.error("El correo se envió, pero no se pudo marcar InvitacionEnviada: %s", e.args[:1])
    return {"correoEnviado": True, "mensaje": f"Correo enviado a {usuario['Correo']}."}


# ---------------------------------------------------------------------------
# Centro de administración principal (/administradores)
# ---------------------------------------------------------------------------

MSG_PERMISO_VENCIDO = "El permiso de edición venció. Vuelve a ingresar la contraseña del administrador."


def _estado_admin(a: dict) -> str:
    if not a["Activo"]:
        return "inactivo"
    return "bloqueado" if a["Bloqueado"] else "activo"


def _admin_json(a: dict, sesion_id: int) -> dict:
    """Datos públicos de un administrador (nunca el hash ni la sal)."""
    return {
        "id": a["Id"],
        "nombre": a["Nombre"],
        "correo": a["Correo"],
        "ultimoAcceso": _iso_utc(a["UltimoAcceso"]),
        "estado": _estado_admin(a),
        "bloqueadoHasta": _iso_utc(a["BloqueadoHasta"]) if a["Bloqueado"] else None,
        "esYo": a["Id"] == sesion_id,
    }


def _admin_editable(admin_id: int) -> dict:
    destino = db.obtener_admin(admin_id)
    if destino is None:
        raise StarletteHTTPException(status_code=404, detail="Administrador no encontrado.")
    if not destino["Activo"]:
        raise StarletteHTTPException(status_code=403, detail="El administrador está inactivo y no se puede editar.")
    return destino


@app.get("/api/administradores")
def api_administradores(admin: dict = Depends(require_admin)):
    return [_admin_json(a, admin["Id"]) for a in db.listar_admins()]


@app.post("/api/administradores/{admin_id}/verificar")
def api_verificar_administrador(
    admin_id: int, request: Request, datos: VerificarAdministrador, admin: dict = Depends(require_admin)
):
    """Contraseña DE ESE administrador → permiso de edición de 5 minutos. Los fallos cuentan para su bloqueo."""
    if not datos.contrasena:
        raise ErrorCampo(422, "contrasena", "Ingresa la contraseña.")
    _controlar_intentos(request)
    destino = _admin_editable(admin_id)
    if destino["Bloqueado"]:
        raise StarletteHTTPException(
            status_code=423, detail="Este administrador está bloqueado por intentos fallidos. Intenta más tarde."
        )
    try:
        verificado = auth.comprobar_contrasena(destino, datos.contrasena, es_ingreso=False)
    except auth.CredencialesInvalidas:
        log.info("Verificación de card rechazada (administrador Id=%s, por Id=%s)", admin_id, admin["Id"])
        raise ErrorCampo(422, "contrasena", "La contraseña no es correcta.") from None
    except auth.ContrasenaPorDefectoVencida:
        raise ErrorCampo(422, "contrasena", MSG_POR_DEFECTO_VENCIDA) from None

    log.info("Permiso de edición entregado (administrador Id=%s, por Id=%s)", admin_id, admin["Id"])
    resp = JSONResponse({
        "permiso": auth.crear_permiso(verificado, admin["Id"]),
        "expiraEnSeg": auth.DURACION_PERMISO_S,
        "administrador": {"id": verificado["Id"], "nombre": verificado["Nombre"], "correo": verificado["Correo"]},
    })
    # Si era su propia card y el hash se migró a PBKDF2, su cookie necesita la huella nueva.
    if admin_id == admin["Id"] and verificado["ContrasenaHash"] != admin["ContrasenaHash"]:
        auth.crear_cookie_sesion(resp, auth.datos_sesion(verificado))
    return resp


@app.put("/api/administradores/{admin_id}")
def api_editar_administrador(admin_id: int, datos: AdministradorEditar, admin: dict = Depends(require_admin)):
    destino = _admin_editable(admin_id)
    if not auth.permiso_valido(datos.permiso, destino, admin["Id"]):
        return JSONResponse({"detail": MSG_PERMISO_VENCIDO, "permisoVencido": True}, status_code=403)

    cambia_clave = bool(datos.nuevaContrasena or datos.confirmacion)
    if cambia_clave:
        errores = {
            ("nuevaContrasena" if campo == "nueva" else campo): mensaje
            for campo, mensaje in _errores_contrasena_nueva(datos.nuevaContrasena, datos.confirmacion).items()
        }
        # Aquí sí se compara con el hash: el permiso ya prueba que se conoce la contraseña actual.
        if not errores and claves.verificar(
            destino["AlgoritmoHash"], datos.nuevaContrasena, destino["ContrasenaSal"], destino["ContrasenaHash"]
        ):
            errores["nuevaContrasena"] = MSG_IGUAL_A_LA_ACTUAL
        if errores:
            raise ErrorValidacion(errores)

    otro = db.obtener_admin_por_correo(datos.correo) if datos.correo != destino["Correo"] else None
    if otro is not None:
        raise ErrorCampo(409, "correo", "Ese correo ya pertenece a otro administrador.")
    try:
        if not db.actualizar_admin(admin_id, datos.nombre, datos.correo):
            raise StarletteHTTPException(status_code=404, detail="Administrador no encontrado.")
    except db.CorreoDuplicado:
        raise ErrorCampo(409, "correo", "Ese correo ya pertenece a otro administrador.") from None

    hash_nuevo = None
    if cambia_clave:
        hash_nuevo, sal, algoritmo = claves.nuevo_hash(datos.nuevaContrasena)
        db.cambiar_contrasena_admin(admin_id, hash_nuevo, sal, algoritmo)
    log.info(
        "Administrador actualizado (Id=%s, por Id=%s%s)", admin_id, admin["Id"], ", con contraseña nueva" if cambia_clave else ""
    )

    actualizado = db.obtener_admin(admin_id)
    if actualizado is None:
        raise StarletteHTTPException(status_code=404, detail="Administrador no encontrado.")
    mensaje = "Administrador actualizado."
    if cambia_clave:
        mensaje = "Administrador actualizado. Su contraseña cambió y sus otras sesiones se cerraron."
    resp = JSONResponse({"administrador": _admin_json(actualizado, admin["Id"]), "mensaje": mensaje})
    if hash_nuevo is not None and admin_id == admin["Id"]:
        # Cambió su propia contraseña: sigue conectado en esta sesión.
        auth.crear_cookie_sesion(resp, {"id": admin_id, "h": auth.huella(hash_nuevo)})
    return resp


# ---------------------------------------------------------------------------
# Latidos de sesión (público: los envían los JS de Energía y MiraStock)
# ---------------------------------------------------------------------------

TAMANO_MAX_LATIDO = 8 * 1024
# text/plain permite navigator.sendBeacon al cerrar la pestaña; el body igual debe ser JSON.
_TIPOS_LATIDO = {"application/json", "text/plain"}


def _latido_invalido(detalle: str) -> StarletteHTTPException:
    return StarletteHTTPException(status_code=400, detail=detalle)


async def _cuerpo_latido(request: Request) -> dict:
    tipo = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if tipo not in _TIPOS_LATIDO:
        raise _latido_invalido("El cuerpo debe ser JSON.")
    try:
        largo = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise _latido_invalido("Cuerpo de la solicitud inválido.") from None
    if largo > TAMANO_MAX_LATIDO:
        raise _latido_invalido("El cuerpo de la solicitud es demasiado grande.")
    # Se lee por partes con tope por si el cliente no envía Content-Length (chunked).
    cuerpo = bytearray()
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > TAMANO_MAX_LATIDO:
            raise _latido_invalido("El cuerpo de la solicitud es demasiado grande.")
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        raise _latido_invalido("El cuerpo de la solicitud no es un JSON válido.") from None
    if not isinstance(datos, dict):
        raise _latido_invalido("El cuerpo de la solicitud no es válido.")
    return datos


def _llave_latido(datos: dict) -> str:
    """GUID de «t» normalizado (minúsculas, con guiones). 400 si no es válido."""
    llave = datos.get("t")
    try:
        llave = str(uuid.UUID(llave)) if isinstance(llave, str) else None
    except ValueError:
        llave = None
    if llave is None:
        raise _latido_invalido("La llave de sesión no es válida.")
    return llave


@app.post(RUTA_LATIDO, status_code=204)
async def api_latido(request: Request):
    """Registra que la sesión sigue activa. Responde 204 aunque no actualice nada (no revela si la llave existe).

    Nunca se registran en el log la llave ni el token.
    """
    datos = await _cuerpo_latido(request)
    tipo = datos.get("tipo")
    # `cierre` es opcional: true = el usuario cerró con «Atrás» o «Cerrar sesión». type() evita aceptar 1 o 0.
    cierre = datos.get("cierre", False)
    if type(cierre) is not bool:
        raise _latido_invalido("El campo «cierre» debe ser true o false.")

    if tipo == "mirastock":
        llave = _llave_latido(datos)
        await run_in_threadpool(db.cierre_mirastock if cierre else db.latido_mirastock, llave)
        return Response(status_code=204)

    if tipo == "energia":
        # v10: el Header de Energía manda la llave «t» que guardó el flujo; «token» (v8/v9) sigue funcionando.
        if ("t" in datos) == ("token" in datos):
            raise _latido_invalido("Envía la llave (t) o el token, no ambos.")
        if "t" in datos:
            llave = _llave_latido(datos)
            await run_in_threadpool(db.cierre_energia_llave if cierre else db.latido_energia_llave, llave)
            return Response(status_code=204)
        token = datos.get("token")
        if not isinstance(token, str) or not token.strip():
            raise _latido_invalido("Falta el token de sesión.")
        try:
            correo = await run_in_threadpool(auth.validar_token_energia, token.strip())
        except auth.ClaveNoDisponible:
            raise StarletteHTTPException(
                status_code=503, detail="No se pudo validar el token en este momento. Intenta nuevamente."
            ) from None
        except auth.TokenInvalido as e:
            log.debug("Latido de Energía rechazado: %s", e)
            raise StarletteHTTPException(status_code=401, detail="El token de sesión no es válido.") from None
        await run_in_threadpool(db.cierre_energia if cierre else db.latido_energia, correo)
        return Response(status_code=204)

    raise _latido_invalido("El tipo de latido debe ser «mirastock» o «energia».")


# ---------------------------------------------------------------------------
# Historial de accesos (solo lectura)
# ---------------------------------------------------------------------------

# Los portales salen de la vista: cualquier nombre sirve como filtro. Estos solo fijan la escritura canónica.
PORTALES_HISTORIAL = ("Energía", "MiraStock")
MAX_LARGO_PORTAL = 50
RESULTADOS_HISTORIAL = ("OK", "Denegado")
TAMANO_PAGINA_HISTORIAL = 50
TOPE_CSV_HISTORIAL = 50_000
TOPE_USUARIOS_ESTADISTICAS = 5_000


def _valor_permitido(valor: str, permitidos: tuple[str, ...]) -> str | None:
    """Devuelve el valor canónico (sin distinguir mayúsculas) o None si no está permitido."""
    buscado = valor.strip().casefold()
    return next((p for p in permitidos if p.casefold() == buscado), None)


def _fecha_utc(texto: str) -> datetime | None:
    """ISO 8601 a datetime UTC sin zona (la vista guarda UTC). Sin zona se asume UTC. None si no es válida."""
    try:
        fecha = datetime.fromisoformat(texto.strip())
    except ValueError:
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


def _filtros_historial(
    correo: str | None = None,
    portal: str | None = None,
    resultado: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> db.FiltrosHistorial:
    errores: dict[str, str] = {}
    correo = (correo or "").strip() or None
    if correo and len(correo) > 256:
        errores["correo"] = "El correo no puede superar los 256 caracteres."

    portal_ok = None
    if portal and portal.strip():
        portal_ok = _valor_permitido(portal, PORTALES_HISTORIAL) or portal.strip()
        if len(portal_ok) > MAX_LARGO_PORTAL:
            errores["portal"] = f"El portal no puede superar los {MAX_LARGO_PORTAL} caracteres."

    resultado_ok = None
    if resultado and resultado.strip():
        resultado_ok = _valor_permitido(resultado, RESULTADOS_HISTORIAL)
        if resultado_ok is None:
            errores["resultado"] = "El resultado debe ser OK o Denegado."

    fechas: dict[str, datetime | None] = {}
    for campo, texto in (("desde", desde), ("hasta", hasta)):
        fechas[campo] = None
        if texto and texto.strip():
            fechas[campo] = _fecha_utc(texto)
            if fechas[campo] is None:
                errores[campo] = "La fecha no tiene un formato válido (ISO 8601)."
    if fechas["desde"] and fechas["hasta"] and fechas["desde"] >= fechas["hasta"]:
        errores.setdefault("hasta", "La fecha «hasta» debe ser posterior a «desde».")

    if errores:
        raise ErrorValidacion(errores)
    return db.FiltrosHistorial(correo, portal_ok, resultado_ok, fechas["desde"], fechas["hasta"])


def _iso_utc(fecha: datetime | None) -> str | None:
    # La vista declara Fecha como NULL-able (viene de una unión): una fila sin fecha no debe romper la respuesta.
    return fecha.strftime("%Y-%m-%dT%H:%M:%SZ") if fecha else None


def _es_denegado(fila: dict) -> bool:
    # Un acceso denegado no fue una sesión: Cierre, Tiempo y Final quedan vacíos.
    return fila["Resultado"] == "Denegado"


def _texto_cierre(fila: dict) -> str:
    """Cómo terminó la sesión, con los mismos textos que la tabla (vacío = «—» en pantalla).

    Prioridad: Botón → En curso → Inactividad → Sin actividad → No medida.
    """
    if _es_denegado(fila):
        return ""
    if fila["CierreExplicito"]:
        return "Botón"
    if fila["EnCurso"]:
        return "En curso"
    if fila["FinalSesion"]:
        return "Inactividad"
    if fila.get("SinActividad"):
        return "Sin actividad"
    if not fila.get("Medible"):
        return "No medida"
    return ""


def _final_sesion(fila: dict) -> datetime | None:
    """Final de sesión a mostrar: sin actividad = la hora de ingreso; no medida o denegado = ninguno."""
    if _es_denegado(fila):
        return None
    if fila["FinalSesion"]:
        return fila["FinalSesion"]
    return fila["Fecha"] if fila.get("SinActividad") else None


def _tiempo_csv(fila: dict) -> str:
    """Minutos de la sesión: 0 si no hubo actividad; vacío si no se midió o fue denegado."""
    if _es_denegado(fila):
        return ""
    if fila.get("SinActividad"):
        return "0"
    return _minutos_csv(fila["TiempoSesionSeg"])


def _zona_csv(tz_offset_min: int) -> str:
    """Texto para el encabezado de las columnas de fecha: «UTC» o «hora local, UTC-03:00»."""
    if tz_offset_min == 0:
        return "UTC"
    horas, minutos = divmod(abs(tz_offset_min), 60)
    return f"hora local, UTC{'+' if tz_offset_min > 0 else '-'}{horas:02d}:{minutos:02d}"


def _fecha_csv(fecha: datetime | None, tz_offset_min: int = 0) -> str:
    return (fecha + timedelta(minutes=tz_offset_min)).strftime("%Y-%m-%d %H:%M:%S") if fecha else ""


def _minutos_csv(segundos: int | None) -> str:
    # Minutos enteros truncados (40 s → 0); vacío si no hubo latidos.
    return str(max(0, segundos) // 60) if segundos is not None else ""


def _duracion_texto(segundos: int | None) -> str:
    """Igual que la pantalla: «< 1 min», «44 min» o «52 h 10 min» (truncado); vacío si no hay tiempo medido."""
    if segundos is None:
        return ""
    minutos = max(0, segundos) // 60
    if segundos < 60:
        return "< 1 min"
    if minutos < 60:
        return f"{minutos} min"
    return f"{minutos // 60} h {minutos % 60:02d} min"


def _celda_csv(valor: str) -> str:
    """Neutraliza la inyección de fórmulas: Excel interpretaría = + - @ (y tab o CR) al inicio."""
    return "'" + valor if valor and valor[0] in "=+-@\t\r" else valor


def _respuesta_csv(
    encabezados: list[str], filas: list[list[str]], prefijo: str, truncado_en: int | None = None
) -> Response:
    salida = io.StringIO()
    # Separador ';' y BOM: Excel en español abre el archivo con columnas y acentos correctos.
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(encabezados)
    escritor.writerows(filas)
    nombre = f"{prefijo}_{datetime.now(timezone.utc):%Y%m%d}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{nombre}"'}
    if truncado_en is not None:
        headers["X-Historial-Truncado"] = str(truncado_en)
    return Response(
        ("\ufeff" + salida.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8", headers=headers
    )


# `admin` va primero: sin sesión responde 401 antes de validar los filtros.

@app.get("/api/historial")
def api_historial(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_historial),
    pagina: int = Query(1, ge=1, le=1_000_000),
):
    filas, total = db.listar_historial(filtros, pagina, TAMANO_PAGINA_HISTORIAL)
    return {
        "filas": [{**f, "Fecha": _iso_utc(f["Fecha"]), "FinalSesion": _iso_utc(f["FinalSesion"])} for f in filas],
        "total": total,
        "pagina": pagina,
        "tamano": TAMANO_PAGINA_HISTORIAL,
        "paginas": max(1, -(-total // TAMANO_PAGINA_HISTORIAL)),
    }


@app.get("/api/historial/resumen")
def api_historial_resumen(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_historial),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    return db.resumen_historial(filtros, tz_offset_min)


@app.get("/api/historial/csv")
def api_historial_csv(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_historial),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    filas, total = db.listar_historial(filtros, 1, TOPE_CSV_HISTORIAL)
    zona = _zona_csv(tz_offset_min)
    encabezados = [
        f"Fecha ({zona})", "Usuario", "Correo", "Portal", "Resultado", f"Final de sesión ({zona})",
        "Tiempo de sesión (min)", "Cierre",
    ]
    contenido = [
        [
            _fecha_csv(f["Fecha"], tz_offset_min),
            *(_celda_csv(f[c] or "") for c in ("Usuario", "Correo", "Portal", "Resultado")),
            _fecha_csv(_final_sesion(f), tz_offset_min),
            _tiempo_csv(f),
            _texto_cierre(f),
        ]
        for f in filas
    ]
    log.info("Historial exportado a CSV (%s de %s filas)", len(filas), total)
    return _respuesta_csv(
        encabezados, contenido, "historial_accesos", TOPE_CSV_HISTORIAL if total > TOPE_CSV_HISTORIAL else None
    )


# ---------------------------------------------------------------------------
# Estadísticas por portal (solo lectura; sesiones = filas con Resultado = 'OK')
# ---------------------------------------------------------------------------

TOTAL_PORTAL_CORPORATIVO = "Total Portal Corporativo"


def _filtros_estadisticas(desde: str | None = None, hasta: str | None = None) -> db.FiltrosHistorial:
    return _filtros_historial(desde=desde, hasta=hasta)


def _filtros_estadisticas_portal(
    portal: str | None = None, correo: str | None = None, desde: str | None = None, hasta: str | None = None
) -> db.FiltrosHistorial:
    """Como `_filtros_estadisticas`, pero el portal es obligatorio y acepta `correo` (contiene).

    Junta todos los errores en un solo 422.
    """
    errores: dict[str, str] = {}
    filtros = None
    try:
        filtros = _filtros_historial(correo=correo, portal=portal, desde=desde, hasta=hasta)
    except ErrorValidacion as e:
        errores = e.errores
    if not (portal and portal.strip()):
        errores = {"portal": "Indica el portal.", **errores}
    if errores:
        raise ErrorValidacion(errores)
    return filtros


def _estadistica_json(datos: dict) -> dict:
    return {**datos, "ultimaConexion": _iso_utc(datos["ultimaConexion"])}


def _celdas_sesiones(datos: dict, tz_offset_min: int) -> list[str]:
    """Sesiones · Sesiones medidas · Sin actividad · Horas totales · Minutos totales · Promedio · Última conexión."""
    return [
        str(datos["sesiones"]),
        str(datos["sesionesMedidas"]),
        str(datos["sinActividad"]),
        _duracion_texto(datos["segundosTotales"]),
        _minutos_csv(datos["segundosTotales"]),
        _duracion_texto(datos["promedioSeg"]),
        _fecha_csv(datos["ultimaConexion"], tz_offset_min),
    ]


def _encabezados_sesiones(tz_offset_min: int) -> list[str]:
    return [
        "Sesiones", "Sesiones medidas", "Sin actividad", "Horas totales", "Minutos totales", "Promedio por sesión",
        f"Última conexión ({_zona_csv(tz_offset_min)})",
    ]


def _slug_portal(nombre: str) -> str:
    """«Energía» → «energia», «Bodega Norte/Sur» → «bodega-norte-sur» (para /estadisticas/portal/<slug>)."""
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-")[:MAX_LARGO_SLUG - 4].strip("-")
    return slug or "portal"


def _slugs_portales(nombres: list[str]) -> dict[str, str]:
    """Slug único por portal: si dos dan el mismo, en orden alfabético el segundo lleva «-2», el tercero «-3»…"""
    usados: set[str] = set()
    slugs: dict[str, str] = {}
    for nombre in sorted(nombres, key=lambda n: (n.casefold(), n)):
        base = _slug_portal(nombre)
        slug, n = base, 1
        while slug in usados:
            n += 1
            slug = f"{base}-{n}"
        usados.add(slug)
        slugs[nombre] = slug
    return slugs


def _nombre_archivo(texto: str) -> str:
    """«Energía» → «energia»: solo letras y números ASCII para el nombre del CSV."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalnum() else "_" for c in ascii_).strip("_") or "portal"


@app.get("/api/estadisticas/portales")
def api_estadisticas_portales(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_estadisticas),
):
    datos = db.estadisticas_portales(filtros.desde, filtros.hasta)
    slugs = _slugs_portales([p["portal"] for p in datos["portales"]])
    return {
        "portales": [{**_estadistica_json(p), "slug": slugs[p["portal"]]} for p in datos["portales"]],
        "total": _estadistica_json(datos["total"]),
    }


@app.get("/api/estadisticas/portales/csv")
def api_estadisticas_portales_csv(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_estadisticas),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    datos = db.estadisticas_portales(filtros.desde, filtros.hasta)
    filas = [
        [_celda_csv(p["portal"]), str(p["usuariosUnicos"]), *_celdas_sesiones(p, tz_offset_min)]
        for p in datos["portales"]
    ]
    total = datos["total"]
    filas.append([TOTAL_PORTAL_CORPORATIVO, str(total["usuariosUnicos"]), *_celdas_sesiones(total, tz_offset_min)])
    log.info("Estadísticas por portal exportadas a CSV (%s portales)", len(datos["portales"]))
    return _respuesta_csv(
        ["Portal", "Usuarios únicos", *_encabezados_sesiones(tz_offset_min)], filas, "estadisticas_portales"
    )


@app.get("/api/estadisticas/resumen")
def api_estadisticas_resumen(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_estadisticas_portal),
):
    """Tarjetas de la vista de un portal (v17), con filtro opcional de correo (contiene)."""
    datos = db.estadisticas_resumen_portal(filtros.portal, filtros.desde, filtros.hasta, filtros.correo)
    return {"portal": filtros.portal, "correo": filtros.correo, **_estadistica_json(datos)}


@app.get("/api/estadisticas/usuarios")
def api_estadisticas_usuarios(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_estadisticas_portal),
):
    filas, truncado = db.estadisticas_usuarios(
        filtros.portal, filtros.desde, filtros.hasta, TOPE_USUARIOS_ESTADISTICAS, filtros.correo
    )
    # Sin filtro ni truncado, el total sin filtro es el mismo: no hace falta otra consulta.
    if filtros.correo or truncado:
        total_sin_filtro = db.contar_usuarios_portal(filtros.portal, filtros.desde, filtros.hasta)
    else:
        total_sin_filtro = len(filas)
    return {
        "portal": filtros.portal,
        "correo": filtros.correo,
        "filas": [_estadistica_json(f) for f in filas],
        "total": len(filas),
        "totalSinFiltro": total_sin_filtro,
        "truncado": truncado,
    }


@app.get("/api/estadisticas/usuarios/csv")
def api_estadisticas_usuarios_csv(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_estadisticas_portal),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    filas, truncado = db.estadisticas_usuarios(
        filtros.portal, filtros.desde, filtros.hasta, TOPE_USUARIOS_ESTADISTICAS, filtros.correo
    )
    contenido = [
        [_celda_csv(f["usuario"]), _celda_csv(f["correo"] or ""), *_celdas_sesiones(f, tz_offset_min)]
        for f in filas
    ]
    log.info("Estadísticas de usuarios exportadas a CSV (%s filas)", len(filas))
    return _respuesta_csv(
        ["Usuario", "Correo", *_encabezados_sesiones(tz_offset_min)],
        contenido,
        f"estadisticas_{_nombre_archivo(filtros.portal)}_usuarios",
        TOPE_USUARIOS_ESTADISTICAS if truncado else None,
    )


# ---------------------------------------------------------------------------
# Gráficos de /estadisticas (v16; solo lectura)
# ---------------------------------------------------------------------------

MAX_DIAS_SERIES = 731
ETIQUETAS_DURACION = ("< 5 min", "5–15 min", "15–30 min", "30–60 min", "> 1 h")


def _filtros_series(
    portal: str | None = None, correo: str | None = None, desde: str | None = None, hasta: str | None = None
) -> db.FiltrosHistorial:
    """Fechas, portal opcional (sin portal = todos, desglosado por portal) y correo (v17, solo con portal).

    Junta todos los errores en un solo 422.
    """
    errores: dict[str, str] = {}
    filtros = None
    try:
        filtros = _filtros_historial(correo=correo, portal=portal, desde=desde, hasta=hasta)
    except ErrorValidacion as e:
        errores = e.errores
    if correo and correo.strip() and not (portal and portal.strip()) and "correo" not in errores:
        errores = {"correo": "Indica el portal para buscar por correo.", **errores}
    if errores:
        raise ErrorValidacion(errores)
    return filtros


def _filtros_distribucion(
    portal: str | None = None, correo: str | None = None, desde: str | None = None, hasta: str | None = None
) -> db.FiltrosHistorial:
    """Portal obligatorio, fechas y correo opcional (v17, contiene)."""
    return _filtros_estadisticas_portal(portal=portal, correo=correo, desde=desde, hasta=hasta)


def _dia_local(fecha: datetime, tz_offset_min: int) -> date:
    return (fecha + timedelta(minutes=tz_offset_min)).date()


def _limites_series(filtros: db.FiltrosHistorial, tz_offset_min: int) -> tuple[date | None, date | None]:
    """Primer y último día local del rango pedido (`hasta` es exclusivo); None si falta esa fecha."""
    primero = _dia_local(filtros.desde, tz_offset_min) if filtros.desde else None
    ultimo = _dia_local(filtros.hasta - timedelta(microseconds=1), tz_offset_min) if filtros.hasta else None
    return primero, ultimo


def _error_rango_series(primero: date, ultimo: date, mensaje: str) -> None:
    if (ultimo - primero).days + 1 > MAX_DIAS_SERIES:
        raise ErrorValidacion({"hasta": mensaje})


@app.get("/api/estadisticas/series")
def api_estadisticas_series(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_series),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    primero, ultimo = _limites_series(filtros, tz_offset_min)
    if primero and ultimo:
        _error_rango_series(primero, ultimo, f"El rango no puede superar los {MAX_DIAS_SERIES} días.")
    datos = db.estadisticas_series(filtros.portal, filtros.desde, filtros.hasta, tz_offset_min, filtros.correo)
    filas = datos["filas"]
    # Sin alguna de las fechas, el relleno va del primer al último día con datos.
    dias_con_datos = [f["dia"] for f in filas]
    primero = primero or min(dias_con_datos, default=None)
    ultimo = ultimo or max(dias_con_datos, default=None)
    if primero is None or ultimo is None or primero > ultimo:
        dias: list[date] = []
    else:
        _error_rango_series(
            primero, ultimo, f"El rango no puede superar los {MAX_DIAS_SERIES} días: indica «desde» y «hasta»."
        )
        dias = [primero + timedelta(days=i) for i in range((ultimo - primero).days + 1)]
    indice = {d: i for i, d in enumerate(dias)}

    def vacia() -> dict[str, list[int]]:
        return {"sesiones": [0] * len(dias), "segundos": [0] * len(dias), "usuarios": [0] * len(dias)}

    por_portal = {p: vacia() for p in datos["portales"]}
    total = vacia()
    for f in filas:
        i = indice.get(f["dia"])
        if i is None:
            continue
        destino = total if f["portal"] is None else por_portal.setdefault(f["portal"], vacia())
        for campo in ("sesiones", "segundos", "usuarios"):
            destino[campo][i] = f[campo]
    return {
        "dias": [d.isoformat() for d in dias],
        "portales": [{"portal": p, **s} for p, s in sorted(por_portal.items(), key=lambda x: x[0].casefold())],
        "total": total,
    }


@app.get("/api/estadisticas/distribucion")
def api_estadisticas_distribucion(
    admin: dict = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_distribucion),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    datos = db.estadisticas_distribucion(
        filtros.portal, filtros.desde, filtros.hasta, tz_offset_min, filtros.correo
    )
    return {
        "portal": filtros.portal,
        "correo": filtros.correo,
        "cierres": datos["cierres"],
        "duracion": {
            "rangos": [
                {"etiqueta": etiqueta, "sesiones": n} for etiqueta, n in zip(ETIQUETAS_DURACION, datos["duracion"])
            ],
            "sinActividad": datos["sinActividad"],
            "sinMedir": datos["sinMedir"],
        },
        "calor": datos["calor"],
    }

# ---------------------------------------------------------------------------
# Consulta de base de datos (v19, solo lectura: app/consulta_bd.py)
# ---------------------------------------------------------------------------


@app.get("/api/consulta-bd/tablas")
def api_consulta_bd_tablas(admin: dict = Depends(require_admin)):
    """Lista cerrada de tablas (sale del catálogo; no consulta la base)."""
    return {
        "tope": consulta_bd.TOPE_FILAS,
        "tablas": [
            {"clave": t.nombre, "nombre": t.nombre_completo, "camposBusqueda": list(t.busqueda)}
            for t in consulta_bd.TABLAS.values()
        ],
    }


@app.get("/api/consulta-bd/filas")
def api_consulta_bd_filas(
    admin: dict = Depends(require_admin),
    tabla: str | None = None,
    q: str | None = None,
):
    """Últimos 500 registros de la tabla, o hasta 500 coincidencias de `q` (contiene) en sus columnas de búsqueda."""
    errores: dict[str, str] = {}
    clave = (tabla or "").strip()
    elegida = consulta_bd.TABLAS.get(clave)
    if not clave:
        errores["tabla"] = "Elige una tabla."
    elif elegida is None:
        errores["tabla"] = "La tabla no está disponible para consulta."
    texto = (q or "").strip() or None
    if texto is not None:
        if len(texto) > consulta_bd.MAX_LARGO_BUSQUEDA:
            errores["q"] = f"La búsqueda admite hasta {consulta_bd.MAX_LARGO_BUSQUEDA} caracteres."
        elif elegida is not None and not elegida.busqueda:
            errores["q"] = "Esta tabla no tiene columnas para buscar."
    if errores:
        raise ErrorValidacion(errores)

    datos = consulta_bd.consultar(elegida, texto)
    # Nunca se registra el texto buscado.
    log.info(
        "Consulta de base de datos: %s (%s filas%s)",
        elegida.nombre_completo, len(datos["filas"]), ", con búsqueda" if texto else "",
    )
    return {
        "tabla": elegida.nombre_completo,
        "clave": elegida.nombre,
        "columnas": [{"nombre": c, "tipo": t} for c, t in elegida.columnas],
        "camposBusqueda": list(elegida.busqueda),
        "busqueda": texto,
        "tope": consulta_bd.TOPE_FILAS,
        "mostrando": len(datos["filas"]),
        "total": datos["total"],
        "totalTabla": datos["totalTabla"],
        "filas": datos["filas"],
    }
