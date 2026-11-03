"""v16: gráficos de /estadisticas — /api/estadisticas/series y /api/estadisticas/distribucion."""

from datetime import date, datetime, timedelta

import pytest

from app import db, main
from tests.test_historial import CursorFalso, cursor_falso, revocar_admin  # noqa: F401 (fixture)

LUNES = datetime(2026, 11, 2, 15, 0, 0)    # lunes 2026-11-02 15:00 UTC
DOMINGO = datetime(2026, 11, 8, 23, 30, 0)  # domingo 2026-11-08 23:30 UTC


def sesion(bd, fecha, correo="a@ejemplo.com", portal="Energía", segundos=None, **kwargs):
    final = fecha + timedelta(seconds=segundos) if segundos is not None else None
    bd.agregar_acceso(fecha, correo, portal, kwargs.pop("resultado", "OK"), final_sesion=final, **kwargs)


def rango(desde, hasta):
    return {"desde": desde, "hasta": hasta}


# ---------------------------------------------------------------------------
# Autorización y validación
# ---------------------------------------------------------------------------

ENDPOINTS = [
    ("/api/estadisticas/series", {}),
    ("/api/estadisticas/distribucion", {"portal": "Energía"}),
]


@pytest.mark.parametrize("ruta, params", ENDPOINTS)
def test_sin_sesion_401(cliente, ruta, params):
    resp = cliente.get(ruta, params=params)
    assert resp.status_code == 401 and "detail" in resp.json()


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
    ({"tz_offset_min": "841"}, "tz_offset_min"),
    ({"tz_offset_min": "x"}, "tz_offset_min"),
    ({"portal": "x" * 51}, "portal"),
])
def test_validaciones_422(cliente_admin, bd, ruta, params, malos, campo):
    resp = cliente_admin.get(ruta, params={**params, **malos})
    assert resp.status_code == 422
    assert campo in resp.json()["errores"]
    assert bd.llamadas_historial == []


@pytest.mark.parametrize("portal", [None, "", "   "])
def test_distribucion_exige_portal(cliente_admin, bd, portal):
    params = {} if portal is None else {"portal": portal}
    resp = cliente_admin.get("/api/estadisticas/distribucion", params=params)
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"portal": "Indica el portal."}
    assert bd.llamadas_historial == []


def test_distribucion_no_acepta_filtro_de_correo(cliente_admin, bd):
    cliente_admin.get("/api/estadisticas/distribucion", params={"portal": "Energía", "correo": "a"})
    assert bd.llamadas_historial == [("distribucion", "Energía", None, None, 0)]


# ---------------------------------------------------------------------------
# /series
# ---------------------------------------------------------------------------

def test_series_sin_datos_y_sin_fechas(cliente_admin):
    assert cliente_admin.get("/api/estadisticas/series").json() == {
        "dias": [], "portales": [], "total": {"sesiones": [], "segundos": [], "usuarios": []},
    }


def test_series_rellena_con_ceros_y_desglosa_por_portal(cliente_admin, bd):
    sesion(bd, LUNES, "ana@ejemplo.com", "Energía", 600)
    sesion(bd, LUNES + timedelta(hours=1), "ana@ejemplo.com", "Energía", 300)
    sesion(bd, LUNES + timedelta(hours=2), "ana@ejemplo.com", "MiraStock", 120)
    sesion(bd, LUNES + timedelta(hours=3), "beto@ejemplo.com", "MiraStock")  # sin tiempo
    sesion(bd, LUNES + timedelta(days=2), "beto@ejemplo.com", "Energía", 60)
    sesion(bd, LUNES, "carla@ejemplo.com", "Energía", resultado="Denegado")  # no es sesión
    params = rango("2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z")
    datos = cliente_admin.get("/api/estadisticas/series", params=params).json()
    assert datos["dias"] == ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    assert datos["portales"] == [
        {"portal": "Energía", "sesiones": [0, 2, 0, 1], "segundos": [0, 900, 0, 60], "usuarios": [0, 1, 0, 1]},
        {"portal": "MiraStock", "sesiones": [0, 2, 0, 0], "segundos": [0, 120, 0, 0], "usuarios": [0, 2, 0, 0]},
    ]
    # El total no repite usuarios entre portales: el lunes, ana (en los dos) y beto = 2.
    assert datos["total"] == {"sesiones": [0, 4, 0, 1], "segundos": [0, 1020, 0, 60], "usuarios": [0, 2, 0, 1]}
    assert bd.llamadas_historial[-1] == ("series", None, datetime(2026, 11, 1), datetime(2026, 11, 5), 0)


