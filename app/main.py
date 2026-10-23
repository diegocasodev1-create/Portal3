"""App FastAPI: middlewares de sesión y seguridad, rutas de autenticación, API y archivos estáticos."""

import logging
from html import escape
from http import HTTPStatus
from pathlib import Path

import pyodbc
from fastapi import Depends, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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


_INDEX_HTML = _leer_plantilla(STATIC_DIR / "index.html")
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
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
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


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    if not settings.auth_enabled:
        return HTMLResponse(_INDEX_HTML)
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
    return HTMLResponse(_INDEX_HTML)


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
