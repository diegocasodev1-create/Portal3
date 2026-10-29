"""App FastAPI: middlewares de sesión y seguridad, rutas de autenticación, API y archivos estáticos."""

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from pathlib import Path

import pyodbc
from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth, db, externalid, mailer
from app.auth import require_admin
from app.config import get_settings
from app.schemas import UsuarioCrear, UsuarioEditar

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
if not settings.auth_enabled:
    log.warning("AUTH_ENABLED=false: la app no pide ingreso y /api/* no exige sesión.")

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

MSG_SIN_SESION = "Ingresa desde el Portal Corporativo para administrar usuarios."
MSG_TOKEN_INVALIDO = "No pudimos validar tu ingreso. Vuelve a entrar desde el Portal Corporativo."
MSG_BD_NO_DISPONIBLE = "No se pudo verificar tu acceso en este momento. Intenta nuevamente en unos minutos."

app = FastAPI(title="Administración de usuarios - MiraGroup", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Páginas HTML simples
# ---------------------------------------------------------------------------

def _leer_plantilla(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8").replace("{{PORTAL_URL}}", escape(settings.portal_base_url, quote=True))


_INICIO_HTML = _leer_plantilla(STATIC_DIR / "inicio.html")
_CONTACTOS_HTML = _leer_plantilla(STATIC_DIR / "contactos.html")
_HISTORIAL_HTML = _leer_plantilla(STATIC_DIR / "historial.html")
_SIN_ACCESO_HTML = _leer_plantilla(TEMPLATES_DIR / "sin_acceso.html")
_SIN_PERMISOS_HTML = _leer_plantilla(TEMPLATES_DIR / "sin_permisos.html")


def _pagina_sin_acceso(mensaje: str, status_code: int) -> HTMLResponse:
    return HTMLResponse(_SIN_ACCESO_HTML.replace("{{MENSAJE}}", escape(mensaje)), status_code=status_code)


def _pagina_sin_permisos() -> HTMLResponse:
    return HTMLResponse(_SIN_PERMISOS_HTML, status_code=403)


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
    # Sin autenticación no se lee ni se renueva la cookie.
    correo = auth.leer_sesion(request) if settings.auth_enabled else None
    request.state.correo = correo
    response = await call_next(request)
    # Expiración por inactividad: cada request válido renueva la cookie.
    # /auth/* administra la cookie por su cuenta (nueva sesión o cierre).
    path = request.url.path
    if correo and not path.startswith(("/auth/", "/static/")) and response.status_code not in (401, 403):
        auth.crear_cookie_sesion(response, correo)
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
# Rutas públicas y de autenticación
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


def _pagina_protegida(request: Request, html: str) -> HTMLResponse:
    """Con auth activa exige sesión y Portal3 = 1 y Activo = 1; con auth apagada sirve la página directo."""
    if not settings.auth_enabled:
        return HTMLResponse(html)
    correo = request.state.correo
    if not correo:
        return _pagina_sin_acceso(MSG_SIN_SESION, 200)
    try:
        es_admin = db.es_admin(correo)
    except pyodbc.Error as e:
        log.error("Error de base de datos al verificar acceso: %s", e.args[:1])
        return _pagina_sin_acceso(MSG_BD_NO_DISPONIBLE, 503)
    if not es_admin:
        return _pagina_sin_permisos()
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    return _pagina_protegida(request, _INICIO_HTML)


@app.get("/contactos", response_class=HTMLResponse)
def contactos(request: Request):
    return _pagina_protegida(request, _CONTACTOS_HTML)


@app.get("/historial", response_class=HTMLResponse)
def historial(request: Request):
    return _pagina_protegida(request, _HISTORIAL_HTML)


@app.post("/auth/portal")
def auth_portal(token: str = Form("")):
    try:
        correo = auth.validar_token_portal(token)
    except auth.TokenInvalido as e:
        log.warning("Token del portal rechazado: %s", e)
        return _pagina_sin_acceso(MSG_TOKEN_INVALIDO, 401)

    try:
        es_admin = db.es_admin(correo)
    except pyodbc.Error as e:
        log.error("Error de base de datos al verificar acceso: %s", e.args[:1])
        return _pagina_sin_acceso(MSG_BD_NO_DISPONIBLE, 503)

    if not es_admin:
        log.info("Ingreso rechazado: el usuario no tiene Portal3 activo")
        resp = _pagina_sin_permisos()
        auth.borrar_cookie_sesion(resp)
        return resp

    log.info("Ingreso desde el portal aceptado")
    resp = RedirectResponse("/", status_code=303)
    auth.crear_cookie_sesion(resp, correo)
    return resp


@app.post("/auth/logout")
def auth_logout():
    resp = JSONResponse({"redirect": settings.portal_base_url})
    auth.borrar_cookie_sesion(resp)
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


# `admin` es None cuando AUTH_ENABLED=false (no hay usuario identificado).

@app.get("/api/me")
def api_me(admin: str | None = Depends(require_admin)):
    if not settings.auth_enabled:
        return {"correo": None, "authEnabled": False}
    return {"correo": admin}


@app.get("/api/gerencias")
def api_gerencias(admin: str | None = Depends(require_admin)):
    return db.listar_gerencias()


@app.get("/api/usuarios")
def api_listar_usuarios(admin: str | None = Depends(require_admin)):
    return db.listar_usuarios()


@app.post("/api/usuarios", status_code=201)
def api_crear_usuario(datos: UsuarioCrear, admin: str | None = Depends(require_admin)):
    gerencia = _gerencia_valida(datos.gerencia)
    if db.existe_correo(datos.correo):
        raise ErrorCampo(409, "correo", "Ese correo ya está registrado.")
    try:
        usuario = db.crear_usuario(
            datos.correo, datos.nombre, datos.apellido, gerencia, datos.portal1, datos.portal2, datos.portal3
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
def api_editar_usuario(usuario_id: int, datos: UsuarioEditar, admin: str | None = Depends(require_admin)):
    actual = _usuario_o_404(usuario_id)
    if admin and actual["Correo"].lower() == admin and not datos.portal3:
        raise ErrorCampo(400, "portal3", "No puedes quitarte tu propio acceso a Administración de usuarios.")
    gerencia = _gerencia_valida(datos.gerencia)
    if not db.actualizar_usuario(
        usuario_id, datos.nombre, datos.apellido, gerencia, datos.portal1, datos.portal2, datos.portal3
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
def api_eliminar_usuario(usuario_id: int, admin: str | None = Depends(require_admin)):
    actual = _usuario_o_404(usuario_id)
    if admin and actual["Correo"].lower() == admin:
        raise StarletteHTTPException(status_code=400, detail="No puedes eliminar tu propio usuario.")
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
def api_enviar_correo(usuario_id: int, admin: str | None = Depends(require_admin)):
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
        llave = datos.get("t")
        try:
            llave = str(uuid.UUID(llave)) if isinstance(llave, str) else None
        except ValueError:
            llave = None
        if llave is None:
            raise _latido_invalido("La llave de sesión no es válida.")
        await run_in_threadpool(db.cierre_mirastock if cierre else db.latido_mirastock, llave)
        return Response(status_code=204)

    if tipo == "energia":
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

PORTALES_HISTORIAL = ("Energía", "MiraStock")
RESULTADOS_HISTORIAL = ("OK", "Denegado")
TAMANO_PAGINA_HISTORIAL = 50
TOPE_CSV_HISTORIAL = 50_000


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
        portal_ok = _valor_permitido(portal, PORTALES_HISTORIAL)
        if portal_ok is None:
            errores["portal"] = "El portal debe ser Energía o MiraStock."

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


def _texto_cierre(fila: dict) -> str:
    """Cómo terminó la sesión (mismos textos que la tabla de /historial; vacío si no hubo latidos)."""
    if fila["CierreExplicito"]:
        return "Botón"
    if fila["EnCurso"]:
        return "En curso"
    return "Inactividad" if fila["FinalSesion"] else ""


def _fecha_csv(fecha: datetime | None) -> str:
    return fecha.strftime("%Y-%m-%d %H:%M:%S") if fecha else ""


def _celda_csv(valor: str) -> str:
    """Neutraliza la inyección de fórmulas: Excel interpretaría = + - @ (y tab o CR) al inicio."""
    return "'" + valor if valor and valor[0] in "=+-@\t\r" else valor


# `admin` va primero: sin sesión responde 401 antes de validar los filtros.

@app.get("/api/historial")
def api_historial(
    admin: str | None = Depends(require_admin),
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
    admin: str | None = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_historial),
    tz_offset_min: int = Query(0, ge=-840, le=840),
):
    return db.resumen_historial(filtros, tz_offset_min)


@app.get("/api/historial/csv")
def api_historial_csv(
    admin: str | None = Depends(require_admin),
    filtros: db.FiltrosHistorial = Depends(_filtros_historial),
):
    filas, total = db.listar_historial(filtros, 1, TOPE_CSV_HISTORIAL)
    salida = io.StringIO()
    # Separador ';' y BOM: Excel en español abre el archivo con columnas y acentos correctos.
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([
        "Fecha (UTC)", "Usuario", "Correo", "Portal", "Resultado", "Final de sesión (UTC)", "Tiempo de sesión (min)",
        "Cierre",
    ])
    for f in filas:
        segundos = f["TiempoSesionSeg"]
        escritor.writerow([
            _fecha_csv(f["Fecha"]),
            *(_celda_csv(f[c] or "") for c in ("Usuario", "Correo", "Portal", "Resultado")),
            _fecha_csv(f["FinalSesion"]),
            # Minutos enteros truncados (40 s → 0); vacío si no hubo latidos.
            str(max(0, segundos) // 60) if segundos is not None else "",
            _texto_cierre(f),
        ])
    nombre = f"historial_accesos_{datetime.now(timezone.utc):%Y%m%d}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{nombre}"'}
    if total > TOPE_CSV_HISTORIAL:
        headers["X-Historial-Truncado"] = str(TOPE_CSV_HISTORIAL)
    log.info("Historial exportado a CSV (%s de %s filas)", len(filas), total)
    return Response(
        ("\ufeff" + salida.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8", headers=headers
    )
