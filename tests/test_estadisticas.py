"""/estadisticas y la API de estadísticas por portal (v11), más el CSV de /historial en hora local."""

from datetime import datetime, timedelta, timezone

import pytest

from app import db, main
from tests.test_historial import CursorFalso, cursor_falso, revocar_admin  # noqa: F401 (fixture)

FECHA = datetime(2026, 10, 20, 15, 30, 0)  # UTC sin zona, como la vista
HOY = lambda: datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: E731

SIN_SESIONES = {
    "sesiones": 0, "segundosTotales": None, "promedioSeg": None, "sesionesMedidas": 0, "ultimaConexion": None,
    "sinActividad": 0,
}


def sesion(bd, correo, portal="Energía", minutos=None, fecha=FECHA, resultado="OK", usuario=""):
    """Una fila de la vista; `minutos` = tiempo medido (None = sin latidos)."""
    final = fecha + timedelta(minutes=minutos) if minutos is not None else None
    bd.agregar_acceso(fecha, correo, portal, resultado, usuario=usuario, final_sesion=final)


def lineas_csv(resp):
    return resp.content.decode("utf-8-sig").split("\r\n")


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

def test_pagina_estadisticas_estructura(cliente_admin):
    # v16: el inicio de estadísticas son cards (las arma estadisticas-inicio.js); sin acordeón.
    texto = cliente_admin.get("/estadisticas").text
    assert 'id="cards-estadisticas"' in texto and "<details" not in texto
    assert 'href="/historial"' in texto and 'href="/">← Inicio</a>' in texto
    assert '<script src="/static/comun.js?v=16" defer></script>' in texto


def test_historial_enlaza_estadisticas(cliente_admin):
    assert 'href="/estadisticas">Estadísticas</a>' in cliente_admin.get("/historial").text


def test_js_de_estadisticas_no_tiene_portales_fijos(cliente_admin):
    resp = cliente_admin.get("/static/estadisticas.js")
    assert resp.status_code == 200
    # Los bloques salen de la API: un portal nuevo no necesita código.
    assert "Energía" not in resp.text and "MiraStock" not in resp.text
    assert "const SUBVISTAS = [" in resp.text


def test_comun_js_expone_formatos_compartidos(cliente_admin):
    texto = cliente_admin.get("/static/comun.js").text
    for nombre in ("duracion", "fechaLocal", "textoCierre", "agregarRango", "tzOffsetMin", "descargarCsv"):
        assert nombre in texto


# ---------------------------------------------------------------------------
# Autorización y validación
# ---------------------------------------------------------------------------

ENDPOINTS = [
    ("/api/estadisticas/portales", {}),
    ("/api/estadisticas/portales/csv", {}),
    ("/api/estadisticas/usuarios", {"portal": "Energía"}),
    ("/api/estadisticas/usuarios/csv", {"portal": "Energía"}),
]


@pytest.mark.parametrize("ruta, params", ENDPOINTS)
def test_sin_sesion_401(cliente, ruta, params):
    resp = cliente.get(ruta, params=params)
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.parametrize("ruta, params", ENDPOINTS)
def test_401_antes_que_validar(cliente, ruta, params):
    assert cliente.get(ruta, params={"desde": "x", "tz_offset_min": "9999"}).status_code == 401


@pytest.mark.parametrize("ruta, params", ENDPOINTS)
def test_admin_desactivado_401(cliente_admin, bd, ruta, params):
    revocar_admin(bd)
    assert cliente_admin.get(ruta, params=params).status_code == 401


@pytest.mark.parametrize("ruta, params", ENDPOINTS)
@pytest.mark.parametrize("malos, campo", [
    ({"desde": "20/10/2026"}, "desde"),
    ({"hasta": "mañana"}, "hasta"),
    ({"desde": "2026-10-21T00:00:00Z", "hasta": "2026-10-21T00:00:00Z"}, "hasta"),
])
def test_fechas_invalidas_422(cliente_admin, bd, ruta, params, malos, campo):
    resp = cliente_admin.get(ruta, params={**params, **malos})
    assert resp.status_code == 422
    assert campo in resp.json()["errores"]
    assert bd.llamadas_historial == []


