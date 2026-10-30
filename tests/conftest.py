"""Fixtures comunes: configuración de prueba, BD simulada (con administradores), clave de Energía y clientes HTTP."""

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
        "ENERGIA_PORTAL_URL": "https://energia.ejemplo.com",
        "LATIDO_ORIGINS": "https://energia.ejemplo.com, https://mirastock.ejemplo.com/",
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
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth, claves, db, externalid, mailer
from app.main import app

ADMIN = "admin@ejemplo.com"
CLAVE_ADMIN = "Clave#Segura2026"
EMISOR = "otro-sitio.ejemplo.com"
EMISOR_ENERGIA = "energia.ejemplo.com"
CSRF = {"X-Requested-With": "mira-admin"}
# PBKDF2 con 600.000 iteraciones haría lentísimos los tests: se bajan (test_claves comprueba el valor real).
ITERACIONES_TEST = 1_000


def _nueva_clave():
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return pem, privada.public_key()


CLAVE_PRIVADA, CLAVE_PUBLICA = _nueva_clave()
OTRA_CLAVE_PRIVADA, OTRA_CLAVE_PUBLICA = _nueva_clave()
CLAVE_PRIVADA_ENERGIA, CLAVE_PUBLICA_ENERGIA = _nueva_clave()


def crear_token(claims=None, clave=CLAVE_PRIVADA, **extra):
    datos = {"iss": EMISOR, "exp": int(time.time()) + 600, "email": ADMIN}
    datos.update(claims or {})
    datos.update(extra)
    datos = {k: v for k, v in datos.items() if v is not None}
    return jwt.encode(datos, clave, algorithm="RS256")


def crear_token_energia(claims=None, clave=CLAVE_PRIVADA_ENERGIA, **extra):
    return crear_token({"iss": EMISOR_ENERGIA, **(claims or {})}, clave, **extra)


