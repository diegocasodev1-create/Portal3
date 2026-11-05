/* Inicio de estadísticas (/estadisticas): una card «General por portal» y una por cada portal que devuelve
   la API (sin código por portal), con el resumen de los últimos 30 días y el color del portal.
   Cada card enlaza a su vista: /estadisticas/general o /estadisticas/portal/<slug> (el slug lo da la API). */
"use strict";

(() => {
  const { $, el, api, numero, textoDia, agregarRango, duracion } = window.Mira;
  const { colorPortal } = window.MiraGraficos;

  const DIAS_RESUMEN = 30;

  // Últimos 30 días locales (hoy incluido), igual que el valor por defecto de cada vista.
  function rangoResumen() {
    const hoy = new Date();
    const desde = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - (DIAS_RESUMEN - 1));
    return agregarRango(new URLSearchParams(), textoDia(desde), textoDia(hoy));
  }

  // «85 sesiones · 61 h 46 min» (sin horas si no hubo tiempo medido).
  function textoResumen(d) {
    if (!d.sesiones) return "Sin sesiones en los últimos 30 días";
    const sesiones = `${numero.format(d.sesiones)} ${d.sesiones === 1 ? "sesión" : "sesiones"}`;
    return d.segundosTotales === null ? sesiones : `${sesiones} · ${duracion(d.segundosTotales)}`;
  }

  const textoUsuarios = (n) => `${numero.format(n)} ${n === 1 ? "usuario" : "usuarios"}`;

  function card({ href, titulo, detalle, d, color }) {
    const nodo = el("a", { class: "card card-modulo card-estadistica", href }, [
      el("span", { class: "modulo-titulo", text: titulo }),
      el("span", { class: "modulo-texto", text: detalle }),
      el("span", { class: "estadistica-resumen", text: textoResumen(d) }),
      el("span", { class: "estadistica-usuarios", text: textoUsuarios(d.usuariosUnicos || 0) }),
      el("span", { class: "modulo-ir", "aria-hidden": "true" }, ["Entrar ", el("span", { class: "modulo-flecha", text: "→" })]),
    ]);
    // Color de la franja superior (CSSOM: la CSP lo permite).
    if (color) nodo.style.setProperty("--color-portal", color);
    return nodo;
  }

  async function cargar() {
    const contenedor = $("cards-estadisticas");
    contenedor.setAttribute("aria-busy", "true");
    contenedor.replaceChildren(el("div", { class: "estado estado-cards" }, [
      el("span", { class: "spinner", "aria-hidden": "true" }),
      el("span", { text: "Cargando…" }),
    ]));
    let r;
    try {
      r = await api("GET", `/api/estadisticas/portales?${rangoResumen()}`);
    } catch (e) {
      contenedor.setAttribute("aria-busy", "false");
      if (e.status === 401 || e.status === 403) return;  // la pantalla de bloqueo ya avisa
      const reintentar = el("button", { type: "button", class: "btn btn-secundario", text: "Reintentar" });
      reintentar.addEventListener("click", cargar);
      contenedor.replaceChildren(el("div", { class: "estado estado-error estado-cards", role: "alert" }, [
        el("p", { text: e.message || "No se pudieron cargar las estadísticas." }), reintentar,
      ]));
      return;
    }
    contenedor.replaceChildren(
      card({
        href: "/estadisticas/general", titulo: "General por portal",
        detalle: "Todos los portales juntos: reparto, uso por día y horas.", d: r.total,
      }),
      ...r.portales.map((p) => card({
        href: `/estadisticas/portal/${encodeURIComponent(p.slug)}`, titulo: `Portal ${p.portal}`,
        detalle: "Uso por día, usuarios, cierres, duración y horarios.", d: p, color: colorPortal(p.portal),
      })),
    );
    contenedor.setAttribute("aria-busy", "false");
  }

  cargar();
})();