@pytest.mark.parametrize("ruta", ["/api/estadisticas/portales/csv", "/api/estadisticas/usuarios/csv"])
@pytest.mark.parametrize("tz", ["841", "-841", "x"])
def test_tz_offset_invalido_422(cliente_admin, ruta, tz):
    resp = cliente_admin.get(ruta, params={"portal": "Energía", "tz_offset_min": tz})
    assert resp.status_code == 422
    assert "tz_offset_min" in resp.json()["errores"]


@pytest.mark.parametrize("ruta", ["/api/estadisticas/usuarios", "/api/estadisticas/usuarios/csv"])
@pytest.mark.parametrize("portal", [None, "", "   "])
def test_usuarios_exige_portal(cliente_admin, bd, ruta, portal):
    params = {} if portal is None else {"portal": portal}
    resp = cliente_admin.get(ruta, params=params)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Indica el portal.", "errores": {"portal": "Indica el portal."}}
    assert bd.llamadas_historial == []


def test_usuarios_junta_errores_de_portal_y_fechas(cliente_admin):
    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"desde": "x"}).json()
    assert list(datos["errores"]) == ["portal", "desde"]
    assert datos["detail"] == "Indica el portal."


def test_usuarios_portal_demasiado_largo_422(cliente_admin):
    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": "x" * 51}).json()
    assert datos["errores"] == {"portal": "El portal no puede superar los 50 caracteres."}


# ---------------------------------------------------------------------------
# General por portal
# ---------------------------------------------------------------------------

def test_portales_sin_datos(cliente_admin):
    assert cliente_admin.get("/api/estadisticas/portales").json() == {
        "portales": [], "total": {"usuariosUnicos": 0, **SIN_SESIONES},
    }


def test_portales_totales_y_total_corporativo(cliente_admin, bd):
    sesion(bd, "ana@ejemplo.com", "Energía", 60, FECHA)
    sesion(bd, "ana@ejemplo.com", "Energía", 30, FECHA + timedelta(hours=1))
    sesion(bd, "beto@ejemplo.com", "Energía", None, FECHA + timedelta(hours=2))  # sin latidos
    sesion(bd, "ana@ejemplo.com", "MiraStock", 10, FECHA + timedelta(hours=3))
    sesion(bd, "carla@ejemplo.com", "MiraStock", None, FECHA + timedelta(hours=4), resultado="Denegado")

    datos = cliente_admin.get("/api/estadisticas/portales").json()
    assert datos["portales"] == [
        {
            "portal": "Energía", "slug": "energia", "usuariosUnicos": 2, "sesiones": 3, "segundosTotales": 5400,
            "promedioSeg": 2700, "sesionesMedidas": 2, "ultimaConexion": "2026-10-20T17:30:00Z",
            "sinActividad": 0,
        },
        {
            "portal": "MiraStock", "slug": "mirastock", "usuariosUnicos": 1, "sesiones": 1, "segundosTotales": 600,
            "promedioSeg": 600, "sesionesMedidas": 1, "ultimaConexion": "2026-10-20T18:30:00Z",
            "sinActividad": 0,
        },
    ]
    # Usuarios únicos sin repetir entre portales (ana está en los dos; carla solo fue denegada).
    assert datos["total"] == {
        "usuariosUnicos": 2, "sesiones": 4, "segundosTotales": 6000, "promedioSeg": 2000,
        "sesionesMedidas": 3, "ultimaConexion": "2026-10-20T18:30:00Z", "sinActividad": 0,
    }


def test_portales_denegado_no_cuenta_como_sesion_ni_usuario(cliente_admin, bd):
    sesion(bd, "solo.denegado@ejemplo.com", "MiraStock", resultado="Denegado")
    datos = cliente_admin.get("/api/estadisticas/portales").json()
    assert datos["portales"] == [{"portal": "MiraStock", "slug": "mirastock", "usuariosUnicos": 0, **SIN_SESIONES}]
    assert datos["total"]["usuariosUnicos"] == 0


def test_portal_sin_sesiones_en_el_rango_aparece_con_ceros(cliente_admin, bd):
    sesion(bd, "a@ejemplo.com", "Energía", 5, datetime(2026, 9, 1))
    sesion(bd, "b@ejemplo.com", "MiraStock", 5, FECHA)
    params = {"desde": "2026-10-01T00:00:00Z", "hasta": "2026-11-01T00:00:00Z"}
    datos = cliente_admin.get("/api/estadisticas/portales", params=params).json()
    assert [p["portal"] for p in datos["portales"]] == ["Energía", "MiraStock"]
    assert datos["portales"][0] == {"portal": "Energía", "slug": "energia", "usuariosUnicos": 0, **SIN_SESIONES}
    assert datos["total"]["sesiones"] == 1
    assert bd.llamadas_historial[-1] == ("portales", datetime(2026, 10, 1), datetime(2026, 11, 1))


