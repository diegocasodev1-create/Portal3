"""v17: buscador por correo de los gráficos de cada portal.

/api/estadisticas/resumen (nuevo), /series (con portal) y /distribucion aceptan `correo` (contiene, sin distinguir
mayúsculas, comodines de LIKE literales, hasta 256 caracteres). Sin `correo` todo responde igual que en v16, y
/portales (vista general, inicio) no cambia.
"""

from datetime import datetime, timedelta

import pytest

from app import db
from tests.test_historial import CursorFalso, cursor_falso, revocar_admin  # noqa: F401 (fixture)

LUNES = datetime(2026, 11, 2, 15, 0, 0)  # lunes 2026-11-02 15:00 UTC
RANGO = {"desde": "2026-11-01T00:00:00Z", "hasta": "2026-11-05T00:00:00Z"}


def sesion(bd, fecha, correo, portal="Energía", segundos=None, **kwargs):
    final = fecha + timedelta(seconds=segundos) if segundos is not None else None
    bd.agregar_acceso(fecha, correo, portal, kwargs.pop("resultado", "OK"), final_sesion=final, **kwargs)


@pytest.fixture
def datos(bd):
    """Ana: 3 sesiones en 2 días (Energía); beto: 1; un correo con % y _ literales; MiraStock aparte."""
    sesion(bd, LUNES, "ana.perez@entel.pe", segundos=600)
    sesion(bd, LUNES + timedelta(hours=1), "ana.perez@entel.pe", segundos=300)
    sesion(bd, LUNES + timedelta(days=1), "ana.perez@entel.pe", segundos=1200, cierre=True)
    sesion(bd, LUNES, "beto@miragroup.cl", segundos=60)
    sesion(bd, LUNES + timedelta(days=2), "con_raya%100@ejemplo.com", segundos=120)
    sesion(bd, LUNES, "conXraya@ejemplo.com", segundos=30)
    sesion(bd, LUNES, "ana.perez@entel.pe", resultado="Denegado")  # no es sesión
    sesion(bd, LUNES, "ana.perez@entel.pe", portal="MiraStock", segundos=999)  # otro portal
    return bd


def get(cliente, ruta, **params):
    return cliente.get(ruta, params={**RANGO, **params})


# ---------------------------------------------------------------------------
# Autorización y validación (los tres endpoints que filtran los gráficos de un portal)
# ---------------------------------------------------------------------------

RUTAS = ["/api/estadisticas/resumen", "/api/estadisticas/series", "/api/estadisticas/distribucion"]


def test_resumen_sin_sesion_401(cliente):
    assert cliente.get("/api/estadisticas/resumen", params={"portal": "Energía"}).status_code == 401


def test_resumen_admin_desactivado_401(cliente_admin, bd):
    revocar_admin(bd)
    assert cliente_admin.get("/api/estadisticas/resumen", params={"portal": "Energía"}).status_code == 401


def test_resumen_401_antes_que_validar(cliente):
    assert cliente.get("/api/estadisticas/resumen", params={"correo": "x" * 257}).status_code == 401


@pytest.mark.parametrize("ruta", RUTAS)
def test_correo_de_257_caracteres_422(cliente_admin, bd, ruta):
    resp = get(cliente_admin, ruta, portal="Energía", correo="x" * 257)
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"correo": "El correo no puede superar los 256 caracteres."}
    assert bd.llamadas_historial == []


@pytest.mark.parametrize("ruta", RUTAS)
def test_correo_de_256_caracteres_se_acepta(cliente_admin, bd, ruta):
    assert get(cliente_admin, ruta, portal="Energía", correo="x" * 256).status_code == 200


@pytest.mark.parametrize("portal", [None, "", "   "])
def test_resumen_exige_portal(cliente_admin, bd, portal):
    params = {"correo": "ana"} if portal is None else {"portal": portal, "correo": "ana"}
    resp = cliente_admin.get("/api/estadisticas/resumen", params=params)
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"portal": "Indica el portal."}
    assert bd.llamadas_historial == []


@pytest.mark.parametrize("portal", [None, "", "   "])
def test_series_con_correo_sin_portal_422(cliente_admin, bd, portal):
    params = {"correo": "ana"} if portal is None else {"portal": portal, "correo": "ana"}
    resp = cliente_admin.get("/api/estadisticas/series", params=params)
    assert resp.status_code == 422
    assert resp.json()["errores"] == {"correo": "Indica el portal para buscar por correo."}
    assert bd.llamadas_historial == []


def test_series_junta_errores_de_correo_y_fechas(cliente_admin, bd):
    resp = cliente_admin.get("/api/estadisticas/series", params={"correo": "ana", "desde": "ayer"})
    assert resp.status_code == 422
    assert set(resp.json()["errores"]) == {"correo", "desde"}


