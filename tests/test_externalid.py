"""Módulo de External ID y script de sincronización (Graph simulado)."""

import httpx
import pytest

from app import externalid
from app.config import get_settings
from app.tools import sync_externalid

DOMINIO = "externos.ejemplo.com"


def identidad_codigo(correo):
    return {"signInType": "federated", "issuer": "mail", "issuerAssignedId": correo}


def identidad_contrasena(correo):
    return {"signInType": "emailAddress", "issuer": DOMINIO, "issuerAssignedId": correo}


class GraphFalso:
    """Simula /users de Graph: guarda las cuentas en memoria y registra cada solicitud.

    Como Graph real, al filtrar identidades emailAddress ignora el issuer; las federated deben coincidir.
    """

    def __init__(self):
        self.cuentas: dict[str, dict] = {}  # id -> cuerpo enviado al crear
        self.solicitudes: list[dict] = []
        self.forzar: dict[str, httpx.Response] = {}  # método -> respuesta fija

    def _coincide(self, identidad, correo, issuer):
        if identidad["issuerAssignedId"] != correo:
            return False
        return identidad["signInType"] == "emailAddress" or identidad["issuer"] == issuer

    def request(self, metodo, url, headers, timeout, params=None, json=None):
        self.solicitudes.append({"metodo": metodo, "url": url, "params": params, "json": json, "headers": headers})
        if metodo in self.forzar:
            return self.forzar[metodo]
        ruta = url.removeprefix("https://graph.microsoft.com/v1.0")
        if metodo == "GET" and ruta == "/users":
            # Extrae correo e issuer del filtro (deshaciendo el escape de comillas).
            filtro = params["$filter"]
            correo = filtro.split("issuerAssignedId eq '", 1)[1].split("' and c/issuer", 1)[0].replace("''", "'")
            issuer = filtro.split("c/issuer eq '", 1)[1].rsplit("')", 1)[0].replace("''", "'")
            valores = [
                {"id": id_, "identities": c["identities"]}
                for id_, c in self.cuentas.items()
                if any(self._coincide(i, correo, issuer) for i in c["identities"])
            ]
            return httpx.Response(200, json={"value": valores})
        if metodo == "POST" and ruta == "/users":
            id_ = f"id-{len(self.cuentas) + 1}"
            self.cuentas[id_] = json
            return httpx.Response(201, json={"id": id_})
        if metodo == "PATCH":
            id_ = ruta.removeprefix("/users/")
            self.cuentas[id_].update(json)
            return httpx.Response(204)
        if metodo == "DELETE":
            id_ = ruta.removeprefix("/users/")
            return httpx.Response(204 if self.cuentas.pop(id_, None) else 404)
        raise AssertionError(f"solicitud inesperada: {metodo} {url}")

    def agregar(self, correo, contrasena=False):
        """Cuenta existente: de código (federated/mail) o antigua con contraseña (emailAddress)."""
        id_ = f"{'antigua' if contrasena else 'codigo'}-{correo}"
        identidad = identidad_contrasena(correo) if contrasena else identidad_codigo(correo)
        self.cuentas[id_] = {"identities": [identidad]}
        return id_


@pytest.fixture
def graph(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "extid_enabled", True)
    monkeypatch.setattr(s, "extid_client_id", "cliente-externos")
    monkeypatch.setattr(s, "extid_client_secret", type(s.extid_client_secret)("secreto-externos"))

    class MsalFalso:
        def acquire_token_for_client(self, scopes):
            assert scopes == ["https://graph.microsoft.com/.default"]
            return {"access_token": "token-falso"}

    monkeypatch.setattr(externalid, "_cliente_msal", lambda: MsalFalso())
    falso = GraphFalso()
    monkeypatch.setattr(httpx, "request", falso.request)
    return falso


# --- búsqueda ---

def test_buscar_primero_por_issuer_mail_y_escapa_comillas(graph):
    id_ = graph.agregar("o'brien@ejemplo.com")
    assert externalid.buscar_por_correo("o'brien@ejemplo.com") == externalid.Cuenta(id_, externalid.TIPO_CODIGO)
    assert len(graph.solicitudes) == 1
    params = graph.solicitudes[0]["params"]
    assert params["$filter"] == "identities/any(c:c/issuerAssignedId eq 'o''brien@ejemplo.com' and c/issuer eq 'mail')"
    assert params["$select"] == "id,identities"
    assert graph.solicitudes[0]["headers"] == {"Authorization": "Bearer token-falso"}