def test_portal_nuevo_aparece_sin_codigo(cliente_admin, bd):
    sesion(bd, "a@ejemplo.com", "Energía", 5)
    sesion(bd, "b@ejemplo.com", "Bodega Norte", 20)
    sesion(bd, "a@ejemplo.com", "Bodega Norte", 10)
    datos = cliente_admin.get("/api/estadisticas/portales").json()
    assert [p["portal"] for p in datos["portales"]] == ["Bodega Norte", "Energía"]
    assert datos["portales"][0]["usuariosUnicos"] == 2 and datos["total"]["usuariosUnicos"] == 2
    usuarios = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": "Bodega Norte"}).json()
    assert [f["correo"] for f in usuarios["filas"]] == ["b@ejemplo.com", "a@ejemplo.com"]


# ---------------------------------------------------------------------------
# Usuarios por portal
# ---------------------------------------------------------------------------

def test_usuarios_orden_por_horas_y_campos(cliente_admin, bd):
    sesion(bd, "poco@ejemplo.com", "Energía", 5, usuario="Poco Tiempo")
    sesion(bd, "mucho@ejemplo.com", "Energía", 120, usuario="Mucho Tiempo")
    sesion(bd, "mucho@ejemplo.com", "Energía", None, FECHA + timedelta(days=1), usuario="Mucho Tiempo")
    sesion(bd, "sin.tiempo.b@ejemplo.com", "Energía", None)
    sesion(bd, "sin.tiempo.a@ejemplo.com", "Energía", None)
    sesion(bd, "sin.tiempo.a@ejemplo.com", "Energía", None)
    sesion(bd, "otro.portal@ejemplo.com", "MiraStock", 500)
    sesion(bd, "denegado@ejemplo.com", "Energía", resultado="Denegado")

    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": "energía"}).json()
    assert datos["portal"] == "Energía" and datos["total"] == 4 and datos["truncado"] is False
    assert [f["correo"] for f in datos["filas"]] == [
        "mucho@ejemplo.com", "poco@ejemplo.com", "sin.tiempo.a@ejemplo.com", "sin.tiempo.b@ejemplo.com",
    ]
    assert datos["filas"][0] == {
        "usuario": "Mucho Tiempo", "correo": "mucho@ejemplo.com", "sesiones": 2, "segundosTotales": 7200,
        "promedioSeg": 7200, "sesionesMedidas": 1, "ultimaConexion": "2026-10-21T15:30:00Z",
        "sinActividad": 0,
    }
    assert datos["filas"][2]["usuario"] == "" and datos["filas"][2]["segundosTotales"] is None
    assert bd.llamadas_historial[-1] == ("usuarios", "Energía", None, None, main.TOPE_USUARIOS_ESTADISTICAS, None)


def test_usuarios_portal_sin_datos(cliente_admin):
    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": "Inexistente"}).json()
    assert datos == {
        "portal": "Inexistente", "correo": None, "filas": [], "total": 0, "totalSinFiltro": 0, "truncado": False,
    }


def test_usuarios_tope_avisa_truncado(cliente_admin, bd, monkeypatch):
    monkeypatch.setattr(main, "TOPE_USUARIOS_ESTADISTICAS", 2)
    for i in range(3):
        sesion(bd, f"u{i}@ejemplo.com", "MiraStock", i + 1)
    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": "MiraStock"}).json()
    assert datos["truncado"] is True and datos["total"] == 2 and datos["totalSinFiltro"] == 3
    resp = cliente_admin.get("/api/estadisticas/usuarios/csv", params={"portal": "MiraStock"})
    assert resp.headers["x-historial-truncado"] == "2"
    assert len(lineas_csv(resp)) == 1 + 2 + 1


# ---------------------------------------------------------------------------
# Buscador por correo en «Usuarios (general)» (v13)
# ---------------------------------------------------------------------------

PORTALES_BUSQUEDA = ["Energía", "MiraStock", "Bodega Norte"]