@pytest.mark.parametrize("correo", ["", "   "])
def test_series_correo_vacio_sin_portal_es_la_vista_general(cliente_admin, datos, correo):
    resp = get(cliente_admin, "/api/estadisticas/series", correo=correo)
    assert resp.status_code == 200
    assert [p["portal"] for p in resp.json()["portales"]] == ["Energía", "MiraStock"]
    assert datos.llamadas_historial[-1] == ("series", None, datetime(2026, 11, 1), datetime(2026, 11, 5), 0)


# ---------------------------------------------------------------------------
# /resumen
# ---------------------------------------------------------------------------

def test_resumen_sin_correo_coincide_con_la_fila_del_portal_en_portales(cliente_admin, datos):
    resumen = get(cliente_admin, "/api/estadisticas/resumen", portal="Energía").json()
    portales = get(cliente_admin, "/api/estadisticas/portales").json()
    fila = next(p for p in portales["portales"] if p["portal"] == "Energía")
    assert resumen == {"portal": "Energía", "correo": None, **{k: v for k, v in fila.items() if k != "slug"}}
    assert resumen["usuariosUnicos"] == 4 and resumen["sesiones"] == 6


def test_resumen_usuarios_unicos_correctos_con_filtro(cliente_admin, datos):
    # Ana tiene sesiones en dos días distintos: cuenta 1 usuario, no 2.
    r = get(cliente_admin, "/api/estadisticas/resumen", portal="Energía", correo="ana").json()
    assert r == {
        "portal": "Energía", "correo": "ana", "usuariosUnicos": 1, "sesiones": 3,
        "segundosTotales": 2100, "promedioSeg": 700, "sesionesMedidas": 3,
        "ultimaConexion": "2026-11-03T15:00:00Z", "sinActividad": 0,
    }
    assert datos.llamadas_historial[-1] == (
        "resumen_portal", "Energía", datetime(2026, 11, 1), datetime(2026, 11, 5), "ana",
    )


def test_resumen_coincidencia_parcial_y_varios_usuarios(cliente_admin, datos):
    r = get(cliente_admin, "/api/estadisticas/resumen", portal="Energía", correo="ejemplo.com").json()
    assert r["usuariosUnicos"] == 2 and r["sesiones"] == 2


def test_resumen_sin_distinguir_mayusculas(cliente_admin, datos):
    r = get(cliente_admin, "/api/estadisticas/resumen", portal="Energía", correo="  ANA.Perez@ENTEL  ").json()
    assert r["correo"] == "ANA.Perez@ENTEL" and r["usuariosUnicos"] == 1 and r["sesiones"] == 3


@pytest.mark.parametrize("correo, sesiones", [("_", 1), ("%", 1), ("a%1", 1), ("n_r", 1), ("x%", 0)])
def test_resumen_comodines_literales(cliente_admin, datos, correo, sesiones):
    # «_» y «%» se buscan como caracteres: «conXraya» no coincide con «n_r».
    assert get(cliente_admin, "/api/estadisticas/resumen", portal="Energía", correo=correo).json()["sesiones"] == sesiones


def test_resumen_sin_coincidencias_en_cero(cliente_admin, datos):
    r = get(cliente_admin, "/api/estadisticas/resumen", portal="Energía", correo="nadie").json()
    assert r == {
        "portal": "Energía", "correo": "nadie", "usuariosUnicos": 0, "sesiones": 0, "segundosTotales": None,
        "promedioSeg": None, "sesionesMedidas": 0, "ultimaConexion": None, "sinActividad": 0,
    }


def test_resumen_portal_nuevo(cliente_admin, bd):
    sesion(bd, LUNES, "zoe@ejemplo.com", portal="Bodega Norte", segundos=60, sin_actividad=False)
    r = get(cliente_admin, "/api/estadisticas/resumen", portal="Bodega Norte", correo="zoe").json()
    assert r["usuariosUnicos"] == 1 and r["sesiones"] == 1


# ---------------------------------------------------------------------------
# /series con portal
# ---------------------------------------------------------------------------

def test_series_sin_correo_igual_que_antes(cliente_admin, datos):
    s = get(cliente_admin, "/api/estadisticas/series", portal="Energía").json()
    assert s["portales"] == [{
        "portal": "Energía", "sesiones": [0, 4, 1, 1], "segundos": [0, 990, 1200, 120], "usuarios": [0, 3, 1, 1],
    }]
    assert datos.llamadas_historial[-1] == ("series", "Energía", datetime(2026, 11, 1), datetime(2026, 11, 5), 0)


