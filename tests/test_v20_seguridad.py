"""v20: correcciones de la revisión de seguridad (R1, R3, R4, R5, R6, R7, R10, R11, R16)."""

import logging
import re
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app import auth, claves, consulta_bd, db
from tests.conftest import ADMIN, CLAVE_ADMIN, CSRF, ingresar, poner_sesion
from tests.test_consulta_bd import CursorBD, lectura  # noqa: F401  (fixture)
from tests.test_latido import LLAVE, ORIGEN_ENERGIA, RUTA, latir, mirastock

RAIZ = Path(__file__).resolve().parent.parent
POR_DEFECTO = "Admin@123456"
NUEVA = "Nueva#Clave2026"


def cookie(cliente, datos):
    cliente.cookies.set(auth.COOKIE_SESION, auth._serializador().dumps(datos), domain="testserver.local", path="/")


def datos_cookie(resp):
    return auth._serializador().loads(resp.cookies[auth.COOKIE_SESION])


def max_age(resp):
    return int(re.search(r"max-age=(\d+)", resp.headers["set-cookie"], re.I).group(1))


# ---------------------------------------------------------------------------
# R1: la contraseña por defecto no se publica y vence a las 24 h
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("archivo", sorted((RAIZ / "app" / "static").rglob("*.*")), ids=lambda p: p.name)
def test_r1_ningun_archivo_publico_trae_la_contrasena_por_defecto(archivo):
    if archivo.suffix in (".png", ".jpg"):
        return
    assert POR_DEFECTO not in archivo.read_text(encoding="utf-8", errors="ignore")


def test_r1_el_servidor_sigue_rechazando_la_contrasena_por_defecto(cliente_admin):
    resp = cliente_admin.post("/api/auth/cambiar-contrasena", headers=CSRF,
                              json={"actual": CLAVE_ADMIN, "nueva": POR_DEFECTO, "confirmacion": POR_DEFECTO})
    assert resp.status_code == 422
    assert resp.json()["errores"]["nueva"] == "No puedes usar la contraseña por defecto."


@pytest.mark.parametrize("horas, entra", [(1, True), (23, True), (25, False), (71, False)])
def test_r1_contrasena_por_defecto_vale_24_horas(cliente, bd, horas, entra):
    bd.agregar_admin("nuevo.admin@miragroup.cl", "Nuevo", POR_DEFECTO, algoritmo="SHA2_512", debe_cambiar=True,
                     fecha_alta=bd.ahora - timedelta(hours=horas))
    resp = ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena=POR_DEFECTO)
    assert resp.status_code == (200 if entra else 401)
    if not entra:
        assert "24 horas" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# R3: mismo costo de verificación para cualquier algoritmo o clave
# ---------------------------------------------------------------------------

@pytest.fixture
def pbkdf2(monkeypatch):
    llamadas = []
    original = claves.hashlib.pbkdf2_hmac

    def espia(*a, **kw):
        llamadas.append(a[2])  # la sal
        return original(*a, **kw)

    monkeypatch.setattr(claves.hashlib, "pbkdf2_hmac", espia)
    return llamadas


@pytest.mark.parametrize("algoritmo, clave, sal, esperado", [
    ("SHA2_512", "Admin@123456", b"s" * 32, b"x" * 64),
    ("DESCONOCIDO", "Admin@123456", b"s" * 32, b"x" * 64),
    ("PBKDF2_SHA256", "", b"s" * 32, b"x" * 32),
    ("PBKDF2_SHA256", "A" * 129, b"s" * 32, b"x" * 32),
    ("PBKDF2_SHA256", "Clave#2026x", b"", b"x" * 32),
])
def test_r3_verificar_siempre_gasta_un_pbkdf2(pbkdf2, algoritmo, clave, sal, esperado):
    assert claves.verificar(algoritmo, clave, sal, esperado) is False
    assert pbkdf2 == [claves._SAL_RELLENO]


def test_r3_pbkdf2_real_no_se_calcula_dos_veces(pbkdf2):
    sal = b"\x01" * 32
    esperado = claves.calcular("PBKDF2_SHA256", "Clave#2026x", sal)
    pbkdf2.clear()
    assert claves.verificar("PBKDF2_SHA256", "Clave#2026x", sal, esperado) is True
    assert pbkdf2 == [sal]


def test_r3_sha2_correcta_sigue_verificando(pbkdf2):
    sal = b"\x02" * 32
    assert claves.verificar("SHA2_512", POR_DEFECTO, sal, claves.calcular("SHA2_512", POR_DEFECTO, sal)) is True
    assert pbkdf2 == [claves._SAL_RELLENO]


