"""Fixtures comunes: configuración de prueba, BD simulada, clave del portal y clientes HTTP."""

import os

# La configuración de prueba se define antes de importar la app (las variables de entorno
# tienen prioridad sobre el .env local, así los tests nunca usan credenciales reales).
os.environ.update(
    {
        "SQL_SERVER": "servidor-de-prueba",
        "SQL_DATABASE": "bd-de-prueba",
        "SQL_USER": "usuario-de-prueba",
        "SQL_PASSWORD": "clave-de-prueba",
        "PORTAL_BASE_URL": "https://portal.ejemplo.com",
        "TOKEN_AUDIENCE": "",
        "SESSION_SECRET": "secreto-de-prueba-" + "x" * 48,
        "SESSION_MAX_AGE_MIN": "60",
        "GRAPH_TENANT_ID": "tenant-de-prueba",
        "GRAPH_CLIENT_ID": "",
        "GRAPH_CLIENT_SECRET": "",
        "MAIL_SENDER": "no-reply@ejemplo.com",
        "MAIL_ENABLED": "false",
        "EXTID_ENABLED": "false",
        "EXTID_TENANT_ID": "tenant-externos-de-prueba",
        "EXTID_CLIENT_ID": "",
        "EXTID_CLIENT_SECRET": "",
        "EXTID_DOMAIN": "externos.ejemplo.com",
        "LOG_LEVEL": "WARNING",
    }
)

import time
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth, db, externalid, mailer
from app.config import get_settings
from app.main import app

ADMIN = "admin@ejemplo.com"
EMISOR = "portal.ejemplo.com"
CSRF = {"X-Requested-With": "mira-admin"}


def _nueva_clave():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return pem, privada.public_key()


CLAVE_PRIVADA, CLAVE_PUBLICA = _nueva_clave()
OTRA_CLAVE_PRIVADA, OTRA_CLAVE_PUBLICA = _nueva_clave()


def crear_token(claims=None, clave=CLAVE_PRIVADA, **extra):
    datos = {"iss": EMISOR, "exp": int(time.time()) + 600, "email": ADMIN}
    datos.update(claims or {})
    datos.update(extra)
    datos = {k: v for k, v in datos.items() if v is not None}
    return jwt.encode(datos, clave, algorithm="RS256")