class BDFalsa:
    """Reemplaza las funciones de app.db con datos en memoria."""

    def __init__(self):
        self.gerencias = ["Gerencia Comercial", "Gerencia de Operaciones", "Gerencia TI"]
        self.usuarios: dict[int, dict] = {}
        self._siguiente = 1
        self.historial: list[dict] = []  # filas de core.vHistorialAccesos (Fecha UTC sin zona)
        self.llamadas_historial: list[tuple] = []
        # Latidos: "ahora" simula SYSUTCDATETIME(); las tablas guardan UTC sin zona.
        self.ahora = datetime(2026, 10, 28, 15, 0, 0)
        self.sesiones_agente: dict[str, dict] = {}  # core.SesionesAgente por Token (GUID en minúsculas)
        self.accesos: list[dict] = []  # core.HistorialAccesos
        self.llamadas_latido: list[tuple] = []
        self.agregar(ADMIN, "Ana", "Admin", "Gerencia TI", p3=True)
        # core.AdministradoresPortal: el admin de los tests (Id 1) ya cambió su contraseña (PBKDF2).
        self.admins: dict[int, dict] = {}
        self.agregar_admin(ADMIN, "Ana Admin", CLAVE_ADMIN)

    def agregar(self, correo, nombre="Nombre", apellido="", gerencia="Gerencia TI",
                p1=False, p2=False, p3=False, activo=True, invitacion=False, cliente="Otro"):
        uid = self._siguiente
        self._siguiente += 1
        self.usuarios[uid] = {
            "Id": uid, "Correo": correo, "Nombre": nombre, "Apellido": apellido, "Gerencia": gerencia,
            "Cliente": cliente, "Portal1": p1, "Portal2": p2, "Portal3": p3, "Activo": activo,
            "InvitacionEnviada": invitacion,
            "FechaAlta": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        return dict(self.usuarios[uid])

    def _por_correo(self, correo):
        return next((u for u in self.usuarios.values() if u["Correo"].lower() == correo.lower()), None)

    # --- administradores (core.AdministradoresPortal); el reloj es bd.ahora, como SYSUTCDATETIME() ---
    def agregar_admin(self, correo, nombre="Admin", clave=CLAVE_ADMIN, algoritmo=claves.ALGORITMO_APP,
                      debe_cambiar=False, activo=True, intentos=0, bloqueado_hasta=None,
                      ultimo_acceso=None, fecha_cambio=None, fecha_alta=None):
        aid = max(self.admins, default=0) + 1
        sal = bytes([aid]) * 32
        self.admins[aid] = {
            "Id": aid, "Nombre": nombre, "Correo": correo,
            "ContrasenaHash": claves.calcular(algoritmo, clave, sal), "ContrasenaSal": sal, "AlgoritmoHash": algoritmo,
            "DebeCambiarContrasena": debe_cambiar, "Activo": activo, "IntentosFallidos": intentos,
            "BloqueadoHasta": bloqueado_hasta, "UltimoAcceso": ultimo_acceso,
            "FechaCambioContrasena": fecha_cambio, "FechaAlta": fecha_alta or self.ahora - timedelta(hours=1),
        }
        return aid

    def _vista_admin(self, a):
        base = a["FechaCambioContrasena"] or a["FechaAlta"]
        return {
            **{k: v for k, v in a.items() if k not in ("FechaCambioContrasena", "FechaAlta")},
            "Bloqueado": bool(a["BloqueadoHasta"] and a["BloqueadoHasta"] > self.ahora),
            "PorDefectoVencida": base + timedelta(hours=db.HORAS_CONTRASENA_POR_DEFECTO) < self.ahora,
        }

    def obtener_admin(self, aid):
        a = self.admins.get(aid)
        return self._vista_admin(a) if a else None

    def obtener_admin_por_correo(self, correo):
        a = next((a for a in self.admins.values() if a["Correo"] == correo), None)
        return self._vista_admin(a) if a else None

    def listar_admins(self):
        return [
            {k: v[k] for k in ("Id", "Nombre", "Correo", "Activo", "UltimoAcceso", "BloqueadoHasta", "Bloqueado")}
            for v in sorted((self._vista_admin(a) for a in self.admins.values()), key=lambda a: (a["Nombre"], a["Correo"]))
        ]

    def registrar_fallo_admin(self, aid):
        a = self.admins[aid]
        if a["BloqueadoHasta"] and a["BloqueadoHasta"] > self.ahora:
            return
        if a["BloqueadoHasta"]:  # bloqueo anterior vencido: la cuenta empieza de nuevo
            a["IntentosFallidos"], a["BloqueadoHasta"] = 1, None
            return
        a["IntentosFallidos"] += 1
        if a["IntentosFallidos"] >= db.INTENTOS_PARA_BLOQUEO:
            a["BloqueadoHasta"] = self.ahora + timedelta(minutes=db.MINUTOS_BLOQUEO)

    def registrar_exito_admin(self, aid, es_ingreso):
        a = self.admins[aid]
        a["IntentosFallidos"], a["BloqueadoHasta"] = 0, None
        if es_ingreso:
            a["UltimoAcceso"] = self.ahora

    def cambiar_contrasena_admin(self, aid, hash_, sal, algoritmo):
        self.admins[aid].update(
            ContrasenaHash=hash_, ContrasenaSal=sal, AlgoritmoHash=algoritmo, DebeCambiarContrasena=False,
            FechaCambioContrasena=self.ahora, IntentosFallidos=0, BloqueadoHasta=None,
        )

    def migrar_hash_admin(self, aid, hash_anterior, hash_, sal, algoritmo):
        a = self.admins[aid]
        if a["ContrasenaHash"] != hash_anterior or a["DebeCambiarContrasena"]:
            return False
        a.update(ContrasenaHash=hash_, ContrasenaSal=sal, AlgoritmoHash=algoritmo)
        return True

    def actualizar_admin(self, aid, nombre, correo):
        if aid not in self.admins:
            return False
        if any(a["Correo"] == correo for i, a in self.admins.items() if i != aid):
            raise db.CorreoDuplicado()
        self.admins[aid].update(Nombre=nombre, Correo=correo)
        return True

    # --- funciones de app.db ---
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

    def crear_usuario(self, correo, nombre, apellido, gerencia, cliente, p1, p2, p3):
        if self._por_correo(correo):
            raise db.CorreoDuplicado()
        return self.agregar(correo, nombre, apellido, gerencia, p1, p2, p3, cliente=cliente)

    def actualizar_usuario(self, uid, nombre, apellido, gerencia, cliente, p1, p2, p3):
        u = self.usuarios.get(uid)
        if not u:
            return False
        u.update(Nombre=nombre, Apellido=apellido, Gerencia=gerencia, Cliente=cliente, Portal1=p1, Portal2=p2, Portal3=p3)
        return True

    def eliminar_usuario(self, uid):
        return self.usuarios.pop(uid, None) is not None

    def marcar_invitacion_enviada(self, uid):
        self.usuarios[uid]["InvitacionEnviada"] = True

    def agregar_acceso(self, fecha, correo, portal="Energía", resultado="OK", usuario="",
                       final_sesion=None, en_curso=False, cierre=False):
        tiempo = int((final_sesion - fecha).total_seconds()) if final_sesion and fecha else None
        self.historial.append({
            "Fecha": fecha, "Usuario": usuario, "Correo": correo, "Portal": portal, "Resultado": resultado,
            "FinalSesion": final_sesion, "TiempoSesionSeg": tiempo, "EnCurso": en_curso, "CierreExplicito": cierre,
        })

    def agregar_sesion_agente(self, token, creado_en, final_sesion=None, expira_en=None, cierre=False):
        self.sesiones_agente[token] = {
            "CreadoEn": creado_en, "ExpiraEn": expira_en or creado_en + timedelta(minutes=10),
            "FinalSesion": final_sesion, "CierreExplicito": cierre,
        }

    def agregar_fila_acceso(self, correo, fecha, final_sesion=None, portal="Energía", resultado="OK", cierre=False,
                            token=None):
        fila = {
            "Correo": correo, "Portal": portal, "Resultado": resultado, "Fecha": fecha,
            "FinalSesion": final_sesion, "CierreExplicito": cierre,
        }
        if token is not None:
            fila["Token"] = token
        self.accesos.append(fila)
        return fila

    # Misma lógica que el SQL de db.latido_* / db.cierre_*.
    def _sesion_agente_abierta(self, token):
        s = self.sesiones_agente.get(token)
        if not s or s["CreadoEn"] < self.ahora - timedelta(hours=12) or s["CierreExplicito"]:
            return None
        return s

    def latido_mirastock(self, token):
        self.llamadas_latido.append(("mirastock", token))
        s = self._sesion_agente_abierta(token)
        if not s:
            return False
        if s["FinalSesion"] is not None and s["FinalSesion"] >= self.ahora - timedelta(seconds=60):
            return False
        s["FinalSesion"] = self.ahora
        return True

    def cierre_mirastock(self, token):
        self.llamadas_latido.append(("cierre_mirastock", token))
        s = self._sesion_agente_abierta(token)
        if not s:
            return False
        s["FinalSesion"] = self.ahora
        if s["ExpiraEn"] > self.ahora:
            s["ExpiraEn"] = self.ahora
        s["CierreExplicito"] = True
        return True

    def _ultima_fila_energia(self, correo):
        """La fila más reciente de la ventana de 30 min, abierta o cerrada."""
        vigentes = [
            f for f in self.accesos
            if f["Correo"] == correo and f["Portal"] == "Energía" and f["Resultado"] == "OK"
            and (f["FinalSesion"] or f["Fecha"]) >= self.ahora - timedelta(minutes=30)
        ]
        return max(vigentes, key=lambda f: f["Fecha"]) if vigentes else None

    def latido_energia(self, correo):
        self.llamadas_latido.append(("energia", correo))
        ultima = self._ultima_fila_energia(correo)
        hace_60s = self.ahora - timedelta(seconds=60)
        if ultima and not ultima["CierreExplicito"]:
            if ultima["FinalSesion"] is None or ultima["FinalSesion"] < hace_60s:
                ultima["FinalSesion"] = self.ahora
            return False
        if ultima and ultima["FinalSesion"] is not None and ultima["FinalSesion"] >= hace_60s:
            return False  # cerrada hace menos de 60 s: latido que venía en camino
        self.agregar_fila_acceso(correo, self.ahora, self.ahora)
        return True

    def cierre_energia(self, correo):
        self.llamadas_latido.append(("cierre_energia", correo))
        ultima = self._ultima_fila_energia(correo)
        if not ultima or ultima["CierreExplicito"]:
            return False
        ultima["FinalSesion"] = self.ahora
        ultima["CierreExplicito"] = True
        return True

    def _fila_energia_llave(self, llave):
        """Fila OK de Energía con esa llave, de las últimas 12 h y abierta (como el WHERE del SQL)."""
        for f in self.accesos:
            if (f.get("Token") == llave and f["Portal"] == "Energía" and f["Resultado"] == "OK"
                    and f["Fecha"] >= self.ahora - timedelta(hours=12) and not f["CierreExplicito"]):
                return f
        return None

    def latido_energia_llave(self, llave):
        self.llamadas_latido.append(("energia_llave", llave))
        f = self._fila_energia_llave(llave)
        if not f or (f["FinalSesion"] is not None and f["FinalSesion"] >= self.ahora - timedelta(seconds=60)):
            return False
        f["FinalSesion"] = self.ahora
        return True

    def cierre_energia_llave(self, llave):
        self.llamadas_latido.append(("cierre_energia_llave", llave))
        f = self._fila_energia_llave(llave)
        if not f:
            return False
        f["FinalSesion"] = self.ahora
        f["CierreExplicito"] = True
        return True

    def _filtrar_historial(self, f):
        filas = self.historial
        if f.correo:
            filas = [r for r in filas if f.correo.lower() in r["Correo"]]
        if f.portal:
            filas = [r for r in filas if r["Portal"] == f.portal]
        if f.resultado:
            filas = [r for r in filas if r["Resultado"] == f.resultado]
        if f.desde:
            filas = [r for r in filas if r["Fecha"] >= f.desde]
        if f.hasta:
            filas = [r for r in filas if r["Fecha"] < f.hasta]
        return sorted(filas, key=lambda r: (r["Fecha"], r["Correo"]), reverse=True)

    def listar_historial(self, filtros, pagina, tamano=50):
        self.llamadas_historial.append(("listar", filtros, pagina, tamano))
        filas = self._filtrar_historial(filtros)
        inicio = (pagina - 1) * tamano
        return [dict(r) for r in filas[inicio:inicio + tamano]], len(filas)

    def resumen_historial(self, filtros, tz_offset_min):
        self.llamadas_historial.append(("resumen", filtros, tz_offset_min))
        filas = self._filtrar_historial(filtros)
        por_dia: dict[str, int] = {}
        for r in filas:
            dia = (r["Fecha"] + timedelta(minutes=tz_offset_min)).date().isoformat()
            por_dia[dia] = por_dia.get(dia, 0) + 1
        tiempos = [r for r in filas if r["TiempoSesionSeg"] is not None]
        return {
            "total": len(filas),
            "usuariosUnicos": len({r["Correo"] for r in filas}),
            "porPortal": {p: sum(r["Portal"] == p for r in filas) for p in ("Energía", "MiraStock")},
            "denegados": sum(r["Resultado"] == "Denegado" for r in filas),
            "tiempoPromedioSeg": (
                sum(r["TiempoSesionSeg"] for r in tiempos) // len(tiempos) if tiempos else None
            ),
            "tiempoTotalSeg": {
                p: sum(r["TiempoSesionSeg"] for r in tiempos if r["Portal"] == p) for p in ("Energía", "MiraStock")
            },
            "enCurso": sum(bool(r["EnCurso"]) for r in filas),
            "cerradasBoton": sum(bool(r["CierreExplicito"]) for r in filas),
            "porDia": [{"dia": d, "total": n} for d, n in sorted(por_dia.items())],
        }

    # Misma lógica que db.estadisticas_*: sesiones = filas OK del rango.
    def _sesiones(self, portal, desde, hasta):
        filtros = db.FiltrosHistorial(portal=portal, resultado="OK", desde=desde, hasta=hasta)
        return [r for r in self._filtrar_historial(filtros) if r["Portal"] is not None]

    @staticmethod
    def _agregados(filas):
        tiempos = [r["TiempoSesionSeg"] for r in filas if r["TiempoSesionSeg"] is not None]
        return {
            "sesiones": len(filas),
            "segundosTotales": sum(tiempos) if tiempos else None,
            "promedioSeg": sum(tiempos) // len(tiempos) if tiempos else None,
            "sesionesMedidas": len(tiempos),
            "ultimaConexion": max((r["Fecha"] for r in filas), default=None),
        }

    def estadisticas_portales(self, desde, hasta):
        self.llamadas_historial.append(("portales", desde, hasta))
        filas = self._sesiones(None, desde, hasta)
        conocidos = {r["Portal"] for r in self.historial if r["Portal"] is not None}

        def unicos(fs):
            return len({r["Correo"] for r in fs if r["Correo"] is not None})

        return {
            "portales": [
                {"portal": p, "usuariosUnicos": unicos(fs), **self._agregados(fs)}
                for p in sorted(conocidos, key=str.casefold)
                for fs in [[r for r in filas if r["Portal"] == p]]
            ],
            "total": {"usuariosUnicos": unicos(filas), **self._agregados(filas)},
        }

    def estadisticas_usuarios(self, portal, desde, hasta, tope):
        self.llamadas_historial.append(("usuarios", portal, desde, hasta, tope))
        por_correo: dict = {}
        for r in self._sesiones(portal, desde, hasta):
            por_correo.setdefault(r["Correo"], []).append(r)
        filas = [
            {"usuario": max((r["Usuario"] or "") for r in fs).strip(), "correo": correo, **self._agregados(fs)}
            for correo, fs in por_correo.items()
        ]
        filas.sort(key=lambda f: (-(f["segundosTotales"] or 0), -f["sesiones"], f["correo"] or ""))
        return filas[:tope], len(filas) > tope


@pytest.fixture(autouse=True)
def iteraciones_rapidas(monkeypatch):
    monkeypatch.setattr(claves, "ITERACIONES_PBKDF2", ITERACIONES_TEST)


@pytest.fixture(autouse=True)
def sin_limite_previo():
    """Cada test empieza sin intentos registrados en el límite por IP."""
    auth.limite_intentos.limpiar()
    yield
    auth.limite_intentos.limpiar()


@pytest.fixture
def bd(monkeypatch, iteraciones_rapidas):
    falsa = BDFalsa()
    for nombre in (
        "obtener_admin", "obtener_admin_por_correo", "listar_admins", "registrar_fallo_admin",
        "registrar_exito_admin", "cambiar_contrasena_admin", "migrar_hash_admin", "actualizar_admin",
        "listar_gerencias", "listar_usuarios", "obtener_usuario", "existe_correo",
        "crear_usuario", "actualizar_usuario", "eliminar_usuario", "marcar_invitacion_enviada",
        "listar_usuarios_con_acceso", "listar_historial", "resumen_historial",
        "estadisticas_portales", "estadisticas_usuarios",
        "latido_mirastock", "latido_energia", "cierre_mirastock", "cierre_energia",
        "latido_energia_llave", "cierre_energia_llave",
    ):
        monkeypatch.setattr(db, nombre, getattr(falsa, nombre))
    return falsa


@pytest.fixture(autouse=True)
def clave_de_energia(monkeypatch):
    """Por defecto el sitio Energía entrega CLAVE_PUBLICA_ENERGIA. `estado['error']` simula que no responde."""
    estado = {"claves": [CLAVE_PUBLICA_ENERGIA], "descargas": 0, "error": None}

    def descargar():
        if estado["error"]:
            raise estado["error"]
        i = min(estado["descargas"], len(estado["claves"]) - 1)
        estado["descargas"] += 1
        return estado["claves"][i]

    auth.clave_energia.limpiar()
    monkeypatch.setattr(auth.clave_energia, "_descargar", descargar)
    yield estado
    auth.clave_energia.limpiar()


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


def poner_sesion(cliente, admin):
    """Cookie de sesión firmada para `admin` (fila de bd.admins), sin pasar por el login."""
    cliente.cookies.set(
        auth.COOKIE_SESION, auth._serializador().dumps(auth.datos_sesion(admin)), domain="testserver.local", path="/"
    )


def ingresar(cliente, correo=ADMIN, contrasena=CLAVE_ADMIN, **params):
    return cliente.post("/api/auth/login", json={"correo": correo, "contrasena": contrasena}, headers=CSRF, params=params)


@pytest.fixture
def cliente_admin(cliente, bd):
    poner_sesion(cliente, bd.admins[1])
    return cliente
