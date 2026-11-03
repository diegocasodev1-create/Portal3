"""v14: sesiones «Sin actividad» y «No medida» (columnas Medible y SinActividad de core.vHistorialAccesos)."""

from datetime import datetime, timedelta

import pytest

from app import db, main
from tests.test_historial import CursorFalso, cursor_falso  # noqa: F401 (fixture)

FECHA = datetime(2026, 11, 2, 15, 0, 0)  # UTC sin zona, como la vista


def fila(**cambios):
    """Una fila de listar_historial: por defecto, OK medible sin datos de sesión."""
    base = {
        "Fecha": FECHA, "Usuario": "", "Correo": "a@ejemplo.com", "Portal": "Energía", "Resultado": "OK",
        "FinalSesion": None, "TiempoSesionSeg": None, "EnCurso": False, "CierreExplicito": False,
        "Medible": True, "SinActividad": False,
    }
    return {**base, **cambios}


def csv_historial(cliente, **params):
    resp = cliente.get("/api/historial/csv", params=params)
    assert resp.status_code == 200
    return [linea.split(";") for linea in resp.content.decode("utf-8-sig").split("\r\n")[1:-1]]


# ---------------------------------------------------------------------------
# Textos: Cierre, Tiempo y Final (CSV)
# ---------------------------------------------------------------------------

FINAL = FECHA + timedelta(minutes=12)

# (descripción, cambios de la fila, Cierre, Final en CSV (UTC), Tiempo en CSV)
ESTADOS = [
    ("botón", dict(FinalSesion=FINAL, TiempoSesionSeg=720, CierreExplicito=True), "Botón", "2026-11-02 15:12:00", "12"),
    ("en curso", dict(EnCurso=True), "En curso", "", ""),
    ("inactividad", dict(FinalSesion=FINAL, TiempoSesionSeg=720), "Inactividad", "2026-11-02 15:12:00", "12"),
    ("sin actividad", dict(SinActividad=True, TiempoSesionSeg=0), "Sin actividad", "2026-11-02 15:00:00", "0"),
    ("no medida", dict(Medible=False), "No medida", "", ""),
    ("medible sin datos", {}, "", "", ""),
    ("denegado", dict(Resultado="Denegado", Medible=False), "", "", ""),
    ("denegado medible", dict(Resultado="Denegado", SinActividad=True, TiempoSesionSeg=0), "", "", ""),
]


@pytest.mark.parametrize("cambios, cierre, final, tiempo", [e[1:] for e in ESTADOS], ids=[e[0] for e in ESTADOS])
def test_estados_en_funciones(cambios, cierre, final, tiempo):
    f = fila(**cambios)
    assert main._texto_cierre(f) == cierre
    assert main._fecha_csv(main._final_sesion(f)) == final
    assert main._tiempo_csv(f) == tiempo


@pytest.mark.parametrize("cambios, cierre, final, tiempo", [e[1:] for e in ESTADOS], ids=[e[0] for e in ESTADOS])
def test_estados_en_csv_historial(cliente_admin, bd, monkeypatch, cambios, cierre, final, tiempo):
    monkeypatch.setattr(db, "listar_historial", lambda *args: ([fila(**cambios)], 1))
    ((_, _, _, _, _, final_csv, tiempo_csv, cierre_csv),) = csv_historial(cliente_admin)
    assert (cierre_csv, final_csv, tiempo_csv) == (cierre, final, tiempo)


@pytest.mark.parametrize("cambios, esperado", [
    # La prioridad manda aunque haya varias marcas a la vez.
    (dict(CierreExplicito=True, EnCurso=True, SinActividad=True, Medible=False), "Botón"),
    (dict(EnCurso=True, FinalSesion=FINAL, SinActividad=True, Medible=False), "En curso"),
    (dict(FinalSesion=FINAL, SinActividad=True, Medible=False), "Inactividad"),
    (dict(SinActividad=True, Medible=False), "Sin actividad"),
])
def test_prioridad_del_cierre(cambios, esperado):
    assert main._texto_cierre(fila(**cambios)) == esperado