class BDFalsa:
    """Reemplaza las funciones de app.db con datos en memoria."""

    def __init__(self):
        self.gerencias = ["Gerencia Comercial", "Gerencia de Operaciones", "Gerencia TI"]
        self.usuarios: dict[int, dict] = {}
        self._siguiente = 1
        self.agregar(ADMIN, "Ana", "Admin", "Gerencia TI", p3=True)

    def agregar(self, correo, nombre="Nombre", apellido="", gerencia="Gerencia TI",
                p1=False, p2=False, p3=False, activo=True, invitacion=False):
        uid = self._siguiente
        self._siguiente += 1
        self.usuarios[uid] = {
            "Id": uid, "Correo": correo, "Nombre": nombre, "Apellido": apellido, "Gerencia": gerencia,
            "Portal1": p1, "Portal2": p2, "Portal3": p3, "Activo": activo,
            "InvitacionEnviada": invitacion,
            "FechaAlta": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        return dict(self.usuarios[uid])

    def _por_correo(self, correo):
        return next((u for u in self.usuarios.values() if u["Correo"].lower() == correo.lower()), None)

    # --- funciones de app.db ---
    def es_admin(self, correo):
        u = self._por_correo(correo)
        return bool(u and u["Portal3"] and u["Activo"])

    def listar_gerencias(self):
        return sorted(self.gerencias)

    def listar_usuarios(self):
        return [dict(u) for u in sorted(self.usuarios.values(), key=lambda u: u["Id"], reverse=True)]

    def listar_usuarios_con_acceso(self):
        return [
            dict(u) for u in sorted(self.usuarios.values(), key=lambda u: u["Correo"])
            if u["Activo"] and (u["Portal1"] or u["Portal2"] or u["Portal3"])
        ]

    def obtener_usuario(self, uid):
        u = self.usuarios.get(uid)
        return dict(u) if u else None

    def existe_correo(self, correo):
        return self._por_correo(correo) is not None

    def crear_usuario(self, correo, nombre, apellido, gerencia, p1, p2, p3):
        if self._por_correo(correo):
            raise db.CorreoDuplicado()
        return self.agregar(correo, nombre, apellido, gerencia, p1, p2, p3)

    def actualizar_usuario(self, uid, nombre, apellido, gerencia, p1, p2, p3):
        u = self.usuarios.get(uid)
        if not u:
            return False
        u.update(Nombre=nombre, Apellido=apellido, Gerencia=gerencia, Portal1=p1, Portal2=p2, Portal3=p3)
        return True

    def eliminar_usuario(self, uid):
        return self.usuarios.pop(uid, None) is not None

    def marcar_invitacion_enviada(self, uid):
        self.usuarios[uid]["InvitacionEnviada"] = True


@pytest.fixture
def bd(monkeypatch):
    falsa = BDFalsa()
    for nombre in (
        "es_admin", "listar_gerencias", "listar_usuarios", "obtener_usuario", "existe_correo",
        "crear_usuario", "actualizar_usuario", "eliminar_usuario", "marcar_invitacion_enviada",
        "listar_usuarios_con_acceso",
    ):
        monkeypatch.setattr(db, nombre, getattr(falsa, nombre))
    return falsa


@pytest.fixture(autouse=True)
def clave_del_portal(monkeypatch):
    """Por defecto el portal entrega CLAVE_PUBLICA. Los tests pueden cambiar `estado['claves']`."""
    estado = {"claves": [CLAVE_PUBLICA], "descargas": 0}

    def descargar():
        i = min(estado["descargas"], len(estado["claves"]) - 1)
        estado["descargas"] += 1
        return estado["claves"][i]

    auth.clave_portal.limpiar()
    monkeypatch.setattr(auth.clave_portal, "_descargar", descargar)
    yield estado
    auth.clave_portal.limpiar()


@pytest.fixture
def envios(monkeypatch):
    """Simula Graph: registra los envíos y responde según `resultado`."""
    registro = {"enviados": [], "resultado": mailer.ResultadoEnvio(True, "Correo enviado")}

    def enviar(usuario):
        registro["enviados"].append(usuario["Correo"])
        return registro["resultado"]

    monkeypatch.setattr(mailer, "enviar_bienvenida", enviar)
    return registro


class CuentasFalsas:
    """Reemplaza asegurar / actualizar_nombre / eliminar de app.externalid (External ID en memoria).

    `fallar[operacion] = motivo` hace que esa operación lance ErrorExternalId(motivo).
    """

    def __init__(self):
        self.cuentas: dict[str, dict] = {}
        self.fallar: dict[str, str] = {}
        self.llamadas: list[tuple] = []

    def _quizas_fallar(self, operacion):
        if operacion in self.fallar:
            raise externalid.ErrorExternalId(self.fallar[operacion])

    def asegurar(self, correo, nombre, apellido):
        self.llamadas.append(("asegurar", correo))
        self._quizas_fallar("asegurar")
        if correo in self.cuentas:
            cuenta = self.cuentas[correo]
            estado = externalid.EXISTE_CONTRASENA if cuenta.get("contrasena") else externalid.EXISTE_CODIGO
            return cuenta["id"], estado
        self.cuentas[correo] = {"id": f"id-{correo}", "nombre": nombre, "apellido": apellido}
        return self.cuentas[correo]["id"], externalid.CREADA

    def actualizar_nombre(self, correo, nombre, apellido):
        self.llamadas.append(("actualizar_nombre", correo))
        self._quizas_fallar("actualizar_nombre")
        if correo not in self.cuentas:
            return False
        self.cuentas[correo].update(nombre=nombre, apellido=apellido)
        return True

    def eliminar(self, correo):
        self.llamadas.append(("eliminar", correo))
        self._quizas_fallar("eliminar")
        return self.cuentas.pop(correo, None) is not None


@pytest.fixture
def cuentas(monkeypatch):
    falsas = CuentasFalsas()
    for nombre in ("asegurar", "actualizar_nombre", "eliminar"):
        monkeypatch.setattr(externalid, nombre, getattr(falsas, nombre))
    return falsas


@pytest.fixture
def cliente(bd):
    # https para que el navegador simulado acepte y reenvíe la cookie Secure.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def sin_auth(monkeypatch):
    """Simula AUTH_ENABLED=false (por defecto los tests corren con la autenticación activa)."""
    monkeypatch.setattr(get_settings(), "auth_enabled", False)


@pytest.fixture
def cliente_sin_auth(sin_auth, cliente):
    return cliente


@pytest.fixture
def cliente_admin(cliente):
    resp = cliente.post("/auth/portal", data={"token": crear_token()}, follow_redirects=False)
    assert resp.status_code == 303
    return cliente