def test_r3_login_de_admin_sha2_cuesta_un_pbkdf2(cliente, bd, pbkdf2):
    bd.agregar_admin("nuevo.admin@miragroup.cl", "Nuevo", POR_DEFECTO, algoritmo="SHA2_512", debe_cambiar=True)
    for clave in ("Mala#Clave2026", POR_DEFECTO):
        pbkdf2.clear()
        ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena=clave)
        assert pbkdf2 == [claves._SAL_RELLENO]


def test_r3_correo_desconocido_cuesta_lo_mismo(cliente, bd, pbkdf2):
    ingresar(cliente, correo="nadie@miragroup.cl", contrasena="Mala#Clave2026")
    assert pbkdf2 == [claves._SAL_RELLENO]


# ---------------------------------------------------------------------------
# R4: tope absoluto de 12 h desde el ingreso
# ---------------------------------------------------------------------------

def test_r4_duracion_maxima():
    assert auth.DURACION_MAXIMA_SESION_S == 12 * 60 * 60


@pytest.mark.parametrize("hace_s, valida", [
    (0, True), (11 * 3600, True), (12 * 3600 - 60, True), (12 * 3600, False), (13 * 3600, False), (-3600, False),
])
def test_r4_cookie_con_ingreso_antiguo_no_sirve(cliente, bd, hace_s, valida):
    # La firma es reciente (no venció por inactividad): solo decide la hora de ingreso.
    admin = bd.admins[1]
    cookie(cliente, {"id": 1, "h": auth.huella(admin["ContrasenaHash"]), "i": int(time.time()) - hace_s})
    assert cliente.get("/api/me").status_code == (200 if valida else 401)


@pytest.mark.parametrize("i", [None, "123", 1.5, True])
def test_r4_cookie_sin_hora_de_ingreso_valida_no_sirve(cliente, bd, i):
    datos = {"id": 1, "h": auth.huella(bd.admins[1]["ContrasenaHash"])}
    if i is not None:
        datos["i"] = i
    cookie(cliente, datos)
    assert cliente.get("/api/me").status_code == 401