def test_series_portal_conocido_sin_sesiones_aparece_en_ceros(cliente_admin, bd):
    sesion(bd, LUNES, portal="Energía", segundos=60)
    sesion(bd, datetime(2026, 9, 1), portal="MiraStock", segundos=60)
    datos = cliente_admin.get("/api/estadisticas/series", params=rango("2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z")).json()
    assert [(p["portal"], p["sesiones"]) for p in datos["portales"]] == [("Energía", [1]), ("MiraStock", [0])]


@pytest.mark.parametrize("portal", ["Energía", "MiraStock", "Bodega Norte"])
def test_series_de_un_portal(cliente_admin, bd, portal):
    sesion(bd, LUNES, "a@ejemplo.com", portal, 60)
    sesion(bd, LUNES, "b@ejemplo.com", "Otro Portal", 60)
    datos = cliente_admin.get(
        "/api/estadisticas/series", params={"portal": portal, **rango("2026-11-02T00:00:00Z", "2026-11-04T00:00:00Z")}
    ).json()
    assert datos["portales"] == [{"portal": portal, "sesiones": [1, 0], "segundos": [60, 0], "usuarios": [1, 0]}]
    assert datos["total"]["sesiones"] == [1, 0]


def test_series_sin_fechas_rellena_entre_el_primer_y_el_ultimo_dia_con_datos(cliente_admin, bd):
    sesion(bd, LUNES, segundos=60)
    sesion(bd, LUNES + timedelta(days=3), segundos=60)
    datos = cliente_admin.get("/api/estadisticas/series").json()
    assert datos["dias"] == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]
    assert datos["total"]["sesiones"] == [1, 0, 0, 1]


def test_series_solo_desde_rellena_hasta_el_ultimo_dia_con_datos(cliente_admin, bd):
    sesion(bd, LUNES, segundos=60)
    datos = cliente_admin.get("/api/estadisticas/series", params={"desde": "2026-10-31T00:00:00Z"}).json()
    assert datos["dias"] == ["2026-10-31", "2026-11-01", "2026-11-02"]


def test_series_con_fechas_y_sin_datos_devuelve_los_dias_en_cero(cliente_admin):
    datos = cliente_admin.get("/api/estadisticas/series", params=rango("2026-11-01T00:00:00Z", "2026-11-03T00:00:00Z")).json()
    assert datos["dias"] == ["2026-11-01", "2026-11-02"] and datos["total"]["sesiones"] == [0, 0]


def test_series_agrupa_en_hora_local(cliente_admin, bd):
    # 2026-11-03 01:30 UTC = 2026-11-02 22:30 en UTC-3.
    sesion(bd, datetime(2026, 11, 3, 1, 30), segundos=60)
    params = {"desde": "2026-11-02T03:00:00Z", "hasta": "2026-11-04T03:00:00Z", "tz_offset_min": "-180"}
    datos = cliente_admin.get("/api/estadisticas/series", params=params).json()
    assert datos["dias"] == ["2026-11-02", "2026-11-03"]
    assert datos["total"]["sesiones"] == [1, 0]
    assert bd.llamadas_historial[-1][-1] == -180


@pytest.mark.parametrize("dias, ok", [(731, True), (732, False)])
def test_series_tope_de_731_dias(cliente_admin, bd, dias, ok):
    desde = datetime(2025, 1, 1)
    params = rango(desde.isoformat() + "Z", (desde + timedelta(days=dias)).isoformat() + "Z")
    resp = cliente_admin.get("/api/estadisticas/series", params=params)
    if ok:
        assert resp.status_code == 200 and len(resp.json()["dias"]) == 731
    else:
        assert resp.status_code == 422
        assert resp.json()["errores"] == {"hasta": "El rango no puede superar los 731 días."}
        assert bd.llamadas_historial == []


def test_series_sin_fechas_y_datos_de_mas_de_731_dias_422(cliente_admin, bd):
    sesion(bd, datetime(2023, 1, 1), segundos=60)
    sesion(bd, LUNES, segundos=60)
    resp = cliente_admin.get("/api/estadisticas/series")
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"hasta": "El rango no puede superar los 731 días: indica «desde» y «hasta»."}


def test_limites_series_hasta_exclusivo_en_hora_local():
    filtros = db.FiltrosHistorial(desde=datetime(2026, 11, 1, 3), hasta=datetime(2026, 11, 3, 3))
    assert main._limites_series(filtros, -180) == (date(2026, 11, 1), date(2026, 11, 2))
    assert main._limites_series(filtros, 0) == (date(2026, 11, 1), date(2026, 11, 3))
    assert main._limites_series(db.FiltrosHistorial(), 0) == (None, None)