def test_buscar_cuenta_antigua_con_contrasena(graph):
    id_ = graph.agregar("juan@ejemplo.com", contrasena=True)
    cuenta = externalid.buscar_por_correo("juan@ejemplo.com")
    assert cuenta == externalid.Cuenta(id_, externalid.TIPO_CONTRASENA)


def test_buscar_cuenta_antigua_se_clasifica_por_sus_identidades(graph):
    # Graph devuelve la cuenta emailAddress incluso filtrando por issuer 'mail' (ignora el issuer):
    # se clasifica por la identidad que trae, no por el filtro que la encontró.
    graph.agregar("juan@ejemplo.com", contrasena=True)
    externalid.buscar_por_correo("juan@ejemplo.com")
    assert len(graph.solicitudes) == 1  # ya apareció en la primera búsqueda


def test_buscar_si_hay_dos_cuentas_gana_la_de_codigo(graph):
    graph.agregar("juan@ejemplo.com", contrasena=True)
    id_codigo = graph.agregar("juan@ejemplo.com")
    assert externalid.buscar_por_correo("juan@ejemplo.com") == externalid.Cuenta(id_codigo, externalid.TIPO_CODIGO)


def test_buscar_sin_cuenta_consulta_mail_y_luego_el_dominio(graph):
    assert externalid.buscar_por_correo("nadie@ejemplo.com") is None
    filtros = [s["params"]["$filter"] for s in graph.solicitudes]
    assert filtros == [
        "identities/any(c:c/issuerAssignedId eq 'nadie@ejemplo.com' and c/issuer eq 'mail')",
        "identities/any(c:c/issuerAssignedId eq 'nadie@ejemplo.com' and c/issuer eq 'externos.ejemplo.com')",
    ]


# --- creación ---

def test_crear_con_identidad_de_codigo_sin_contrasena(graph):
    id_ = externalid.crear("juan@ejemplo.com", "Juan", "Pérez")
    assert graph.cuentas[id_] == {
        "accountEnabled": True,
        "displayName": "Juan Pérez",
        "givenName": "Juan",
        "surname": "Pérez",
        "mail": "juan@ejemplo.com",
        "identities": [{"signInType": "federated", "issuer": "mail", "issuerAssignedId": "juan@ejemplo.com"}],
    }
    assert len(graph.solicitudes) == 1


def test_crear_sin_apellido_omite_surname(graph):
    id_ = externalid.crear("juan@ejemplo.com", "Juan", "")
    assert "surname" not in graph.cuentas[id_]
    assert graph.cuentas[id_]["displayName"] == "Juan"


def test_crear_rechazado_no_reintenta_y_deja_la_respuesta_completa_en_el_log(graph, caplog):
    cuerpo = {"error": {"code": "Request_BadRequest", "message": "Detalle completo de Graph",
                        "innerError": {"request-id": "abc-123"}}}
    graph.forzar["POST"] = httpx.Response(400, json=cuerpo)
    with caplog.at_level("ERROR", logger="app.externalid"), pytest.raises(externalid.ErrorExternalId) as e:
        externalid.crear("juan@ejemplo.com", "Juan", "Pérez")
    assert e.value.motivo == "Microsoft Graph respondió 400 (Request_BadRequest)"
    assert [s["metodo"] for s in graph.solicitudes] == ["POST"]  # sin reintento con contraseña
    assert "passwordProfile" not in graph.solicitudes[0]["json"]
    assert "Detalle completo de Graph" in caplog.text and "abc-123" in caplog.text


def test_crear_con_error_de_graph(graph):
    graph.forzar["POST"] = httpx.Response(403, json={"error": {"code": "Authorization_RequestDenied"}})
    with pytest.raises(externalid.ErrorExternalId) as e:
        externalid.crear("juan@ejemplo.com", "Juan", "Pérez")
    assert e.value.motivo == "Microsoft Graph respondió 403 (Authorization_RequestDenied)"


# --- asegurar ---

