"""v20: íconos 3D (PNG) en las 4 cards del menú de inicio, en lugar de los SVG."""

import re
import struct
from pathlib import Path

import pytest

IMG = Path(__file__).resolve().parent.parent / "app" / "static" / "img"
CARDS = [
    ("/estadisticas", "estadisticas"),
    ("/contactos", "contactos"),
    ("/administradores", "administradores"),
    ("/consulta-bd", "consulta-bd"),
]


def png(datos: bytes) -> tuple[int, int, int]:
    assert datos[:8] == b"\x89PNG\r\n\x1a\n" and datos[12:16] == b"IHDR"
    ancho, alto, _, tipo_color = struct.unpack(">IIBB", datos[16:26])
    return ancho, alto, tipo_color


def card(inicio: str, href: str) -> str:
    desde = inicio.index(f'href="{href}"')
    return inicio[desde:inicio.index("</a>", desde)]


@pytest.mark.parametrize("href, nombre", CARDS)
def test_cada_card_tiene_su_icono_3d(cliente_admin, href, nombre):
    bloque = card(cliente_admin.get("/").text, href)
    base = f"/static/img/icono-{nombre}"
    assert (
        f'<img class="modulo-icono" src="{base}.png?v=20" srcset="{base}.png?v=20 1x, {base}@2x.png?v=20 2x" '
        f'width="88" height="88" alt="" decoding="async">'
    ) in bloque
    assert "<svg" not in bloque


def test_el_inicio_ya_no_tiene_svg_ni_estilos_inline(cliente_admin):
    inicio = cliente_admin.get("/").text
    assert "<svg" not in inicio
    assert 'style="' not in inicio
    assert len(re.findall(r'<img class="modulo-icono"', inicio)) == 4


@pytest.mark.parametrize("nombre", [n for _, n in CARDS])
@pytest.mark.parametrize("sufijo, lado", [("", 96), ("@2x", 176)])
def test_png_transparentes_y_servidos(cliente, nombre, sufijo, lado):
    resp = cliente.get(f"/static/img/icono-{nombre}{sufijo}.png?v=20")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert png(resp.content) == (lado, lado, 6)  # RGBA: fondo transparente
    assert len(resp.content) < 100_000


def test_css_icono_sin_recuadro_y_con_hover(cliente):
    css = cliente.get("/static/styles.css").text.replace("\r\n", "\n")
    regla = css[css.index(".modulo-icono {"):]
    regla = regla[:regla.index("}")]
    assert "width: 88px; height: 88px;" in regla
    assert "border" not in regla and "background" not in regla and "padding" not in regla
    assert "transform: translateY(-3px) scale(1.06);" in css
    assert "filter: drop-shadow(0 0 10px var(--brillo-suave));" in css
    assert "@media (max-width: 600px) {\n  .modulo-icono { width: 72px; height: 72px;" in css
    # Sin movimiento con prefers-reduced-motion.
    reducido = css[css.index("@media (prefers-reduced-motion: reduce) {\n  .card-modulo"):]
    reducido = reducido[:reducido.index("\n}")]
    assert ".card-modulo:hover .modulo-icono" in reducido and "transform: none;" in reducido
    assert ".card-menu .modulo-icono" not in css


def test_las_2x_miden_176():
    for f in IMG.glob("icono-*@2x.png"):
        assert png(f.read_bytes())[:2] == (176, 176)  # el doble de 88 px