def usuarios_para_buscar(bd, portal):
    sesion(bd, "ana.perez@entel.pe", portal, 30, usuario="Ana Pérez")
    sesion(bd, "Beto.Rojas@Entel.pe".lower(), portal, 20)
    sesion(bd, "carla@miragroup.cl", portal, 10)
    sesion(bd, "50%off@ejemplo.com", portal, 5)
    sesion(bd, "500off@ejemplo.com", portal, 4)
    sesion(bd, "a_b@ejemplo.com", portal, 3)
    sesion(bd, "axb@ejemplo.com", portal, 2)
    # No cuentan: otro portal y resultado denegado.
    sesion(bd, "ana.otro@entel.pe", "Portal Ajeno", 99)
    sesion(bd, "ana.denegada@entel.pe", portal, resultado="Denegado")


def correos_json(cliente, portal, correo):
    datos = cliente.get("/api/estadisticas/usuarios", params={"portal": portal, "correo": correo}).json()
    return datos, [f["correo"] for f in datos["filas"]]


def correos_csv(cliente, portal, correo):
    resp = cliente.get("/api/estadisticas/usuarios/csv", params={"portal": portal, "correo": correo})
    assert resp.status_code == 200
    return [linea.split(";")[1] for linea in lineas_csv(resp)[1:-1]]


@pytest.mark.parametrize("portal", PORTALES_BUSQUEDA)
@pytest.mark.parametrize("correo, esperados", [
    ("entel", ["ana.perez@entel.pe", "beto.rojas@entel.pe"]),
    ("  ENTEL.PE ", ["ana.perez@entel.pe", "beto.rojas@entel.pe"]),
    ("Carla", ["carla@miragroup.cl"]),
    ("%", ["50%off@ejemplo.com"]),
    ("50%", ["50%off@ejemplo.com"]),
    ("_", ["a_b@ejemplo.com"]),
    ("a_b", ["a_b@ejemplo.com"]),
    ("nadie", []),
])
def test_usuarios_filtra_por_correo(cliente_admin, bd, portal, correo, esperados):
    usuarios_para_buscar(bd, portal)
    datos, correos = correos_json(cliente_admin, portal, correo)
    assert correos == esperados
    assert datos["total"] == len(esperados)
    assert datos["totalSinFiltro"] == 7
    assert datos["correo"] == correo.strip() and datos["truncado"] is False
    assert correos_csv(cliente_admin, portal, correo) == esperados


@pytest.mark.parametrize("portal", PORTALES_BUSQUEDA)
@pytest.mark.parametrize("correo", [None, "", "   "])
def test_usuarios_sin_filtro_no_cuenta_aparte(cliente_admin, bd, portal, correo):
    usuarios_para_buscar(bd, portal)
    params = {"portal": portal} if correo is None else {"portal": portal, "correo": correo}
    datos = cliente_admin.get("/api/estadisticas/usuarios", params=params).json()
    assert datos["total"] == datos["totalSinFiltro"] == 7 and datos["correo"] is None
    assert bd.llamadas_historial[-1][-1] is None
    assert not any(ll[0] == "contar_usuarios" for ll in bd.llamadas_historial)


def test_usuarios_filtro_pasa_correo_y_rango_a_la_bd(cliente_admin, bd):
    params = {"portal": "MiraStock", "correo": " Ana ", "desde": "2026-10-01T00:00:00Z"}
    cliente_admin.get("/api/estadisticas/usuarios", params=params)
    assert bd.llamadas_historial == [
        ("usuarios", "MiraStock", datetime(2026, 10, 1), None, main.TOPE_USUARIOS_ESTADISTICAS, "Ana"),
        ("contar_usuarios", "MiraStock", datetime(2026, 10, 1), None),
    ]
    cliente_admin.get("/api/estadisticas/usuarios/csv", params=params)
    assert bd.llamadas_historial[-1] == (
        "usuarios", "MiraStock", datetime(2026, 10, 1), None, main.TOPE_USUARIOS_ESTADISTICAS, "Ana",
    )


def test_usuarios_total_sin_filtro_respeta_el_rango(cliente_admin, bd):
    sesion(bd, "ana@ejemplo.com", "Energía", 5, datetime(2026, 9, 1))
    sesion(bd, "beto@ejemplo.com", "Energía", 5, FECHA)
    sesion(bd, "bruno@ejemplo.com", "Energía", 5, FECHA)
    params = {"portal": "Energía", "correo": "b", "desde": "2026-10-01T00:00:00Z"}
    datos = cliente_admin.get("/api/estadisticas/usuarios", params=params).json()
    assert datos["total"] == 2 and datos["totalSinFiltro"] == 2