# ---------------------------------------------------------------------------
# /distribucion
# ---------------------------------------------------------------------------

def test_distribucion_sin_datos(cliente_admin):
    datos = cliente_admin.get("/api/estadisticas/distribucion", params={"portal": "Energía"}).json()
    assert datos["portal"] == "Energía"
    assert datos["cierres"] == {"Botón": 0, "Inactividad": 0, "Sin actividad": 0, "En curso": 0, "No medida": 0, "Otro": 0}
    assert [r["etiqueta"] for r in datos["duracion"]["rangos"]] == [
        "< 5 min", "5–15 min", "15–30 min", "30–60 min", "> 1 h",
    ]
    assert all(r["sesiones"] == 0 for r in datos["duracion"]["rangos"])
    assert datos["duracion"]["sinActividad"] == datos["duracion"]["sinMedir"] == 0
    assert len(datos["calor"]) == 7 and all(len(f) == 24 and not any(f) for f in datos["calor"])


def test_distribucion_cierres_con_prioridad(cliente_admin, bd):
    f = LUNES
    sesion(bd, f, segundos=120, cierre=True, en_curso=True)          # Botón gana a todo
    sesion(bd, f, segundos=120, en_curso=True)                       # En curso
    sesion(bd, f, segundos=120)                                      # Inactividad
    sesion(bd, f, segundos=120)                                      # Inactividad
    sesion(bd, f, sin_actividad=True)                                # Sin actividad
    sesion(bd, f, medible=False)                                     # No medida
    sesion(bd, f)                                                    # medible sin datos → Otro
    sesion(bd, f, medible=False, resultado="Denegado")               # no cuenta
    sesion(bd, f, portal="MiraStock", cierre=True, segundos=5)       # otro portal
    datos = cliente_admin.get("/api/estadisticas/distribucion", params={"portal": "Energía"}).json()
    assert datos["cierres"] == {
        "Botón": 1, "Inactividad": 2, "Sin actividad": 1, "En curso": 1, "No medida": 1, "Otro": 1,
    }


def test_distribucion_rangos_de_duracion_en_sus_bordes(cliente_admin, bd):
    for segundos in (0, 299, 300, 899, 900, 1799, 1800, 3599, 3600, 50_000):
        sesion(bd, LUNES, segundos=segundos)
    sesion(bd, LUNES, sin_actividad=True)  # 0 s, pero va aparte
    sesion(bd, LUNES, sin_actividad=True)
    sesion(bd, LUNES, medible=False)       # sin medir
    sesion(bd, LUNES, en_curso=True)       # en curso sin latido: sin medir
    duracion = cliente_admin.get("/api/estadisticas/distribucion", params={"portal": "Energía"}).json()["duracion"]
    assert [(r["etiqueta"], r["sesiones"]) for r in duracion["rangos"]] == [
        ("< 5 min", 2), ("5–15 min", 2), ("15–30 min", 2), ("30–60 min", 2), ("> 1 h", 2),
    ]
    assert duracion["sinActividad"] == 2 and duracion["sinMedir"] == 2


def test_distribucion_mapa_de_calor_dia_y_hora(cliente_admin, bd):
    sesion(bd, LUNES)                              # lunes 15 h
    sesion(bd, LUNES + timedelta(minutes=20))      # lunes 15 h
    sesion(bd, DOMINGO)                            # domingo 23 h
    sesion(bd, datetime(2026, 11, 4, 0, 0))        # miércoles 0 h
    calor = cliente_admin.get("/api/estadisticas/distribucion", params={"portal": "Energía"}).json()["calor"]
    assert calor[0][15] == 2 and calor[6][23] == 1 and calor[2][0] == 1
    assert sum(map(sum, calor)) == 4


def test_distribucion_mapa_de_calor_en_hora_local_cambia_el_dia(cliente_admin, bd):
    # Lunes 2026-11-09 01:00 UTC = domingo 2026-11-08 22:00 en UTC-3; con UTC+5:30 = lunes 06:30.
    sesion(bd, datetime(2026, 11, 9, 1, 0))
    menos3 = cliente_admin.get(
        "/api/estadisticas/distribucion", params={"portal": "Energía", "tz_offset_min": "-180"}
    ).json()["calor"]
    assert menos3[6][22] == 1
    mas530 = cliente_admin.get(
        "/api/estadisticas/distribucion", params={"portal": "Energía", "tz_offset_min": "330"}
    ).json()["calor"]
    assert mas530[0][6] == 1


