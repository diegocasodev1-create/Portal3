"""v16: /estadisticas como inicio con cards y una vista por sección (/estadisticas/general y
/estadisticas/portal/<slug>), cada una con su filtro de fechas; slug de cada portal en /api/estadisticas/portales."""

from datetime import datetime

import pytest

from app import main
from tests.test_historial import revocar_admin

FECHA = datetime(2026, 11, 2, 15, 0, 0)

RUTAS = ["/estadisticas", "/estadisticas/general", "/estadisticas/portal/energia",
         "/estadisticas/portal/bodega-norte"]


def sesion(bd, correo, portal, segundos=60):
    from datetime import timedelta
    bd.agregar_acceso(FECHA, correo, portal, final_sesion=FECHA + timedelta(seconds=segundos))


# ---------------------------------------------------------------------------
# Rutas: login, cambio de contraseña y BD caída
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_sesion_va_al_login_recordando_la_ruta(cliente, ruta):
    resp = cliente.get(ruta, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/login?siguiente={ruta}"


@pytest.mark.parametrize("ruta", RUTAS)
def test_admin_desactivado_va_al_login(cliente_admin, bd, ruta):
    revocar_admin(bd)
    resp = cliente_admin.get(ruta, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"].startswith("/login")


@pytest.mark.parametrize("ruta", RUTAS)
def test_debe_cambiar_contrasena_va_a_cambiarla(cliente_admin, bd, ruta):
    bd.admins[1]["DebeCambiarContrasena"] = True
    resp = cliente_admin.get(ruta, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/cambiar-contrasena"


def test_slug_invalido_sin_sesion_igual_va_al_login(cliente):
    resp = cliente.get("/estadisticas/portal/Energ%C3%ADa", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"].startswith("/login")


def test_siguiente_vuelve_a_la_vista_despues_del_login():
    assert main._siguiente_seguro("/estadisticas/portal/energia") == "/estadisticas/portal/energia"


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

def test_inicio_tiene_cards_e_historial(cliente_admin):
    texto = cliente_admin.get("/estadisticas").text
    assert "<h1>Estadísticas del Portal Corporativo MiraGroup</h1>" in texto
    assert 'class="modulos modulos-estadisticas" id="cards-estadisticas"' in texto
    assert 'href="/historial">Historial completo</a>' in texto
    assert '<script src="/static/estadisticas-inicio.js?v=19" defer></script>' in texto
    # El inicio no dibuja gráficos: no carga Chart.js.
    assert "chart.umd" not in texto and 'id="form-rango"' not in texto


@pytest.mark.parametrize("ruta, vista", [
    ("/estadisticas/general", "general"), ("/estadisticas/portal/energia", "portal"),
])
def test_vistas_con_filtro_propio_y_volver_a_estadisticas(cliente_admin, ruta, vista):
    resp = cliente_admin.get(ruta)
    assert resp.status_code == 200
    texto = resp.text
    assert f'<body data-vista="{vista}">' in texto
    assert 'href="/estadisticas">← Estadísticas</a>' in texto
    assert 'id="form-rango"' in texto and 'id="e-desde"' in texto and 'id="btn-aplicar"' in texto
    assert 'href="/historial">Historial completo</a>' in texto
    assert "<details" not in texto


def test_vista_general(cliente_admin):
    texto = cliente_admin.get("/estadisticas/general").text
    assert "<h1>General por portal</h1>" in texto and 'id="general-cuerpo"' in texto


def test_vista_portal_tiene_no_encontrado_y_pestanas(cliente_admin):
    texto = cliente_admin.get("/estadisticas/portal/mirastock").text
    assert '<h1 id="titulo-portal">Portal</h1>' in texto
    assert 'id="portal-no-encontrado"' in texto and "Portal no encontrado" in texto
    assert 'href="/estadisticas">← Volver a Estadísticas</a>' in texto
    assert 'id="portal-cuerpo"' in texto and 'role="tablist"' in texto


@pytest.mark.parametrize("slug", ["bodega-norte", "portal-2", "a", "x" * 64])
def test_slug_valido_desconocido_responde_200(cliente_admin, slug):
    # La página resuelve el slug con la API y, si no existe, muestra «Portal no encontrado».
    resp = cliente_admin.get(f"/estadisticas/portal/{slug}")
    assert resp.status_code == 200 and 'id="portal-no-encontrado"' in resp.text


@pytest.mark.parametrize("slug", ["Energia", "energ%C3%ADa", "bodega_norte", "-energia", "energia-", "a--b",
                                  "x" * 65, "%20"])
def test_slug_con_formato_invalido_404(cliente_admin, slug):
    resp = cliente_admin.get(f"/estadisticas/portal/{slug}")
    assert resp.status_code == 404
    assert 'id="portal-no-encontrado"' in resp.text and 'href="/estadisticas">← Volver a Estadísticas</a>' in resp.text


def test_ruta_de_portal_sin_slug_404(cliente_admin):
    assert cliente_admin.get("/estadisticas/portal/").status_code == 404


# ---------------------------------------------------------------------------
# Slug en /api/estadisticas/portales
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre, slug", [
    ("Energía", "energia"), ("MiraStock", "mirastock"), ("Bodega Norte", "bodega-norte"),
    ("Bodega Norte/Sur", "bodega-norte-sur"), ("  Ñandú  ", "nandu"), ("Ventas 2026", "ventas-2026"),
    ("***", "portal"), ("Über__Portal!", "uber-portal"), ("Ü-ber", "u-ber"), ("x" * 80, "x" * 60),
])
def test_slug_portal(nombre, slug):
    assert main._slug_portal(nombre) == slug
    assert main._SLUG_VALIDO.fullmatch(slug) and len(slug) <= main.MAX_LARGO_SLUG


def test_slugs_repetidos_el_segundo_en_orden_alfabetico_lleva_sufijo():
    slugs = main._slugs_portales(["Bodega-Norte", "MiraStock", "Bodega Norte", "bodega norte"])
    assert slugs == {
        "Bodega Norte": "bodega-norte", "bodega norte": "bodega-norte-2", "Bodega-Norte": "bodega-norte-3",
        "MiraStock": "mirastock",
    }
    assert len(set(slugs.values())) == len(slugs)


def test_slugs_repetidos_no_chocan_con_un_portal_que_ya_termina_en_numero():
    slugs = main._slugs_portales(["Portal", "portal", "Portal 2"])
    assert len(set(slugs.values())) == 3 and slugs["Portal"] == "portal"


def test_portales_traen_slug_incluido_un_portal_nuevo(cliente_admin, bd):
    sesion(bd, "a@ejemplo.com", "Energía")
    sesion(bd, "b@ejemplo.com", "Bodega Norte")
    sesion(bd, "c@ejemplo.com", "MiraStock")
    datos = cliente_admin.get("/api/estadisticas/portales").json()
    assert [(p["portal"], p["slug"]) for p in datos["portales"]] == [
        ("Bodega Norte", "bodega-norte"), ("Energía", "energia"), ("MiraStock", "mirastock"),
    ]
    assert "slug" not in datos["total"]
    # La ruta de ese slug abre la vista del portal (resuelta con este mismo slug).
    assert cliente_admin.get("/estadisticas/portal/bodega-norte").status_code == 200


def test_slug_no_cambia_el_csv_de_portales(cliente_admin, bd):
    sesion(bd, "a@ejemplo.com", "Energía")
    encabezado = cliente_admin.get("/api/estadisticas/portales/csv").content.decode("utf-8-sig").split("\r\n")[0]
    assert "slug" not in encabezado.lower()


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("archivo", ["estadisticas.js", "estadisticas-inicio.js"])
def test_js_sin_portales_fijos(cliente_admin, archivo):
    texto = cliente_admin.get(f"/static/{archivo}").text
    assert "Energía" not in texto and "MiraStock" not in texto
    assert "energia" not in texto and "mirastock" not in texto


def test_inicio_js_arma_cards_desde_la_api(cliente_admin):
    js = cliente_admin.get("/static/estadisticas-inicio.js").text
    assert "/api/estadisticas/portales?" in js
    assert "`/estadisticas/portal/${encodeURIComponent(p.slug)}`" in js and '"/estadisticas/general"' in js
    assert 'style.setProperty("--color-portal"' in js


def test_vistas_js_recuerdan_las_fechas_por_vista(cliente_admin):
    js = cliente_admin.get("/static/estadisticas.js").text
    assert '"mira.estadisticas.rango.general"' in js
    assert "`mira.estadisticas.rango.portal.${SLUG}`" in js
    assert "sessionStorage.getItem(CLAVE_RANGO)" in js and "sessionStorage.setItem(CLAVE_RANGO" in js
    assert "x.slug === SLUG" in js and "<details" not in js and "asegurarBloque" not in js