@pytest.mark.parametrize("ruta", ["/api/estadisticas/usuarios", "/api/estadisticas/usuarios/csv"])
def test_usuarios_correo_demasiado_largo_422(cliente_admin, bd, ruta):
    resp = cliente_admin.get(ruta, params={"portal": "Energía", "correo": "a" * 257})
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"correo": "El correo no puede superar los 256 caracteres."}
    assert bd.llamadas_historial == []
    assert cliente_admin.get(ruta, params={"portal": "Energía", "correo": "a" * 256}).status_code == 200


def test_usuarios_junta_errores_de_portal_correo_y_fechas(cliente_admin):
    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"correo": "a" * 257, "desde": "x"}).json()
    assert list(datos["errores"]) == ["portal", "correo", "desde"]


def test_portales_ignora_correo(cliente_admin, bd):
    sesion(bd, "ana@ejemplo.com", "Energía", 5)
    sesion(bd, "beto@ejemplo.com", "Energía", 5)
    datos = cliente_admin.get("/api/estadisticas/portales", params={"correo": "ana"}).json()
    # El resumen del portal no se filtra por correo.
    assert datos["portales"][0]["usuariosUnicos"] == 2 and datos["total"]["sesiones"] == 2


def test_usuarios_filtro_con_tope(cliente_admin, bd, monkeypatch):
    monkeypatch.setattr(main, "TOPE_USUARIOS_ESTADISTICAS", 2)
    for i in range(3):
        sesion(bd, f"u{i}@ejemplo.com", "MiraStock", i + 1)
    sesion(bd, "otro@x.com", "MiraStock", 1)
    datos = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": "MiraStock", "correo": "ejemplo"}).json()
    assert datos["truncado"] is True and datos["total"] == 2 and datos["totalSinFiltro"] == 4