def test_asegurar_crea_solo_si_no_existe(graph):
    id_, estado = externalid.asegurar("juan@ejemplo.com", "Juan", "Pérez")
    assert estado == externalid.CREADA
    assert externalid.asegurar("juan@ejemplo.com", "Juan", "Pérez") == (id_, externalid.EXISTE_CODIGO)
    assert len(graph.cuentas) == 1


def test_asegurar_con_cuenta_antigua_no_crea_otra(graph, caplog):
    id_ = graph.agregar("juan@ejemplo.com", contrasena=True)
    with caplog.at_level("WARNING", logger="app.externalid"):
        assert externalid.asegurar("juan@ejemplo.com", "Juan", "Pérez") == (id_, externalid.EXISTE_CONTRASENA)
    assert len(graph.cuentas) == 1
    assert "POST" not in [s["metodo"] for s in graph.solicitudes]
    assert f"ya existe con contraseña (formato antiguo, id={id_})" in caplog.text


# --- actualizar / eliminar ---

def test_actualizar_nombre(graph):
    id_ = graph.agregar("juan@ejemplo.com")
    assert externalid.actualizar_nombre("juan@ejemplo.com", "Pedro", "") is True
    patch = graph.solicitudes[-1]
    assert patch["metodo"] == "PATCH" and patch["url"].endswith(f"/users/{id_}")
    assert patch["json"] == {"displayName": "Pedro", "givenName": "Pedro", "surname": None}


def test_actualizar_nombre_de_cuenta_antigua(graph):
    id_ = graph.agregar("juan@ejemplo.com", contrasena=True)
    assert externalid.actualizar_nombre("juan@ejemplo.com", "Pedro", "Soto") is True
    assert graph.solicitudes[-1]["url"].endswith(f"/users/{id_}")


def test_actualizar_nombre_sin_cuenta(graph):
    assert externalid.actualizar_nombre("nadie@ejemplo.com", "Pedro", "Soto") is False
    assert [s["metodo"] for s in graph.solicitudes] == ["GET", "GET"]


@pytest.mark.parametrize("contrasena", [False, True])
def test_eliminar(graph, contrasena):
    graph.agregar("juan@ejemplo.com", contrasena=contrasena)
    assert externalid.eliminar("juan@ejemplo.com") is True
    assert graph.cuentas == {}
    assert externalid.eliminar("juan@ejemplo.com") is False


# --- errores y deshabilitado ---

def test_error_de_red(graph, monkeypatch):
    def falla(*a, **k):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(httpx, "request", falla)
    with pytest.raises(externalid.ErrorExternalId) as e:
        externalid.buscar_por_correo("juan@ejemplo.com")
    assert e.value.motivo == "No se pudo conectar con Microsoft Graph"


def test_sin_token(graph, monkeypatch):
    class MsalSinToken:
        def acquire_token_for_client(self, scopes):
            return {"error": "invalid_client"}

    monkeypatch.setattr(externalid, "_cliente_msal", lambda: MsalSinToken())
    with pytest.raises(externalid.ErrorExternalId) as e:
        externalid.buscar_por_correo("juan@ejemplo.com")
    assert e.value.motivo == "No se pudo autenticar con Microsoft Graph (invalid_client)"


def test_faltan_credenciales(graph, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "extid_client_secret", type(s.extid_client_secret)(""))
    with pytest.raises(externalid.ErrorExternalId) as e:
        externalid.asegurar("juan@ejemplo.com", "Juan", "")
    assert "credenciales" in e.value.motivo
    assert graph.solicitudes == []


def test_deshabilitado_no_hace_nada(monkeypatch, caplog):
    def no_llamar(*a, **k):
        raise AssertionError("no debería llamar a Graph")

    monkeypatch.setattr(httpx, "request", no_llamar)
    monkeypatch.setattr(externalid, "_cliente_msal", no_llamar)
    with caplog.at_level("DEBUG", logger="app.externalid"):
        assert externalid.buscar_por_correo("a@b.com") is None
        assert externalid.crear("a@b.com", "A", "B") is None
        assert externalid.asegurar("a@b.com", "A", "B") == (None, None)
        assert externalid.actualizar_nombre("a@b.com", "A", "B") is False
        assert externalid.eliminar("a@b.com") is False
    assert "External ID deshabilitado" in caplog.text


# --- script de sincronización ---

