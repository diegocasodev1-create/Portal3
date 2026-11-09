"""v18: logo de MiraGroup en todas las páginas y cards del menú de inicio en gris metálico."""

import re
import struct
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
PAGINAS = sorted((APP / "static").glob("*.html")) + [APP / "templates" / "error.html"]
LOGO = (
    '<img src="/static/img/logo-miragroup.png?v=19" srcset="/static/img/logo-miragroup.png?v=19 1x, '
    '/static/img/logo-miragroup@2x.png?v=19 2x" width="240" height="73" alt="MiraGroup" class="logo">'
)


@pytest.mark.parametrize("pagina", PAGINAS, ids=lambda p: p.name)
def test_todas_las_paginas_usan_el_logo_nuevo(pagina):
    texto = pagina.read_text(encoding="utf-8")
    assert "logoMG" not in texto
    imagenes = re.findall(r"<img [^>]*>", texto)
    assert imagenes and all(i == LOGO for i in imagenes)
    assert 'style="' not in texto


def test_login_muestra_el_logo_encima_del_titulo(cliente):
    texto = cliente.get("/login").text
    assert texto.index(LOGO) < texto.index("<h1>Portal de administración</h1>")


def test_encabezado_del_inicio_tiene_el_logo(cliente_admin):
    texto = cliente_admin.get("/").text
    marca = texto[texto.index('<div class="marca">'):texto.index("</div>", texto.index('<div class="marca">'))]
    assert LOGO in marca


@pytest.mark.parametrize("nombre, ancho, alto", [("logo-miragroup.png", 240, 73), ("logo-miragroup@2x.png", 480, 146)])
def test_logo_png_transparente_y_liviano(cliente, nombre, ancho, alto):
    resp = cliente.get(f"/static/img/{nombre}")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    datos = resp.content
    assert datos[:8] == b"\x89PNG\r\n\x1a\n" and datos[12:16] == b"IHDR"
    w, h, _, tipo_color = struct.unpack(">IIBB", datos[16:26])
    assert (w, h) == (ancho, alto)
    assert tipo_color == 6  # RGBA: fondo transparente
    assert len(datos) < 100_000


@pytest.mark.parametrize("ruta", ["/static/logoMG.png", "/static/media/logo2.jpg", "/static/../media/logo2.jpg", "/media/logo2.jpg"])
def test_no_se_sirven_el_logo_viejo_ni_los_originales(cliente, ruta):
    assert cliente.get(ruta).status_code == 404


def test_cards_del_menu_de_inicio_en_gris_metalico(cliente_admin):
    inicio = cliente_admin.get("/").text
    assert inicio.count('class="card card-modulo card-menu"') == 4  # v19: + «Consulta de base de datos»
    # Solo el menú de inicio: las cards de Estadísticas y Administradores no cambian.
    for archivo in ("estadisticas-inicio.js", "administradores.js", "estadisticas.html", "administradores.html"):
        assert "card-menu" not in (APP / "static" / archivo).read_text(encoding="utf-8")
    css = cliente_admin.get("/static/styles.css").text
    assert ".card-menu {" in css and "#4b5361" in css
    assert ".logo.logo-placa {" in css and "drop-shadow" in css


# ---------------------------------------------------------------------------
# v18 (ajuste): encabezado blanco y fijo; login plateado
# ---------------------------------------------------------------------------

def test_encabezado_blanco_fijo_y_logo_sin_halo(cliente):
    css = cliente.get("/static/styles.css").text
    bloque = css[css.index(".encabezado {"):css.index("}", css.index(".encabezado {"))]
    assert "position: sticky; top: 0; z-index: 40;" in bloque and "background: #ffffff;" in bloque
    # Por encima del contenido, por debajo de modales (50), bloqueo (80) y avisos (90).
    assert "z-index: 50;" in css and "z-index: 80;" in css and "z-index: 90;" in css
    assert ".encabezado .logo { filter: none; }" in css
    assert ".encabezado h1 { color: var(--claro-titulo); }" in css


def test_login_plateado_y_logo_sin_halo(cliente):
    texto = cliente.get("/login").text
    assert '<main class="card card-aviso card-ingreso card-plata">' in texto
    css = cliente.get("/static/styles.css").text
    assert ".card-plata {" in css and ".card-plata .logo { filter: none; }" in css
    # Solo el login usa el plateado.
    for pagina in PAGINAS:
        if pagina.name != "login.html":
            assert "card-plata" not in pagina.read_text(encoding="utf-8")