def test_js_usuarios_general_tiene_buscador(cliente_admin):
    texto = cliente_admin.get("/static/estadisticas.js").text
    assert "Sin usuarios que coincidan con la búsqueda" in texto
    assert texto.count('placeholder: "Contiene…"') == 2


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def test_csv_portales_formato_hora_local(cliente_admin, bd):
    sesion(bd, "ana@ejemplo.com", "Energía", 52 * 60 + 10, datetime(2026, 10, 20, 2, 15, 7))
    sesion(bd, "beto@ejemplo.com", "Energía", None, datetime(2026, 10, 19, 12, 0))
    sesion(bd, "ana@ejemplo.com", "MiraStock", 44, datetime(2026, 10, 18, 12, 0))
    resp = cliente_admin.get("/api/estadisticas/portales/csv", params={"tz_offset_min": "-180"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"] == f'attachment; filename="estadisticas_portales_{HOY()}.csv"'
    assert resp.content.startswith(b"\xef\xbb\xbf")
    assert lineas_csv(resp) == [
        "Portal;Usuarios únicos;Sesiones;Sesiones medidas;Sin actividad;Horas totales;Minutos totales;Promedio por sesión;"
        "Última conexión (hora local, UTC-03:00)",
        # 2026-10-20 02:15 UTC = 2026-10-19 23:15 en UTC-3
        "Energía;2;2;1;0;52 h 10 min;3130;52 h 10 min;2026-10-19 23:15:07",
        "MiraStock;1;1;1;0;44 min;44;44 min;2026-10-18 09:00:00",
        "Total Portal Corporativo;2;3;2;0;52 h 54 min;3174;26 h 27 min;2026-10-19 23:15:07",
        "",
    ]


def test_csv_portales_utc_y_sin_tiempo_medido(cliente_admin, bd):
    sesion(bd, "a@ejemplo.com", "MiraStock", None)
    sesion(bd, "b@ejemplo.com", "Energía", None, datetime(2026, 9, 1))
    params = {"desde": "2026-10-01T00:00:00Z"}
    lineas = lineas_csv(cliente_admin.get("/api/estadisticas/portales/csv", params=params))
    assert lineas[0].endswith(";Última conexión (UTC)")
    assert lineas[1:] == [
        "Energía;0;0;0;0;;;;",
        "MiraStock;1;1;0;0;;;;2026-10-20 15:30:00",
        "Total Portal Corporativo;1;1;0;0;;;;2026-10-20 15:30:00",
        "",
    ]


def test_csv_portales_neutraliza_formulas(cliente_admin, bd):
    sesion(bd, "a@ejemplo.com", "=Portal", 1)
    assert lineas_csv(cliente_admin.get("/api/estadisticas/portales/csv"))[1].startswith("'=Portal;")


def test_csv_usuarios_formato(cliente_admin, bd):
    sesion(bd, "ana@ejemplo.com", "Energía", 90, usuario="Ana Pérez")
    sesion(bd, "-x@ejemplo.com", "Energía", 0, usuario="@malo")
    resp = cliente_admin.get("/api/estadisticas/usuarios/csv", params={"portal": "Energía", "tz_offset_min": "330"})
    assert resp.headers["content-disposition"] == f'attachment; filename="estadisticas_energia_usuarios_{HOY()}.csv"'
    assert "x-historial-truncado" not in resp.headers
    assert lineas_csv(resp) == [
        "Usuario;Correo;Sesiones;Sesiones medidas;Sin actividad;Horas totales;Minutos totales;Promedio por sesión;"
        "Última conexión (hora local, UTC+05:30)",
        "Ana Pérez;ana@ejemplo.com;1;1;0;1 h 30 min;90;1 h 30 min;2026-10-20 21:00:00",
        "'@malo;'-x@ejemplo.com;1;1;0;< 1 min;0;< 1 min;2026-10-20 21:00:00",
        "",
    ]


@pytest.mark.parametrize("portal, archivo", [
    ("MiraStock", "mirastock"), ("Bodega Norte/Sur", "bodega_norte_sur"), ("Ñandú", "nandu"), ("***", "portal"),
])
def test_csv_usuarios_nombre_de_archivo(cliente_admin, portal, archivo):
    resp = cliente_admin.get("/api/estadisticas/usuarios/csv", params={"portal": portal})
    assert resp.headers["content-disposition"] == f'attachment; filename="estadisticas_{archivo}_usuarios_{HOY()}.csv"'


def test_csv_historial_en_hora_local(cliente_admin, bd):
    inicio = datetime(2026, 10, 20, 1, 0, 0)
    bd.agregar_acceso(inicio, "a@ejemplo.com", final_sesion=inicio + timedelta(minutes=65))
    lineas = lineas_csv(cliente_admin.get("/api/historial/csv", params={"tz_offset_min": "-180"}))
    assert lineas[0] == (
        "Fecha (hora local, UTC-03:00);Usuario;Correo;Portal;Resultado;Final de sesión (hora local, UTC-03:00);"
        "Tiempo de sesión (min);Cierre"
    )
    assert lineas[1] == "2026-10-19 22:00:00;;a@ejemplo.com;Energía;OK;2026-10-19 23:05:00;65;Inactividad"


def test_historial_acepta_cualquier_portal(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", "Bodega Norte")
    datos = cliente_admin.get("/api/historial", params={"portal": "  Bodega Norte "}).json()
    assert datos["total"] == 1
    assert bd.llamadas_historial[-1][1].portal == "Bodega Norte"


# ---------------------------------------------------------------------------
# Formatos del CSV
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("segundos, texto", [
    (None, ""), (-5, "< 1 min"), (0, "< 1 min"), (59, "< 1 min"), (60, "1 min"), (3599, "59 min"),
    (3600, "1 h 00 min"), (187_800, "52 h 10 min"), (3_600_000, "1000 h 00 min"),
])
def test_duracion_texto(segundos, texto):
    assert main._duracion_texto(segundos) == texto


@pytest.mark.parametrize("tz, texto", [
    (0, "UTC"), (-180, "hora local, UTC-03:00"), (-240, "hora local, UTC-04:00"), (330, "hora local, UTC+05:30"),
    (840, "hora local, UTC+14:00"),
])
def test_zona_csv(tz, texto):
    assert main._zona_csv(tz) == texto


# ---------------------------------------------------------------------------
# SQL de db.py (sin BD: se verifica el texto y los parámetros)
# ---------------------------------------------------------------------------

def test_db_estadisticas_portales(cursor_falso):
    desde, hasta = datetime(2026, 10, 1), datetime(2026, 10, 31)
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[
        [("MiraStock",), ("Energía",)],
        [("Energía", 0, 2, 3, 6000, 2000, 3, FECHA, 1), (None, 1, 2, 3, 6000, 2000, 3, FECHA, 1)],
    ])
    datos = db.estadisticas_portales(desde, hasta)
    medidas = {
        "sesiones": 3, "segundosTotales": 6000, "promedioSeg": 2000, "sesionesMedidas": 3, "ultimaConexion": FECHA,
        "sinActividad": 1,
    }
    assert datos == {
        "portales": [
            {"portal": "Energía", "usuariosUnicos": 2, **medidas},
            {"portal": "MiraStock", "usuariosUnicos": 0, **SIN_SESIONES},
        ],
        "total": {"usuariosUnicos": 2, **medidas},
    }
    (sql_portales, p_portales), (sql, params) = cur.ejecutados
    assert sql_portales == "SELECT DISTINCT Portal FROM core.vHistorialAccesos WHERE Portal IS NOT NULL"
    assert p_portales == ()
    assert "SELECT Portal, GROUPING(Portal), COUNT(DISTINCT Correo), COUNT(*)" in sql
    assert "AVG(CAST(TiempoSesionSeg AS BIGINT)), COUNT(TiempoSesionSeg), MAX(Fecha)" in sql
    assert "WHERE Resultado = ? AND Fecha >= ? AND Fecha < ? AND Portal IS NOT NULL" in sql
    assert sql.endswith("GROUP BY GROUPING SETS ((Portal), ())")
    assert params == ("OK", desde, hasta)


def test_db_estadisticas_portales_sin_fila_total(cursor_falso):
    cursor_falso["cursor"] = CursorFalso(uno=[], todos=[[], []])
    assert db.estadisticas_portales(None, None) == {"portales": [], "total": {"usuariosUnicos": 0, **SIN_SESIONES}}


def test_db_estadisticas_usuarios(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[[
        ("a@ejemplo.com", " Ana ", 2, 600, 300, 2, FECHA, 1),
        ("b@ejemplo.com", None, 1, None, None, 0, FECHA, 0),
        ("c@ejemplo.com", "", 1, None, None, 0, FECHA, None),
    ]])
    filas, truncado = db.estadisticas_usuarios("Energía", None, datetime(2026, 11, 1), 2)
    assert truncado is True
    assert filas == [
        {"usuario": "Ana", "correo": "a@ejemplo.com", "sesiones": 2, "segundosTotales": 600, "promedioSeg": 300,
         "sesionesMedidas": 2, "ultimaConexion": FECHA, "sinActividad": 1},
        {"usuario": "", "correo": "b@ejemplo.com", **SIN_SESIONES, "sesiones": 1, "ultimaConexion": FECHA},
    ]
    ((sql, params),) = cur.ejecutados
    assert sql.startswith("SELECT TOP (?) Correo, MAX(ISNULL(Usuario, '')), COUNT(*)")
    assert "FROM core.vHistorialAccesos WHERE Portal = ? AND Resultado = ? AND Fecha < ? GROUP BY Correo" in sql
    assert sql.endswith("ORDER BY ISNULL(SUM(CAST(TiempoSesionSeg AS BIGINT)), 0) DESC, COUNT(*) DESC, Correo")
    assert params == (3, "Energía", "OK", datetime(2026, 11, 1))


def test_db_estadisticas_usuarios_con_correo_escapa_like(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[[]])
    assert db.estadisticas_usuarios("MiraStock", None, None, 10, " 50%_A[\\ ") == ([], False)
    ((sql, params),) = cur.ejecutados
    assert "WHERE Correo LIKE ? ESCAPE '\\' AND Portal = ? AND Resultado = ? GROUP BY Correo" in sql
    assert params == (11, "%50\\%\\_a\\[\\\\%", "MiraStock", "OK")


def test_db_contar_usuarios_portal(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[(7,)], todos=[])
    desde, hasta = datetime(2026, 10, 1), datetime(2026, 10, 31)
    assert db.contar_usuarios_portal("Energía", desde, hasta) == 7
    ((sql, params),) = cur.ejecutados
    assert sql == (
        "SELECT COUNT(DISTINCT Correo) FROM core.vHistorialAccesos"
        " WHERE Portal = ? AND Resultado = ? AND Fecha >= ? AND Fecha < ?"
    )
    assert params == ("Energía", "OK", desde, hasta)