def test_series_con_correo(cliente_admin, datos):
    s = get(cliente_admin, "/api/estadisticas/series", portal="Energía", correo="ANA").json()
    assert s["dias"] == ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    assert s["portales"] == [{
        "portal": "Energía", "sesiones": [0, 2, 1, 0], "segundos": [0, 900, 1200, 0], "usuarios": [0, 1, 1, 0],
    }]
    assert s["total"] == {"sesiones": [0, 2, 1, 0], "segundos": [0, 900, 1200, 0], "usuarios": [0, 1, 1, 0]}
    assert datos.llamadas_historial[-1] == (
        "series", "Energía", datetime(2026, 11, 1), datetime(2026, 11, 5), 0, "ANA",
    )


@pytest.mark.parametrize("correo, sesiones", [("_", [0, 0, 0, 1]), ("%", [0, 0, 0, 1]), ("n_r", [0, 0, 0, 1])])
def test_series_comodines_literales(cliente_admin, datos, correo, sesiones):
    s = get(cliente_admin, "/api/estadisticas/series", portal="Energía", correo=correo).json()
    assert s["portales"][0]["sesiones"] == sesiones


def test_series_sin_coincidencias_dias_en_cero(cliente_admin, datos):
    s = get(cliente_admin, "/api/estadisticas/series", portal="Energía", correo="nadie").json()
    assert s["dias"] == ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    assert s["portales"] == [{"portal": "Energía", "sesiones": [0] * 4, "segundos": [0] * 4, "usuarios": [0] * 4}]


# ---------------------------------------------------------------------------
# /distribucion
# ---------------------------------------------------------------------------

def test_distribucion_sin_correo_igual_que_antes(cliente_admin, datos):
    d = get(cliente_admin, "/api/estadisticas/distribucion", portal="Energía").json()
    assert d["correo"] is None
    assert d["cierres"]["Botón"] == 1 and d["cierres"]["Inactividad"] == 5
    assert datos.llamadas_historial[-1] == (
        "distribucion", "Energía", datetime(2026, 11, 1), datetime(2026, 11, 5), 0,
    )


def test_distribucion_con_correo(cliente_admin, datos):
    d = get(cliente_admin, "/api/estadisticas/distribucion", portal="Energía", correo="Ana.Perez").json()
    assert d["correo"] == "Ana.Perez"
    assert d["cierres"] == {"Botón": 1, "Inactividad": 2, "Sin actividad": 0, "En curso": 0, "No medida": 0, "Otro": 0}
    assert [r["sesiones"] for r in d["duracion"]["rangos"]] == [0, 2, 1, 0, 0]
    assert d["calor"][0][15] == 1 and d["calor"][0][16] == 1 and d["calor"][1][15] == 1
    assert sum(map(sum, d["calor"])) == 3


@pytest.mark.parametrize("correo, total", [("_", 1), ("%", 1), ("n_r", 1), ("x%", 0)])
def test_distribucion_comodines_literales(cliente_admin, datos, correo, total):
    d = get(cliente_admin, "/api/estadisticas/distribucion", portal="Energía", correo=correo).json()
    assert sum(d["cierres"].values()) == total


def test_distribucion_sin_coincidencias_en_cero(cliente_admin, datos):
    d = get(cliente_admin, "/api/estadisticas/distribucion", portal="Energía", correo="nadie").json()
    assert not any(d["cierres"].values())
    assert all(r["sesiones"] == 0 for r in d["duracion"]["rangos"])
    assert d["duracion"]["sinActividad"] == d["duracion"]["sinMedir"] == 0
    assert not any(map(any, d["calor"]))


# ---------------------------------------------------------------------------
# Lo que no cambia: vista general (/portales, /series sin portal) y tablas (/usuarios)
# ---------------------------------------------------------------------------

def test_portales_ignora_correo(cliente_admin, datos):
    sin = get(cliente_admin, "/api/estadisticas/portales").json()
    con = get(cliente_admin, "/api/estadisticas/portales", correo="ana").json()
    assert con == sin and sin["total"]["usuariosUnicos"] == 4
    assert [c for c in datos.llamadas_historial if c[0] == "portales"] == [
        ("portales", datetime(2026, 11, 1), datetime(2026, 11, 5)),
    ] * 2


def test_series_general_sin_cambios(cliente_admin, datos):
    s = get(cliente_admin, "/api/estadisticas/series").json()
    assert [p["portal"] for p in s["portales"]] == ["Energía", "MiraStock"]
    assert s["total"]["sesiones"] == [0, 5, 1, 1]


def test_tabla_usuarios_sigue_con_su_propio_filtro(cliente_admin, datos):
    r = get(cliente_admin, "/api/estadisticas/usuarios", portal="Energía", correo="ana").json()
    assert [f["correo"] for f in r["filas"]] == ["ana.perez@entel.pe"] and r["totalSinFiltro"] == 4