@pytest.fixture
def usuarios_sync(bd):
    # El admin (Portal3) ya está en bd. Se agregan casos que entran y que no entran.
    bd.agregar("con.codigo@ejemplo.com", "Con", "Codigo", p1=True)
    bd.agregar("con.clave@ejemplo.com", "Con", "Clave", p1=True)
    bd.agregar("sin.cuenta@ejemplo.com", "Sin", "Cuenta", p2=True)
    bd.agregar("inactivo@ejemplo.com", "In", "Activo", p1=True, activo=False)
    bd.agregar("sin.portales@ejemplo.com", "Sin", "Portales")
    return bd


def _lineas(salida):
    return {l.split(" | ")[0].strip(): l for l in salida.splitlines() if "@" in l and " | " in l}


def test_sync_modo_prueba_distingue_codigo_contrasena_y_nuevas(graph, usuarios_sync, capsys):
    graph.agregar("con.codigo@ejemplo.com")
    graph.agregar("con.clave@ejemplo.com", contrasena=True)
    assert sync_externalid.main([]) == 0
    salida = capsys.readouterr().out
    assert "PRUEBA" in salida
    assert "Correo" in salida and "Nombre" in salida and "Estado" in salida
    lineas = _lineas(salida)
    assert set(lineas) == {"admin@ejemplo.com", "con.codigo@ejemplo.com", "con.clave@ejemplo.com",
                           "sin.cuenta@ejemplo.com"}
    assert lineas["con.codigo@ejemplo.com"].endswith("Ya existe (código)")
    assert lineas["con.clave@ejemplo.com"].endswith("Ya existe (contraseña, antigua)")
    assert lineas["sin.cuenta@ejemplo.com"].endswith("Se crearía")
    assert "Sin Cuenta" in lineas["sin.cuenta@ejemplo.com"]
    assert ("Resumen: Ya existe (código): 1, Ya existe (contraseña, antigua): 1, Se crearía: 2, Error: 0 "
            "(total: 4)") in salida
    assert "Las cuentas antiguas con contraseña no se tocan" in salida
    assert "POST" not in [s["metodo"] for s in graph.solicitudes]
    assert len(graph.cuentas) == 2
    assert "secreto-externos" not in salida


def test_sync_apply_crea_solo_las_que_faltan(graph, usuarios_sync, capsys):
    graph.agregar("con.codigo@ejemplo.com")
    graph.agregar("con.clave@ejemplo.com", contrasena=True)
    assert sync_externalid.main(["--apply"]) == 0
    salida = capsys.readouterr().out
    assert "APLICAR" in salida
    lineas = _lineas(salida)
    assert lineas["con.codigo@ejemplo.com"].endswith("Ya existía (código)")
    assert lineas["con.clave@ejemplo.com"].endswith("Ya existía (contraseña, antigua)")
    assert lineas["sin.cuenta@ejemplo.com"].endswith("Creada")
    assert lineas["admin@ejemplo.com"].endswith("Creada")
    assert ("Resumen: Ya existía (código): 1, Ya existía (contraseña, antigua): 1, Creada: 2, Error: 0 "
            "(total: 4)") in salida
    # Las nuevas son de código; la antigua con contraseña no se duplicó.
    assert len(graph.cuentas) == 4
    nuevas = [c for id_, c in graph.cuentas.items() if id_.startswith("id-")]
    assert all(c["identities"][0]["issuer"] == "mail" and "passwordProfile" not in c for c in nuevas)
    # Una segunda pasada ya no crea nada.
    assert sync_externalid.main(["--apply"]) == 0
    assert "Ya existía (código): 3, Ya existía (contraseña, antigua): 1, Creada: 0" in capsys.readouterr().out


def test_sync_apply_con_errores(graph, usuarios_sync, capsys):
    graph.forzar["POST"] = httpx.Response(403, json={"error": {"code": "Authorization_RequestDenied"}})
    assert sync_externalid.main(["--apply"]) == 1
    salida = capsys.readouterr().out
    assert "Error: Microsoft Graph respondió 403 (Authorization_RequestDenied)" in salida
    assert "Error: 4 (total: 4)" in salida


def test_sync_se_detiene_si_esta_deshabilitado(bd, capsys):
    assert sync_externalid.main([]) == 2
    assert "EXTID_ENABLED=false" in capsys.readouterr().out