def test_distribucion_respeta_el_rango(cliente_admin, bd):
    sesion(bd, LUNES, segundos=60)
    sesion(bd, LUNES - timedelta(days=30), segundos=60)
    params = {"portal": "energía", **rango("2026-11-01T00:00:00Z", "2026-11-03T00:00:00Z")}
    datos = cliente_admin.get("/api/estadisticas/distribucion", params=params).json()
    assert datos["portal"] == "Energía" and datos["cierres"]["Inactividad"] == 1
    assert bd.llamadas_historial[-1] == ("distribucion", "Energía", datetime(2026, 11, 1), datetime(2026, 11, 3), 0)


def test_distribucion_portal_nuevo_sin_codigo(cliente_admin, bd):
    sesion(bd, LUNES, portal="Bodega Norte", segundos=1000)
    datos = cliente_admin.get("/api/estadisticas/distribucion", params={"portal": "Bodega Norte"}).json()
    assert datos["cierres"]["Inactividad"] == 1 and datos["duracion"]["rangos"][2]["sesiones"] == 1


# ---------------------------------------------------------------------------
# SQL de db.py (cursor falso)
# ---------------------------------------------------------------------------

def test_db_estadisticas_series_sql(cursor_falso):
    desde, hasta = datetime(2026, 11, 1), datetime(2026, 11, 5)
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[
        [("MiraStock",), ("Energía",)],
        [(date(2026, 11, 2), "Energía", 0, 2, 900, 1), (date(2026, 11, 2), None, 1, 3, 900, 2),
         ("2026-11-03", "MiraStock", 0, 1, None, 1)],
    ])
    datos = db.estadisticas_series(None, desde, hasta, -180)
    assert datos == {
        "portales": ["Energía", "MiraStock"],
        "filas": [
            {"dia": date(2026, 11, 2), "portal": "Energía", "sesiones": 2, "segundos": 900, "usuarios": 1},
            {"dia": date(2026, 11, 2), "portal": None, "sesiones": 3, "segundos": 900, "usuarios": 2},
            {"dia": date(2026, 11, 3), "portal": "MiraStock", "sesiones": 1, "segundos": 0, "usuarios": 1},
        ],
    }
    (sql_portales, _), (sql, params) = cur.ejecutados
    assert sql_portales == "SELECT DISTINCT Portal FROM core.vHistorialAccesos WHERE Portal IS NOT NULL"
    assert sql.startswith("SELECT Dia, Portal, GROUPING(Portal), COUNT(*),")
    assert "ISNULL(SUM(CAST(TiempoSesionSeg AS BIGINT)), 0), COUNT(DISTINCT Correo)" in sql
    assert "FROM (SELECT CAST(DATEADD(minute, ?, Fecha) AS date) AS Dia, Portal, Correo, TiempoSesionSeg" in sql
    assert ("FROM core.vHistorialAccesos WHERE Resultado = ? AND Fecha >= ? AND Fecha < ?"
            " AND Portal IS NOT NULL AND Fecha IS NOT NULL) s") in sql
    assert sql.endswith("GROUP BY GROUPING SETS ((Dia, Portal), (Dia)) ORDER BY Dia")
    assert params == (-180, "OK", desde, hasta)


def test_db_estadisticas_series_con_portal_no_lista_portales(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[[]])
    assert db.estadisticas_series("Energía", None, None, 0) == {"portales": ["Energía"], "filas": []}
    ((sql, params),) = cur.ejecutados
    assert "WHERE Portal = ? AND Resultado = ? AND Portal IS NOT NULL" in sql
    assert params == (0, "Energía", "OK")


