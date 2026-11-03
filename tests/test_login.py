"""Login propio (v12): credenciales, bloqueo, contraseña por defecto, migración a PBKDF2, límite por IP
y cambio obligatorio de contraseña."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import auth, claves, db
from app.main import app
from tests.conftest import ADMIN, CLAVE_ADMIN, CSRF, ingresar, poner_sesion

GENERICO = "Correo o contraseña incorrectos."
POR_DEFECTO = "Admin@123456"
NUEVA = "Nueva#Clave2026"


def admin_por_defecto(bd, correo="nuevo.admin@miragroup.cl", **extra):
    """Como lo deja core.sp_CrearAdministrador: SHA2_512, Admin@123456 y DebeCambiarContrasena = 1."""
    return bd.agregar_admin(correo, "Nuevo Admin", POR_DEFECTO, algoritmo="SHA2_512", debe_cambiar=True, **extra)


# ---------------------------------------------------------------------------
# Credenciales
# ---------------------------------------------------------------------------

def test_login_correcto(cliente, bd):
    bd.admins[1]["IntentosFallidos"] = 3
    resp = ingresar(cliente)
    assert resp.status_code == 200
    assert resp.json() == {"redirect": "/", "debeCambiarContrasena": False}
    assert auth.COOKIE_SESION in resp.cookies
    assert bd.admins[1]["IntentosFallidos"] == 0
    assert bd.admins[1]["UltimoAcceso"] == bd.ahora
    assert cliente.get("/api/me").json()["nombre"] == "Ana Admin"
    assert cliente.get("/").status_code == 200


def test_correo_se_normaliza(cliente, bd):
    assert ingresar(cliente, correo="  ADMIN@Ejemplo.COM ").status_code == 200


def test_contrasena_no_se_recorta(cliente, bd):
    assert ingresar(cliente, contrasena=f" {CLAVE_ADMIN} ").status_code == 401


def test_contrasena_incorrecta(cliente, bd):
    resp = ingresar(cliente, contrasena="Otra#Clave2026")
    assert resp.status_code == 401
    assert resp.json()["detail"] == GENERICO
    assert auth.COOKIE_SESION not in resp.cookies
    assert bd.admins[1]["IntentosFallidos"] == 1
    assert bd.admins[1]["UltimoAcceso"] is None
    assert cliente.get("/api/me").status_code == 401


def test_correo_desconocido_mismo_mensaje_y_mismo_costo(cliente, bd, monkeypatch):
    gastos = []
    monkeypatch.setattr(claves, "gastar_tiempo", lambda clave: gastos.append(1))
    resp = ingresar(cliente, correo="nadie@miragroup.cl")
    assert resp.status_code == 401
    assert resp.json()["detail"] == GENERICO
    assert gastos == [1]


def test_admin_inactivo_no_entra_y_no_suma_intentos(cliente, bd, monkeypatch):
    bd.admins[1]["Activo"] = False
    gastos = []
    monkeypatch.setattr(claves, "gastar_tiempo", lambda clave: gastos.append(1))
    resp = ingresar(cliente)
    assert resp.status_code == 401
    assert resp.json()["detail"] == GENERICO
    assert bd.admins[1]["IntentosFallidos"] == 0
    assert gastos == [1]


@pytest.mark.parametrize("cuerpo", [{}, {"correo": ADMIN}, {"contrasena": CLAVE_ADMIN}, {"correo": "", "contrasena": ""}])
def test_datos_incompletos_mensaje_generico(cliente, bd, cuerpo):
    resp = cliente.post("/api/auth/login", json=cuerpo, headers=CSRF)
    assert resp.status_code == 401
    assert resp.json()["detail"] == GENERICO


def test_contrasena_de_tipo_invalido_422(cliente, bd):
    resp = cliente.post("/api/auth/login", json={"correo": ADMIN, "contrasena": 123}, headers=CSRF)
    assert resp.status_code == 422


def test_login_exige_csrf(cliente, bd):
    resp = cliente.post("/api/auth/login", json={"correo": ADMIN, "contrasena": CLAVE_ADMIN})
    assert resp.status_code == 403
    assert auth.COOKIE_SESION not in resp.cookies


def test_contrasena_muy_larga_no_se_calcula(cliente, bd, monkeypatch):
    llamadas = []
    original = claves.calcular
    monkeypatch.setattr(claves, "calcular", lambda *a: llamadas.append(a[0]) or original(*a))
    assert ingresar(cliente, contrasena="A" * 5000).status_code == 401
    assert llamadas == []  # verificar descarta > 128 caracteres sin calcular
    assert bd.admins[1]["IntentosFallidos"] == 1


# ---------------------------------------------------------------------------
# Redirección después del login
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("siguiente, destino", [
    ("/contactos", "/contactos"),
    ("/administradores", "/administradores"),
    ("//evil.example.com", "/"),
    ("/\\evil.example.com", "/"),
    ("https://evil.example.com", "/"),
    ("evil", "/"),
    ("/login", "/"),
    ("/api/usuarios", "/"),
    ("", "/"),
])
def test_siguiente_solo_acepta_rutas_internas(cliente, bd, siguiente, destino):
    assert ingresar(cliente, siguiente=siguiente).json()["redirect"] == destino


# ---------------------------------------------------------------------------
# Bloqueo: 5 intentos → 15 minutos
# ---------------------------------------------------------------------------

def test_cinco_fallos_bloquean_15_minutos(cliente, bd):
    for _ in range(5):
        assert ingresar(cliente, contrasena="Mala#Clave2026").status_code == 401
    assert bd.admins[1]["IntentosFallidos"] == 5
    assert bd.admins[1]["BloqueadoHasta"] == bd.ahora + timedelta(minutes=15)
    # Bloqueado: ni la contraseña correcta entra, el mensaje es el mismo y no se suman intentos.
    resp = ingresar(cliente)
    assert resp.status_code == 401
    assert resp.json()["detail"] == GENERICO
    assert bd.admins[1]["IntentosFallidos"] == 5


def test_cuatro_fallos_no_bloquean(cliente, bd):
    for _ in range(4):
        ingresar(cliente, contrasena="Mala#Clave2026")
    assert bd.admins[1]["BloqueadoHasta"] is None
    assert ingresar(cliente).status_code == 200
    assert bd.admins[1]["IntentosFallidos"] == 0


def test_bloqueo_vencido_permite_entrar_y_reinicia(cliente, bd):
    bd.admins[1].update(IntentosFallidos=5, BloqueadoHasta=bd.ahora - timedelta(seconds=1))
    assert ingresar(cliente).status_code == 200
    assert bd.admins[1]["IntentosFallidos"] == 0 and bd.admins[1]["BloqueadoHasta"] is None


def test_fallo_despues_de_un_bloqueo_vencido_empieza_la_cuenta_de_nuevo(cliente, bd):
    bd.admins[1].update(IntentosFallidos=5, BloqueadoHasta=bd.ahora - timedelta(minutes=1))
    ingresar(cliente, contrasena="Mala#Clave2026")
    assert bd.admins[1]["IntentosFallidos"] == 1
    assert bd.admins[1]["BloqueadoHasta"] is None


def test_sql_del_fallo_y_del_exito(monkeypatch):
    sql = db._SQL_FALLO_ADMIN
    assert "IntentosFallidos" in sql and ">= 5" in sql and "DATEADD(MINUTE, 15, SYSUTCDATETIME())" in sql
    # No suma intentos mientras está bloqueado; un bloqueo vencido empieza la cuenta en 1.
    assert "WHERE Id = ? AND (BloqueadoHasta IS NULL OR BloqueadoHasta <= SYSUTCDATETIME())" in sql
    assert "WHEN BloqueadoHasta <= SYSUTCDATETIME() THEN 1" in sql
    assert "DATEADD(HOUR, 72, COALESCE(FechaCambioContrasena, FechaAlta))" in db._COLUMNAS_ADMIN


def test_sql_de_exito_migracion_y_cambio(monkeypatch):
    from contextlib import contextmanager

    ejecutados = []

    class Cursor:
        rowcount = 1

        def execute(self, sql, *params):
            ejecutados.append((sql, params))

    @contextmanager
    def conexion():
        class Conn:
            def cursor(self):
                return Cursor()
        yield Conn()

    monkeypatch.setattr(db, "_conexion", conexion)
    db.registrar_exito_admin(4, True)
    db.registrar_exito_admin(4, False)
    assert "UltimoAcceso = SYSUTCDATETIME()" in ejecutados[0][0]
    assert "UltimoAcceso" not in ejecutados[1][0]
    assert db.migrar_hash_admin(4, b"viejo", b"nuevo", b"sal", "PBKDF2_SHA256")
    sql, params = ejecutados[2]
    assert "AND ContrasenaHash = ?" in sql and "DebeCambiarContrasena, 0) = 0" in sql
    assert bytes(params[4]) == b"viejo"
    db.cambiar_contrasena_admin(4, b"h", b"s", "PBKDF2_SHA256")
    sql, params = ejecutados[3]
    assert "DebeCambiarContrasena = 0" in sql and "FechaCambioContrasena = SYSUTCDATETIME()" in sql
    assert "IntentosFallidos = 0" in sql and params[-1] == 4


# ---------------------------------------------------------------------------
# Contraseña por defecto (creado o restablecido por SQL)
# ---------------------------------------------------------------------------

def test_por_defecto_entra_y_debe_cambiarla(cliente, bd):
    aid = admin_por_defecto(bd)
    resp = ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena=POR_DEFECTO)
    assert resp.status_code == 200
    assert resp.json() == {"redirect": "/cambiar-contrasena", "debeCambiarContrasena": True}
    # Mientras deba cambiarla, el hash queda en SHA2_512 (lo reemplaza el cambio).
    assert bd.admins[aid]["AlgoritmoHash"] == "SHA2_512"


def test_por_defecto_vence_a_las_72_horas(cliente, bd):
    aid = admin_por_defecto(bd, fecha_alta=bd.ahora - timedelta(hours=73))
    resp = ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena=POR_DEFECTO)
    assert resp.status_code == 401
    assert "venció" in resp.json()["detail"]
    assert auth.COOKIE_SESION not in resp.cookies
    assert bd.admins[aid]["IntentosFallidos"] == 0  # la contraseña era correcta: no es un intento fallido


def test_por_defecto_restablecida_cuenta_desde_el_restablecimiento(cliente, bd):
    # Con el ALTER propuesto, sp_RestablecerContrasenaAdmin actualiza FechaCambioContrasena.
    admin_por_defecto(bd, fecha_alta=bd.ahora - timedelta(days=30), fecha_cambio=bd.ahora - timedelta(hours=2))
    assert ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena=POR_DEFECTO).status_code == 200


def test_por_defecto_vencida_y_contrasena_mala_suma_intento(cliente, bd):
    aid = admin_por_defecto(bd, fecha_alta=bd.ahora - timedelta(hours=73))
    assert ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena="Mala#Clave2026").json()["detail"] == GENERICO
    assert bd.admins[aid]["IntentosFallidos"] == 1


def test_sha2_ya_cambiada_se_migra_a_pbkdf2_al_entrar(cliente, bd):
    aid = bd.agregar_admin("sql@miragroup.cl", "Desde SQL", "Propia#Clave2026", algoritmo="SHA2_512")
    resp = ingresar(cliente, correo="sql@miragroup.cl", contrasena="Propia#Clave2026")
    assert resp.status_code == 200
    a = bd.admins[aid]
    assert a["AlgoritmoHash"] == "PBKDF2_SHA256" and len(a["ContrasenaSal"]) == 32
    assert claves.verificar(a["AlgoritmoHash"], "Propia#Clave2026", a["ContrasenaSal"], a["ContrasenaHash"])
    # La cookie se emitió con el hash nuevo: la sesión sigue valiendo.
    assert cliente.get("/api/me").status_code == 200
    cliente.cookies.clear()
    assert ingresar(cliente, correo="sql@miragroup.cl", contrasena="Propia#Clave2026").status_code == 200


def test_si_la_migracion_no_aplica_la_sesion_usa_el_hash_vigente(cliente, bd, monkeypatch):
    aid = bd.agregar_admin("sql@miragroup.cl", "Desde SQL", "Propia#Clave2026", algoritmo="SHA2_512")
    monkeypatch.setattr(db, "migrar_hash_admin", lambda *a: False)
    assert ingresar(cliente, correo="sql@miragroup.cl", contrasena="Propia#Clave2026").status_code == 200
    assert bd.admins[aid]["AlgoritmoHash"] == "SHA2_512"
    assert cliente.get("/api/me").status_code == 200


# ---------------------------------------------------------------------------
# Límite por IP
# ---------------------------------------------------------------------------

def test_limite_por_ip(cliente, bd):
    for _ in range(20):
        assert ingresar(cliente, correo="nadie@miragroup.cl").status_code == 401
    resp = ingresar(cliente)
    assert resp.status_code == 429
    assert "Demasiados intentos" in resp.json()["detail"]


def test_limite_por_ip_usa_la_ultima_ip_de_x_forwarded_for(cliente, bd):
    # El ingress agrega la IP real al final; la primera la puede inventar el cliente.
    for i in range(20):
        cliente.post("/api/auth/login", json={"correo": "x@y.cl", "contrasena": "x"},
                     headers={**CSRF, "X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"})
    resp = cliente.post("/api/auth/login", json={"correo": ADMIN, "contrasena": CLAVE_ADMIN},
                        headers={**CSRF, "X-Forwarded-For": "10.9.9.9, 203.0.113.7"})
    assert resp.status_code == 429
    otra_ip = cliente.post("/api/auth/login", json={"correo": ADMIN, "contrasena": CLAVE_ADMIN},
                           headers={**CSRF, "X-Forwarded-For": "198.51.100.4"})
    assert otra_ip.status_code == 200


def test_limite_por_ip_ventana_deslizante(monkeypatch):
    reloj = {"t": 1000.0}
    monkeypatch.setattr(auth.time, "monotonic", lambda: reloj["t"])
    limite = auth.LimitePorIp(maximo=2, ventana_s=60)
    assert limite.permitir("a") and limite.permitir("a")
    assert not limite.permitir("a")
    assert limite.permitir("b")
    reloj["t"] += 61
    assert limite.permitir("a")


# ---------------------------------------------------------------------------
# Cambio obligatorio de contraseña
# ---------------------------------------------------------------------------

@pytest.fixture
def cliente_por_defecto(cliente, bd):
    aid = admin_por_defecto(bd)
    poner_sesion(cliente, bd.admins[aid])
    cliente.aid = aid
    return cliente


@pytest.mark.parametrize("ruta", ["/", "/contactos", "/historial", "/estadisticas", "/administradores", "/login"])
def test_paginas_obligan_a_cambiar(cliente_por_defecto, ruta):
    resp = cliente_por_defecto.get(ruta, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/cambiar-contrasena"


@pytest.mark.parametrize("ruta", ["/api/usuarios", "/api/gerencias", "/api/historial", "/api/administradores"])
def test_api_obliga_a_cambiar(cliente_por_defecto, ruta):
    resp = cliente_por_defecto.get(ruta)
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Debes cambiar tu contraseña antes de continuar.", "cambioRequerido": True}


def test_api_de_escritura_obliga_a_cambiar(cliente_por_defecto, bd):
    resp = cliente_por_defecto.delete("/api/usuarios/1", headers={**CSRF, "Content-Type": "application/json"})
    assert resp.status_code == 403
    assert 1 in bd.usuarios


def test_puede_ver_su_nombre_y_la_pagina_de_cambio(cliente_por_defecto):
    assert cliente_por_defecto.get("/api/me").json()["debeCambiarContrasena"] is True
    resp = cliente_por_defecto.get("/cambiar-contrasena")
    assert resp.status_code == 200
    assert 'id="form-cambio"' in resp.text and '<script src="/static/cambiar.js?v=16"' in resp.text


def cambiar(cliente, actual=POR_DEFECTO, nueva=NUEVA, confirmacion=None):
    return cliente.post("/api/auth/cambiar-contrasena", headers=CSRF, json={
        "actual": actual, "nueva": nueva, "confirmacion": nueva if confirmacion is None else confirmacion,
    })


def test_cambio_correcto(cliente_por_defecto, bd):
    aid = cliente_por_defecto.aid
    with TestClient(app, base_url="https://testserver") as otra_sesion:
        poner_sesion(otra_sesion, bd.admins[aid])
        resp = cambiar(cliente_por_defecto)
        assert resp.status_code == 200
        assert resp.json() == {"mensaje": "Contraseña actualizada.", "redirect": "/"}
        a = bd.admins[aid]
        assert a["AlgoritmoHash"] == "PBKDF2_SHA256" and a["DebeCambiarContrasena"] is False
        assert a["FechaCambioContrasena"] == bd.ahora
        assert claves.verificar(a["AlgoritmoHash"], NUEVA, a["ContrasenaSal"], a["ContrasenaHash"])
        # Esta sesión sigue (cookie nueva) y ya puede usar la app; la otra sesión quedó cerrada.
        assert cliente_por_defecto.get("/api/usuarios").status_code == 200
        assert cliente_por_defecto.get("/", follow_redirects=False).status_code == 200
        assert otra_sesion.get("/api/me").status_code == 401


def test_cambio_con_actual_incorrecta_suma_intento(cliente_por_defecto, bd):
    resp = cambiar(cliente_por_defecto, actual="Mala#Clave2026")
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"actual": "La contraseña actual no es correcta."}
    assert bd.admins[cliente_por_defecto.aid]["IntentosFallidos"] == 1
    assert bd.admins[cliente_por_defecto.aid]["DebeCambiarContrasena"] is True


@pytest.mark.parametrize("nueva, mensaje", [
    ("Corta#1", "La contraseña debe tener al menos 10 caracteres."),
    ("sinmayuscula#2026", "La contraseña debe tener al menos una mayúscula."),
    ("SINMINUSCULA#2026", "La contraseña debe tener al menos una minúscula."),
    ("SinNumero#Clave", "La contraseña debe tener al menos un número."),
    ("SinSimbolo2026", "La contraseña debe tener al menos un símbolo."),
    (POR_DEFECTO, "No puedes usar la contraseña por defecto."),
])
def test_cambio_respeta_la_politica(cliente_por_defecto, bd, nueva, mensaje):
    resp = cambiar(cliente_por_defecto, nueva=nueva)
    assert resp.status_code == 422
    assert resp.json()["errores"]["nueva"] == mensaje
    assert bd.admins[cliente_por_defecto.aid]["AlgoritmoHash"] == "SHA2_512"
    assert bd.admins[cliente_por_defecto.aid]["IntentosFallidos"] == 0


def test_cambio_confirmacion_distinta(cliente_por_defecto):
    resp = cambiar(cliente_por_defecto, confirmacion="Otra#Clave2026")
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"confirmacion": "Las contraseñas no coinciden."}


def test_cambio_igual_a_la_actual(cliente_admin, bd):
    resp = cambiar(cliente_admin, actual=CLAVE_ADMIN, nueva=CLAVE_ADMIN)
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"nueva": "La contraseña nueva debe ser distinta de la actual."}


def test_cambio_igual_a_la_actual_no_sirve_para_adivinarla(cliente_admin, bd):
    # Con la actual mal, «distinta de la actual» no se evalúa: no revela si `nueva` es la contraseña.
    resp = cambiar(cliente_admin, actual="Mala#Clave2026", nueva=CLAVE_ADMIN)
    assert resp.json()["errores"] == {"actual": "La contraseña actual no es correcta."}


def test_cambio_voluntario(cliente_admin, bd):
    resp = cambiar(cliente_admin, actual=CLAVE_ADMIN)
    assert resp.status_code == 200
    assert cliente_admin.get("/api/me").status_code == 200
    cliente_admin.cookies.clear()
    assert ingresar(cliente_admin, contrasena=NUEVA).status_code == 200
    assert ingresar(cliente_admin, contrasena=CLAVE_ADMIN).status_code == 401


def test_cambio_sin_actual(cliente_por_defecto):
    resp = cambiar(cliente_por_defecto, actual="")
    assert resp.status_code == 422
    assert resp.json()["errores"]["actual"] == "Ingresa tu contraseña actual."


def test_flujo_completo_desde_el_login(cliente, bd):
    admin_por_defecto(bd)
    resp = ingresar(cliente, correo="nuevo.admin@miragroup.cl", contrasena=POR_DEFECTO)
    assert resp.json()["redirect"] == "/cambiar-contrasena"
    assert cliente.get("/contactos", follow_redirects=False).headers["location"] == "/cambiar-contrasena"
    assert cambiar(cliente).status_code == 200
    assert cliente.get("/contactos").status_code == 200