# ---------------------------------------------------------------------------
# SQL de db.py (cursor falso)
# ---------------------------------------------------------------------------

AGREGADOS = (
    "COUNT(*), SUM(CAST(TiempoSesionSeg AS BIGINT)), AVG(CAST(TiempoSesionSeg AS BIGINT)),"
    " COUNT(TiempoSesionSeg), MAX(Fecha), ISNULL(SUM(CASE WHEN SinActividad = 1 THEN 1 ELSE 0 END), 0)"
)


def test_db_resumen_portal_sql_con_correo(cursor_falso):
    desde, hasta = datetime(2026, 11, 1), datetime(2026, 11, 5)
    ultima = datetime(2026, 11, 3, 15)
    cursor_falso["cursor"] = cur = CursorFalso(uno=[(1, 3, 2100, 700, 3, ultima, 0)], todos=[])
    datos = db.estadisticas_resumen_portal("Energía", desde, hasta, " A%_[\\B ")
    assert datos == {
        "usuariosUnicos": 1, "sesiones": 3, "segundosTotales": 2100, "promedioSeg": 700, "sesionesMedidas": 3,
        "ultimaConexion": ultima, "sinActividad": 0,
    }
    ((sql, params),) = cur.ejecutados
    assert sql == (
        f"SELECT COUNT(DISTINCT Correo), {AGREGADOS} FROM core.vHistorialAccesos"
        " WHERE Correo LIKE ? ESCAPE '\\' AND Portal = ? AND Resultado = ? AND Fecha >= ? AND Fecha < ?"
    )
    assert params == ("%a\\%\\_\\[\\\\b%", "Energía", "OK", desde, hasta)


def test_db_resumen_portal_sql_sin_correo(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[(0, 0, None, None, 0, None, 0)], todos=[])
    assert db.estadisticas_resumen_portal("MiraStock", None, None) == {
        "usuariosUnicos": 0, "sesiones": 0, "segundosTotales": None, "promedioSeg": None, "sesionesMedidas": 0,
        "ultimaConexion": None, "sinActividad": 0,
    }
    ((sql, params),) = cur.ejecutados
    assert "LIKE" not in sql and sql.endswith("WHERE Portal = ? AND Resultado = ?")
    assert params == ("MiraStock", "OK")


def test_db_series_con_correo_sql(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[[]])
    assert db.estadisticas_series("Energía", None, None, -180, "Ana_") == {"portales": ["Energía"], "filas": []}
    ((sql, params),) = cur.ejecutados
    assert ("FROM core.vHistorialAccesos WHERE Correo LIKE ? ESCAPE '\\' AND Portal = ? AND Resultado = ?"
            " AND Portal IS NOT NULL AND Fecha IS NOT NULL) s") in sql
    assert params == (-180, "%ana\\_%", "Energía", "OK")


def test_db_distribucion_con_correo_sql(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[[], [], []])
    db.estadisticas_distribucion("Energía", None, None, 60, "50%")
    (sql_c, p_c), (sql_d, p_d), (sql_h, p_h) = cur.ejecutados
    where = "FROM core.vHistorialAccesos WHERE Correo LIKE ? ESCAPE '\\' AND Portal = ? AND Resultado = ?"
    assert where + ") c GROUP BY Cierre" in sql_c and where + ") d GROUP BY Rango" in sql_d
    assert where + " AND Fecha IS NOT NULL) x" in sql_h
    assert p_c == p_d == ("%50\\%%", "Energía", "OK")
    assert p_h == (60, "%50\\%%", "Energía", "OK")


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

def test_js_buscador_de_graficos(cliente_admin):
    js = cliente_admin.get("/static/estadisticas.js").text
    assert "/api/estadisticas/resumen?" in js
    assert "const CLAVE_CORREO = `mira.estadisticas.correo.portal.${SLUG}`;" in js
    assert 'const SIN_COINCIDENCIAS = "Sin sesiones que coincidan con la búsqueda";' in js
    assert '"Filtrado por: "' in js and '"aria-label": "Quitar filtro"' in js
    assert "tablist.before(...graficosPortal(portal));" in js
    assert 'setAttribute("style"' not in js and ".innerHTML" not in js
    graficos = cliente_admin.get("/static/graficos.js").text
    assert 'if (cual === "vacio") textoVacio.textContent = mensaje || TEXTO_VACIO;' in graficos


@pytest.mark.parametrize("ruta", ["/estadisticas", "/estadisticas/general", "/estadisticas/portal/energia"])
def test_paginas_con_cache_busting_actual(cliente_admin, ruta):
    texto = cliente_admin.get(ruta).text
    assert "?v=19" in texto and "?v=16" not in texto