def test_db_estadisticas_distribucion_sql(cursor_falso):
    desde = datetime(2026, 11, 1)
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[
        [("Botón", 2), ("Inactividad", 5), ("Raro", 1)],
        [(0, 3), (4, 1), (-1, 2), (-2, 6)],
        [(0, 15, 4), (6, 23, 1)],
    ])
    datos = db.estadisticas_distribucion("Energía", desde, None, 330)
    assert datos["cierres"] == {
        "Botón": 2, "Inactividad": 5, "Sin actividad": 0, "En curso": 0, "No medida": 0, "Otro": 1,
    }
    assert datos["duracion"] == [3, 0, 0, 0, 1] and datos["sinActividad"] == 2 and datos["sinMedir"] == 6
    assert datos["calor"][0][15] == 4 and datos["calor"][6][23] == 1 and sum(map(sum, datos["calor"])) == 5

    (sql_c, p_c), (sql_d, p_d), (sql_h, p_h) = cur.ejecutados
    where = "FROM core.vHistorialAccesos WHERE Portal = ? AND Resultado = ? AND Fecha >= ?"
    assert sql_c == (
        "SELECT Cierre, COUNT(*) FROM (SELECT CASE WHEN CierreExplicito = 1 THEN N'Botón'"
        " WHEN EnCurso = 1 THEN N'En curso' WHEN FinalSesion IS NOT NULL THEN N'Inactividad'"
        " WHEN SinActividad = 1 THEN N'Sin actividad' WHEN ISNULL(Medible, 0) = 0 THEN N'No medida'"
        f" ELSE N'Otro' END AS Cierre {where}) c GROUP BY Cierre"
    )
    assert p_c == p_d == ("Energía", "OK", desde)
    assert sql_d == (
        "SELECT Rango, COUNT(*) FROM (SELECT CASE WHEN SinActividad = 1 THEN -1"
        " WHEN TiempoSesionSeg IS NULL THEN -2 WHEN TiempoSesionSeg < 300 THEN 0"
        " WHEN TiempoSesionSeg < 900 THEN 1 WHEN TiempoSesionSeg < 1800 THEN 2"
        f" WHEN TiempoSesionSeg < 3600 THEN 3 ELSE 4 END AS Rango {where}) d GROUP BY Rango"
    )
    # Día de la semana sin @@DATEFIRST: días desde 1900-01-01 (lunes) módulo 7.
    assert sql_h == (
        "SELECT DATEDIFF(day, '19000101', CAST(L AS date)) % 7, DATEPART(hour, L), COUNT(*)"
        f" FROM (SELECT DATEADD(minute, ?, Fecha) AS L {where} AND Fecha IS NOT NULL) x"
        " GROUP BY DATEDIFF(day, '19000101', CAST(L AS date)) % 7, DATEPART(hour, L)"
    )
    assert "DATEFIRST" not in sql_h and "WEEKDAY" not in sql_h.upper()
    assert p_h == (330, "Energía", "OK", desde)


def test_bordes_de_duracion_coinciden_con_el_sql():
    for borde in db.BORDES_DURACION:
        assert f"TiempoSesionSeg < {borde} THEN" in db._CASE_DURACION
    assert len(main.ETIQUETAS_DURACION) == len(db.BORDES_DURACION) + 1


# ---------------------------------------------------------------------------
# Página y archivos estáticos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", ["/estadisticas/general", "/estadisticas/portal/energia"])
def test_pagina_carga_chartjs_antes_que_los_graficos(cliente_admin, ruta):
    texto = cliente_admin.get(ruta).text
    orden = [
        '<script src="/static/vendor/chart.umd.4.4.7.min.js?v=16" defer></script>',
        '<script src="/static/comun.js?v=16" defer></script>',
        '<script src="/static/graficos.js?v=16" defer></script>',
        '<script src="/static/estadisticas.js?v=16" defer></script>',
    ]
    posiciones = [texto.index(s) for s in orden]
    assert posiciones == sorted(posiciones)
    assert "cdn" not in texto.lower() and 'style="' not in texto


def test_chartjs_alojado_con_su_licencia(cliente_admin):
    resp = cliente_admin.get("/static/vendor/chart.umd.4.4.7.min.js")
    assert resp.status_code == 200
    assert resp.text.startswith("/*!\n * Chart.js v4.4.7")
    assert "eval(" not in resp.text and "new Function" not in resp.text
    licencia = cliente_admin.get("/static/vendor/chart.js-LICENSE.md")
    assert licencia.status_code == 200 and "The MIT License" in licencia.text


def test_csp_no_se_afloja(cliente_admin):
    csp = cliente_admin.get("/estadisticas").headers["content-security-policy"]
    assert "script-src 'self';" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "cdn" not in csp


def test_graficos_js_nombra_portales_solo_en_el_mapa_de_colores(cliente_admin):
    texto = cliente_admin.get("/static/graficos.js").text
    mapa = 'const COLORES_PORTAL = { "energía": "#d9a441", "mirastock": "#29b8ec" };'
    assert texto.count(mapa) == 1
    resto = texto.replace(mapa, "")
    for nombre in ("energía", "Energía", "mirastock", "MiraStock"):
        assert nombre not in resto
    assert "const PALETA = [" in texto and "PALETA.length" in texto


def test_estadisticas_js_usa_los_endpoints_nuevos_y_destruye_graficos(cliente_admin):
    js = cliente_admin.get("/static/estadisticas.js").text
    assert "/api/estadisticas/series?" in js and "/api/estadisticas/distribucion?" in js
    graficos = cliente_admin.get("/static/graficos.js").text
    assert "panel.chart.destroy()" in graficos and "new Chart(" in graficos
    assert 'setAttribute("style"' not in graficos + js and ".innerHTML" not in graficos + js