def test_r4_cookie_anterior_a_v20_no_sirve(cliente, bd):
    cookie(cliente, {"id": 1, "h": auth.huella(bd.admins[1]["ContrasenaHash"])})
    resp = cliente.get("/", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


def test_r4_la_renovacion_conserva_la_hora_de_ingreso(cliente, bd):
    inicio = int(time.time()) - 3 * 3600
    cookie(cliente, auth.datos_sesion(bd.admins[1], inicio))
    resp = cliente.get("/api/me")
    assert resp.status_code == 200
    assert datos_cookie(resp)["i"] == inicio
    assert max_age(resp) == 3600


def test_r4_la_cookie_no_dura_mas_que_el_tope(cliente, bd):
    inicio = int(time.time()) - (12 * 3600 - 600)  # quedan 10 min
    cookie(cliente, auth.datos_sesion(bd.admins[1], inicio))
    resp = cliente.get("/api/me")
    assert resp.status_code == 200
    assert 590 <= max_age(resp) <= 600


def test_r4_ingresar_fija_la_hora_de_ingreso(cliente, bd):
    resp = ingresar(cliente)
    assert abs(datos_cookie(resp)["i"] - time.time()) < 60
    assert max_age(resp) == 3600


def test_r4_cambiar_contrasena_no_reinicia_el_tope(cliente, bd):
    inicio = int(time.time()) - 5 * 3600
    cookie(cliente, auth.datos_sesion(bd.admins[1], inicio))
    resp = cliente.post("/api/auth/cambiar-contrasena", headers=CSRF,
                        json={"actual": CLAVE_ADMIN, "nueva": NUEVA, "confirmacion": NUEVA})
    assert resp.status_code == 200
    datos = datos_cookie(resp)
    assert datos["i"] == inicio and datos["h"] == auth.huella(bd.admins[1]["ContrasenaHash"])
    assert cliente.get("/api/me").status_code == 200


def test_r4_verificar_la_propia_card_no_reinicia_el_tope(cliente, bd):
    # Admin con SHA2_512 propio: al verificar su card se migra a PBKDF2 y se reemite su cookie.
    aid = bd.agregar_admin("sql@miragroup.cl", "Desde SQL", "Propia#Clave2026", algoritmo="SHA2_512")
    inicio = int(time.time()) - 2 * 3600
    cookie(cliente, auth.datos_sesion(bd.admins[aid], inicio))
    resp = cliente.post(f"/api/administradores/{aid}/verificar", headers=CSRF, json={"contrasena": "Propia#Clave2026"})
    assert resp.status_code == 200
    assert bd.admins[aid]["AlgoritmoHash"] == "PBKDF2_SHA256"
    assert datos_cookie(resp)["i"] == inicio


def test_r4_editar_la_propia_contrasena_no_reinicia_el_tope(cliente, bd):
    inicio = int(time.time()) - 2 * 3600
    cookie(cliente, auth.datos_sesion(bd.admins[1], inicio))
    permiso = cliente.post("/api/administradores/1/verificar", headers=CSRF, json={"contrasena": CLAVE_ADMIN}).json()["permiso"]
    resp = cliente.put("/api/administradores/1", headers=CSRF, json={
        "permiso": permiso, "nombre": bd.admins[1]["Nombre"], "correo": ADMIN,
        "nuevaContrasena": NUEVA, "confirmacion": NUEVA,
    })
    assert resp.status_code == 200
    assert datos_cookie(resp)["i"] == inicio
    assert cliente.get("/api/me").status_code == 200


# ---------------------------------------------------------------------------
# R5: límite por IP en /api/latido
# ---------------------------------------------------------------------------

def test_r5_limite_de_latidos():
    assert (auth.limite_latidos.maximo, auth.limite_latidos.ventana_s) == (60, 60)


def test_r5_el_latido_61_de_la_misma_ip_recibe_429(cliente, bd):
    ip = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(60):
        assert latir(cliente, mirastock(), headers=ip).status_code == 204
    llamadas = len(bd.llamadas_latido)
    resp = latir(cliente, mirastock(), headers=ip)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Demasiados latidos desde tu conexión."}
    assert len(bd.llamadas_latido) == llamadas  # no toca la BD
    # Otra IP sigue pasando (la última de X-Forwarded-For es la que agrega el ingress).
    assert latir(cliente, mirastock(), headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.8"}).status_code == 204


def test_r5_tambien_cuentan_los_latidos_invalidos(cliente, bd):
    ip = {"X-Forwarded-For": "203.0.113.9"}
    for _ in range(60):
        assert latir(cliente, {"tipo": "otro"}, headers=ip).status_code == 400
    assert latir(cliente, mirastock(), headers=ip).status_code == 429


def test_r5_el_429_trae_cors_para_el_origen_permitido(cliente, bd):
    ip = {"X-Forwarded-For": "203.0.113.10", "Origin": ORIGEN_ENERGIA}
    for _ in range(60):
        latir(cliente, mirastock(), headers=ip)
    resp = latir(cliente, mirastock(), headers=ip)
    assert resp.status_code == 429
    assert resp.headers["access-control-allow-origin"] == ORIGEN_ENERGIA


def test_r5_el_limite_no_afecta_al_login(cliente, bd):
    for _ in range(60):
        latir(cliente, mirastock(), headers={"X-Forwarded-For": "203.0.113.11"})
    assert ingresar(cliente).status_code == 200


# ---------------------------------------------------------------------------
# R6: renovación de la llave de MiraStock con tope CreadoEn + 4 h y nunca si ya venció
# ---------------------------------------------------------------------------

def test_r6_tope_de_4_horas():
    assert db.HORAS_MAXIMAS_LLAVE_MIRASTOCK == 4


@pytest.mark.parametrize("creada_hace_min, expira_en_min, esperado_min", [
    (60, 5, 30),        # normal: ahora + 30
    (215, 5, 25),       # 3 h 35 min: ahora + 30 pasaría de CreadoEn + 4 h → se queda en CreadoEn + 4 h
    (235, 3, 5),        # 3 h 55 min: CreadoEn + 4 h = ahora + 5
    (245, 3, 3),        # pasó las 4 h: ExpiraEn no se mueve
    (60, 45, 45),       # nunca acorta
    (60, -1, -1),       # ya venció: no se renueva
    (30, 0, 0),         # vence justo ahora: tampoco
])
def test_r6_renovacion_de_la_llave(cliente, bd, creada_hace_min, expira_en_min, esperado_min):
    bd.agregar_sesion_agente(LLAVE, bd.ahora - timedelta(minutes=creada_hace_min),
                             final_sesion=bd.ahora - timedelta(minutes=2),
                             expira_en=bd.ahora + timedelta(minutes=expira_en_min))
    assert latir(cliente, mirastock()).status_code == 204
    sesion = bd.sesiones_agente[LLAVE]
    assert sesion["FinalSesion"] == bd.ahora  # el latido igual mide la sesión
    assert sesion["ExpiraEn"] == bd.ahora + timedelta(minutes=esperado_min)


def test_r6_una_llave_filtrada_no_vive_mas_de_4_horas(cliente, bd):
    # Latidos cada 5 min durante 12 h: la llave deja de renovarse a las 4 h y vence.
    creada = bd.ahora
    bd.agregar_sesion_agente(LLAVE, creada)
    for _ in range(12 * 12):
        bd.ahora += timedelta(minutes=5)
        latir(cliente, mirastock())
    assert bd.sesiones_agente[LLAVE]["ExpiraEn"] == creada + timedelta(hours=4)


# ---------------------------------------------------------------------------
# R7: /consulta-bd sin las 3 columnas y con el Id del administrador en el log
# ---------------------------------------------------------------------------

def test_r7_columnas_de_administradores():
    columnas = [c for c, _ in consulta_bd.TABLAS["AdministradoresPortal"].columnas]
    assert columnas == ["Id", "Nombre", "Correo", "DebeCambiarContrasena", "Activo", "UltimoAcceso",
                        "FechaCambioContrasena", "FechaAlta"]
    for oculta in ("AlgoritmoHash", "IntentosFallidos", "BloqueadoHasta"):
        assert oculta not in consulta_bd.SQL["AdministradoresPortal"].listar


def test_r7_el_log_registra_quien_consulta_sin_el_texto(cliente_admin, lectura, caplog):  # noqa: F811
    lectura["cursor"] = CursorBD(conteos=[53, 0], filas=[])
    with caplog.at_level(logging.INFO, logger="mira_admin"):
        cliente_admin.get("/api/consulta-bd/filas", params={"tabla": "UsuariosEntel", "q": "buscado-secreto"})
    mensajes = [r.getMessage() for r in caplog.records if r.name == "mira_admin"]
    assert "Consulta de base de datos: core.UsuariosEntel (0 filas, con búsqueda, por administrador Id=1)" in mensajes
    assert "buscado-secreto" not in caplog.text


# ---------------------------------------------------------------------------
# R10: HSTS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/login", "/health", "/api/me", "/static/styles.css", "/no-existe"])
def test_r10_hsts_en_todas_las_respuestas(cliente, ruta):
    assert cliente.get(ruta).headers["strict-transport-security"] == "max-age=31536000"


# ---------------------------------------------------------------------------
# R11: tope de 64 KB para los body de /api/*
# ---------------------------------------------------------------------------

def test_r11_body_de_mas_de_64_kb_413(cliente_admin, bd):
    cuerpo = b'{"correo": "' + b"a" * (64 * 1024) + b'"}'
    resp = cliente_admin.post("/api/usuarios", content=cuerpo,
                              headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 413
    assert resp.json() == {"detail": "El cuerpo de la solicitud es demasiado grande."}
    assert resp.headers["strict-transport-security"] == "max-age=31536000"


def test_r11_login_publico_tambien_tiene_tope(cliente, bd):
    cuerpo = b'{"correo": "x", "contrasena": "' + b"a" * (64 * 1024) + b'"}'
    resp = cliente.post("/api/auth/login", content=cuerpo, headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 413


def test_r11_64_kb_justos_pasan_el_filtro(cliente_admin, bd):
    base = b'{"correo": "'
    cuerpo = base + b"a" * (64 * 1024 - len(base) - 2) + b'"}'
    assert len(cuerpo) == 64 * 1024
    resp = cliente_admin.post("/api/usuarios", content=cuerpo, headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 422  # llega a la validación normal


def test_r11_sin_content_length_411(cliente, bd):
    def trozos():
        yield b'{"correo": "x", '
        yield b'"contrasena": "y"}'

    resp = cliente.post("/api/auth/login", content=trozos(), headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 411


def test_r11_el_latido_mantiene_su_propio_tope(cliente, bd):
    # Sin Content-Length (por partes) el latido sigue aceptándose y cortándose en 8 KB.
    def trozos():
        yield b'{"tipo": "mirastock", '
        yield b'"t": "' + LLAVE.encode() + b'"}'

    assert cliente.post(RUTA, content=trozos(), headers={"Content-Type": "application/json"}).status_code == 204


def test_r11_get_no_se_ve_afectado(cliente_admin, bd):
    assert cliente_admin.get("/api/usuarios").status_code == 200


# ---------------------------------------------------------------------------
# R16: .gitignore
# ---------------------------------------------------------------------------

def test_r16_gitignore():
    lineas = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    for linea in (".env", ".env.*", "!.env.example", "body.json"):
        assert linea in lineas
    assert lineas.index(".env.*") < lineas.index("!.env.example")
