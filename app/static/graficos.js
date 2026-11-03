/* Gráficos de /estadisticas (v16): tema oscuro de Chart.js, colores por portal, paneles con estados
   (carga, vacío, error), tarjetas y mapa de calor en grilla CSS. JavaScript sin otras librerías.

   CSP: Chart.js 4 se sirve desde /static/vendor y no usa eval ni <style> en línea; los tamaños los fija
   por CSSOM (element.style), que la CSP permite. El mapa de calor usa lo mismo para la intensidad. */
"use strict";

(() => {
  const { el, numero, dos, duracion } = window.Mira;
  const Chart = window.Chart;

  // -------------------------------------------------------------------------
  // Colores: fijos para los portales conocidos (único lugar con nombres de portal) y una paleta de 6
  // para los futuros, elegida por un hash del nombre (no cambia si aparece otro portal).
  // -------------------------------------------------------------------------

  const COLORES_PORTAL = { "energía": "#d9a441", "mirastock": "#29b8ec" };
  const PALETA = ["#3ddc97", "#b388ff", "#ff8a65", "#4dd0e1", "#f06292", "#c5e1a5"];

  function hashTexto(texto) {
    let h = 0;
    for (const c of texto) h = (h * 31 + c.codePointAt(0)) >>> 0;
    return h;
  }

  function colorPortal(nombre) {
    const clave = String(nombre || "").trim().toLocaleLowerCase("es");
    return COLORES_PORTAL[clave] || PALETA[hashTexto(clave) % PALETA.length];
  }

  // "#29b8ec" + 0.4 → "rgba(41, 184, 236, 0.4)"
  function conAlfa(hex, alfa) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
  }

  // Colores fijos de los tipos de cierre (los mismos textos que la columna «Cierre»).
  const COLORES_CIERRE = {
    "Botón": "#3ddc97", "Inactividad": "#29b8ec", "Sin actividad": "#ffc457",
    "En curso": "#8fdcff", "No medida": "#6c7f99", "Otro": "#b388ff",
  };

  // -------------------------------------------------------------------------
  // Tema: los colores salen de las variables CSS de Portal3.
  // -------------------------------------------------------------------------

  function variable(nombre, porDefecto) {
    const valor = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
    return valor || porDefecto;
  }

  let temaListo = false;
  function aplicarTema() {
    if (temaListo || !Chart) return;
    temaListo = true;
    const texto = variable("--texto", "#ffffff");
    const texto2 = variable("--texto-2", "#a9bcd4");
    const grilla = variable("--borde-suave", "rgba(169, 188, 212, 0.18)");
    Chart.defaults.color = texto2;
    Chart.defaults.borderColor = grilla;
    Chart.defaults.font.family = variable("--fuente", '"Exo 2", system-ui, sans-serif');
    Chart.defaults.font.size = 12;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.labels.color = texto2;
    const tooltip = Chart.defaults.plugins.tooltip;
    tooltip.backgroundColor = variable("--fondo-2", "#0a1a33");
    tooltip.borderColor = variable("--borde", "rgba(41, 184, 236, 0.35)");
    tooltip.borderWidth = 1;
    tooltip.titleColor = texto;
    tooltip.bodyColor = texto;
    tooltip.padding = 10;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      Chart.defaults.animation = false;
    }
  }

  // -------------------------------------------------------------------------
  // Formatos
  // -------------------------------------------------------------------------

  const DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
  const DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

  // "2026-11-02" → "02/11" (el día ya viene en hora local desde la API).
  const diaCorto = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  const hora = (h) => `${dos(h)}:00`;
  const horas = (segundos) => Math.round(((segundos || 0) / 3600) * 100) / 100;
  const textoHoras = (valor) => `${numero.format(valor)} h`;

  // -------------------------------------------------------------------------
  // Panel: título visible, caja del gráfico y estados (carga, vacío, error con «Reintentar»).
  // -------------------------------------------------------------------------

  function crearPanel({ titulo, ancho, alto, reintentar, conLienzo = true }) {
    const carga = el("div", { class: "estado estado-grafico" }, [
      el("span", { class: "spinner", "aria-hidden": "true" }),
      el("span", { text: "Cargando…" }),
    ]);
    const vacio = el("div", { class: "estado estado-grafico", hidden: true }, el("p", { text: "Sin datos en el rango" }));
    const textoError = el("p", { text: "No se pudieron cargar los datos." });
    const botonReintentar = el("button", { type: "button", class: "btn btn-secundario btn-chico", text: "Reintentar" });
    botonReintentar.addEventListener("click", () => reintentar && reintentar());
    const error = el("div", { class: "estado estado-grafico estado-error", role: "alert", hidden: true },
      [textoError, botonReintentar]);
    const lienzo = conLienzo ? el("canvas", { role: "img", "aria-label": titulo }) : null;
    const caja = el("div", { class: `grafico-caja${alto ? ` grafico-caja-${alto}` : ""}`, hidden: true }, lienzo);
    const pie = el("p", { class: "grafico-pie", hidden: true });
    const extra = el("div", { class: "grafico-extra" });
    const nodo = el("section", { class: `card grafico-panel${ancho === "completo" ? " grafico-completo" : ""}` }, [
      el("h3", { class: "grafico-titulo", text: titulo }), extra, carga, vacio, error, caja, pie,
    ]);
    const panel = { nodo, lienzo, caja, extra, chart: null };

    function destruir() {
      if (panel.chart) {
        panel.chart.destroy();
        panel.chart = null;
      }
    }

    panel.mostrar = (cual, mensaje) => {
      carga.hidden = cual !== "carga";
      vacio.hidden = cual !== "vacio";
      error.hidden = cual !== "error";
      caja.hidden = cual !== "grafico";
      if (cual !== "grafico") {
        destruir();
        pie.hidden = true;
      }
      if (cual === "error" && mensaje) textoError.textContent = mensaje;
    };

    // Destruye el gráfico anterior antes de crear el nuevo (no se acumulan instancias).
    panel.dibujar = (config, resumen) => {
      aplicarTema();
      destruir();
      panel.mostrar("grafico");
      if (lienzo) {
        lienzo.setAttribute("aria-label", `${titulo}. ${resumen}`);
        panel.chart = new Chart(lienzo, config);
      } else {
        caja.setAttribute("aria-label", `${titulo}. ${resumen}`);
      }
    };

    panel.pie = (texto) => {
      pie.textContent = texto || "";
      pie.hidden = !texto;
    };

    return panel;
  }

  // -------------------------------------------------------------------------
  // Tarjetas (usuarios, sesiones, horas, promedio)
  // -------------------------------------------------------------------------

  function tarjetas(contenedor, datos) {
    const items = [
      ["Usuarios únicos", numero.format(datos.usuariosUnicos || 0)],
      ["Sesiones", numero.format(datos.sesiones || 0)],
      ["Horas totales", duracion(datos.segundosTotales)],
      ["Promedio por sesión", duracion(datos.promedioSeg)],
    ];
    contenedor.replaceChildren(...items.map(([nombre, valor]) => el("div", { class: "card indicador" }, [
      el("span", { class: "indicador-nombre", text: nombre }),
      el("span", { class: "indicador-valor", text: valor }),
    ])));
  }

  // -------------------------------------------------------------------------
  // Mapa de calor día de la semana × hora (grilla CSS; intensidad por element.style)
  // -------------------------------------------------------------------------

  function mapaCalor(panel, matriz, color) {
    let maximo = 0;
    let mejor = null;
    let total = 0;
    matriz.forEach((fila, d) => fila.forEach((n, h) => {
      total += n;
      if (n > maximo) {
        maximo = n;
        mejor = [d, h];
      }
    }));
    if (!total) {
      panel.mostrar("vacio");
      return;
    }
    const celdas = [el("span", { class: "calor-esquina", "aria-hidden": "true" })];
    for (let h = 0; h < 24; h++) {
      celdas.push(el("span", { class: "calor-hora", "aria-hidden": "true", text: h % 3 === 0 ? dos(h) : "" }));
    }
    matriz.forEach((fila, d) => {
      celdas.push(el("span", { class: "calor-dia", "aria-hidden": "true", text: DIAS_CORTOS[d] }));
      fila.forEach((n, h) => {
        const texto = `${DIAS_SEMANA[d]} ${hora(h)} – ${numero.format(n)} ${n === 1 ? "sesión" : "sesiones"}`;
        const celda = el("span", { class: "calor-celda", title: texto, "aria-hidden": "true" });
        if (n > 0) celda.style.backgroundColor = conAlfa(color, 0.15 + 0.85 * (n / maximo));
        celdas.push(celda);
      });
    });
    panel.caja.replaceChildren(el("div", { class: "calor" }, celdas));
    panel.caja.setAttribute("role", "img");
    panel.dibujar(null, `${numero.format(total)} sesiones; la franja con más sesiones es ${DIAS_SEMANA[mejor[0]].toLowerCase()} a las ${hora(mejor[1])} (${numero.format(maximo)}).`);
    panel.pie("Hora local. Pasa el cursor sobre una celda para ver la cantidad.");
  }

  // Resumen para aria-label: «total 85; máximo 30 el 02/11».
  function resumenSerie(dias, valores, formato) {
    let max = -1;
    let iMax = 0;
    let total = 0;
    valores.forEach((v, i) => {
      total += v;
      if (v > max) {
        max = v;
        iMax = i;
      }
    });
    if (!dias.length) return "Sin datos.";
    return `Del ${diaCorto(dias[0])} al ${diaCorto(dias[dias.length - 1])}: total ${formato(total)}; máximo ${formato(max)} el ${diaCorto(dias[iMax])}.`;
  }

  window.MiraGraficos = {
    colorPortal, conAlfa, COLORES_CIERRE, crearPanel, tarjetas, mapaCalor, resumenSerie,
    diaCorto, hora, horas, textoHoras, DIAS_SEMANA,
  };
})();