def test_csv_sin_actividad_usa_la_hora_de_ingreso_en_hora_local(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", sin_actividad=True)
    ((fecha, *_, final, tiempo, cierre),) = csv_historial(cliente_admin, tz_offset_min="-180")
    assert fecha == final == "2026-11-02 12:00:00"
    assert (tiempo, cierre) == ("0", "Sin actividad")


def test_listado_devuelve_medible_y_sin_actividad(cliente_admin, bd):
    bd.agregar_acceso(FECHA, "a@ejemplo.com", sin_actividad=True)
    bd.agregar_acceso(FECHA - timedelta(hours=1), "b@ejemplo.com", medible=False)
    filas = cliente_admin.get("/api/historial").json()["filas"]
    assert [(f["Correo"], f["Medible"], f["SinActividad"], f["TiempoSesionSeg"]) for f in filas] == [
        ("a@ejemplo.com", True, True, 0), ("b@ejemplo.com", False, False, None),
    ]


def test_db_listar_historial_medible_nulo_cuenta_como_0(cursor_falso):
    cursor_falso["cursor"] = CursorFalso(
        uno=[(1,)], todos=[[(FECHA, "", "a@ejemplo.com", "MiraStock", "OK", None, None, 0, 0, None, None)]]
    )
    ((f,), _) = db.listar_historial(db.FiltrosHistorial(), 1, 50)
    assert f["Medible"] is False and f["SinActividad"] is False
    assert main._texto_cierre(f) == "No medida"


# ---------------------------------------------------------------------------
# Estadísticas: conteo «sinActividad»
# ---------------------------------------------------------------------------

def cargar_sesiones(bd):
    bd.agregar_acceso(FECHA, "ana@ejemplo.com", "Energía", final_sesion=FECHA + timedelta(minutes=30))
    bd.agregar_acceso(FECHA, "ana@ejemplo.com", "Energía", sin_actividad=True)
    bd.agregar_acceso(FECHA, "beto@ejemplo.com", "Energía", sin_actividad=True)
    bd.agregar_acceso(FECHA, "beto@ejemplo.com", "Energía", sin_actividad=True)
    bd.agregar_acceso(FECHA, "carla@ejemplo.com", "Energía", medible=False)
    bd.agregar_acceso(FECHA, "ana@ejemplo.com", "MiraStock", sin_actividad=True)
    bd.agregar_acceso(FECHA, "dani@ejemplo.com", "Bodega Norte", final_sesion=FECHA + timedelta(minutes=5))
    # Un denegado no es sesión: no cuenta aunque viniera marcado.
    bd.agregar_acceso(FECHA, "eva@ejemplo.com", "Energía", "Denegado", sin_actividad=True)


def test_portales_cuentan_sin_actividad(cliente_admin, bd):
    cargar_sesiones(bd)
    datos = cliente_admin.get("/api/estadisticas/portales").json()
    por_portal = {p["portal"]: p for p in datos["portales"]}
    assert {p: d["sinActividad"] for p, d in por_portal.items()} == {"Bodega Norte": 0, "Energía": 3, "MiraStock": 1}
    assert datos["total"]["sinActividad"] == 4
    # Las sin actividad son medidas con 0 s: suman al conteo de medidas y bajan el promedio.
    energia = por_portal["Energía"]
    assert (energia["sesiones"], energia["sesionesMedidas"], energia["segundosTotales"], energia["promedioSeg"]) == (
        5, 4, 1800, 450,
    )


@pytest.mark.parametrize("portal, esperado", [
    ("Energía", {"ana@ejemplo.com": 1, "beto@ejemplo.com": 2, "carla@ejemplo.com": 0}),
    ("MiraStock", {"ana@ejemplo.com": 1}),
    ("Bodega Norte", {"dani@ejemplo.com": 0}),
])
def test_usuarios_cuentan_sin_actividad(cliente_admin, bd, portal, esperado):
    cargar_sesiones(bd)
    filas = cliente_admin.get("/api/estadisticas/usuarios", params={"portal": portal}).json()["filas"]
    assert {f["correo"]: f["sinActividad"] for f in filas} == esperado


def test_csv_portales_columna_sin_actividad(cliente_admin, bd):
    cargar_sesiones(bd)
    lineas = cliente_admin.get("/api/estadisticas/portales/csv").content.decode("utf-8-sig").split("\r\n")
    encabezado = lineas[0].split(";")
    assert encabezado[2:5] == ["Sesiones", "Sesiones medidas", "Sin actividad"]
    celdas = {linea.split(";")[0]: linea.split(";")[4] for linea in lineas[1:-1]}
    assert celdas == {"Bodega Norte": "0", "Energía": "3", "MiraStock": "1", "Total Portal Corporativo": "4"}


def test_csv_usuarios_columna_sin_actividad(cliente_admin, bd):
    cargar_sesiones(bd)
    resp = cliente_admin.get("/api/estadisticas/usuarios/csv", params={"portal": "Energía"})
    lineas = resp.content.decode("utf-8-sig").split("\r\n")
    assert lineas[0].split(";")[2:5] == ["Sesiones", "Sesiones medidas", "Sin actividad"]
    celdas = {linea.split(";")[1]: linea.split(";")[4] for linea in lineas[1:-1]}
    assert celdas == {"ana@ejemplo.com": "1", "beto@ejemplo.com": "2", "carla@ejemplo.com": "0"}


def test_db_agregados_cuentan_sin_actividad(cursor_falso):
    cursor_falso["cursor"] = cur = CursorFalso(uno=[], todos=[[("a@ejemplo.com", "", 3, 0, 0, 3, FECHA, 3)]])
    ((f,), _) = db.estadisticas_usuarios("Energía", None, None, 10)
    assert f["sinActividad"] == 3
    ((sql, _),) = cur.ejecutados
    assert "MAX(Fecha), ISNULL(SUM(CASE WHEN SinActividad = 1 THEN 1 ELSE 0 END), 0) FROM" in sql


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

def test_comun_js_tiene_los_textos(cliente_admin):
    texto = cliente_admin.get("/static/comun.js").text
    for t in ('"Botón"', '"En curso"', '"Inactividad"', '"Sin actividad"', '"No medida"', '"0 min"'):
        assert t in texto
    assert "function textoTiempo(a)" in texto and "function textoFinal(a)" in texto


@pytest.mark.parametrize("archivo", ["historial.js", "estadisticas.js"])
def test_tablas_usan_los_textos_compartidos(cliente_admin, archivo):
    texto = cliente_admin.get(f"/static/{archivo}").text
    assert "text: textoFinal(a)" in texto and "text: textoTiempo(a)" in texto and "text: textoCierre(a)" in texto
    assert "fechaLocal(a.FinalSesion)" not in texto and "duracion(a.TiempoSesionSeg)" not in texto


def test_estadisticas_js_muestra_sin_actividad(cliente_admin):
    texto = cliente_admin.get("/static/estadisticas.js").text
    assert "sin actividad: ${numero.format(d.sinActividad)}" in texto
    assert '{ titulo: "Sin actividad", clase: "td-num" }' in texto
