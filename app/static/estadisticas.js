/* Estadísticas del Portal Corporativo – vistas «General por portal» y «Portal <nombre>» (JavaScript sin
   librerías, más Chart.js vía graficos.js).

   Cada vista es su propia página (/estadisticas/general y /estadisticas/portal/<slug>), con su filtro de
   fechas guardado en sessionStorage (una clave por vista). <body data-vista="general|portal"> elige el modo.
   La vista de portal tiene sub-vistas en pestañas (SUBVISTAS): los niveles 3 y 4 (funcionalidades y
   subfuncionalidades) se sumarán como otra entrada de SUBVISTAS, sin tocar el resto. */
"use strict";

(() => {
  const {
    $, el, api, setOcupado, toast,
    numero, textoDia, agregarRango, tzOffsetMin, fechaLocal, duracion, textoCierre, textoTiempo, textoFinal, descargarCsv,
  } = window.Mira;
  const G = window.MiraGraficos;

  const DIAS_POR_DEFECTO = 30;
  const TOTAL_PORTAL_CORPORATIVO = "Total Portal Corporativo";

  // Modo de la página y slug del portal (último tramo de /estadisticas/portal/<slug>).
  const VISTA = document.body.dataset.vista;
  function slugDeLaUrl() {
    try {
      return decodeURIComponent(location.pathname.replace(/\/+$/, "").split("/").pop() || "");
    } catch (e) {
      return "";  // %-codificación inválida: ningún portal coincide («Portal no encontrado»)
    }
  }
  const SLUG = VISTA === "portal" ? slugDeLaUrl() : "";
  const CLAVE_RANGO = VISTA === "portal" ? `mira.estadisticas.rango.portal.${SLUG}` : "mira.estadisticas.rango.general";

  const estado = {
    rango: null,  // URLSearchParams con desde/hasta aplicados
    version: 0,   // sube con cada cambio de fechas; cada vista recuerda con qué versión cargó
  };

  // Vistas que dependen del rango: { visible(), cargar(), version }. Solo se cargan las visibles;
  // una pestaña oculta se carga al elegirla, así no se consulta lo que nadie mira.
  const vistas = [];

  let contadorIds = 0;
  const nuevoId = (base) => `${base}-${++contadorIds}`;

  function registrarVista(vista) {
    vista.version = 0;
    vistas.push(vista);
    return vista;
  }

  function refrescarVisibles() {
    if (!estado.rango) return;
    for (const v of vistas) {
      if (v.version !== estado.version && v.visible()) {
        v.version = estado.version;
        v.cargar();
      }
    }
  }

  // Parámetros del rango aplicado + `extra` (se omiten los vacíos).
  function parametros(extra) {
    const p = new URLSearchParams(estado.rango);
    for (const [clave, valor] of Object.entries(extra || {})) {
      if (valor) p.set(clave, valor);
    }
    return p;
  }

  // /api/estadisticas/portales del rango aplicado: una sola consulta por versión, compartida por la tabla
  // general y los gráficos. Si falla, se olvida para que «Reintentar» vuelva a consultar.
  let promesaPortales = null;
  let versionPortales = -1;
  function datosPortales() {
    if (!promesaPortales || versionPortales !== estado.version) {
      versionPortales = estado.version;
      const promesa = api("GET", `/api/estadisticas/portales?${parametros()}`);
      promesaPortales = promesa;
      promesa.catch(() => {
        if (promesaPortales === promesa) promesaPortales = null;
      });
    }
    return promesaPortales;
  }

  // -------------------------------------------------------------------------
  // Filtro de fechas común
  // -------------------------------------------------------------------------

  // Fechas recordadas durante la sesión del navegador (una clave por vista). Si el almacenamiento no está
  // disponible (modo privado, bloqueado), la vista usa los últimos 30 días.
  const DIA_VALIDO = /^\d{4}-\d{2}-\d{2}$/;

  function leerRango() {
    try {
      const r = JSON.parse(sessionStorage.getItem(CLAVE_RANGO) || "null");
      if (r && DIA_VALIDO.test(r.desde) && DIA_VALIDO.test(r.hasta) && r.desde <= r.hasta) return r;
    } catch (e) { /* sin almacenamiento o valor corrupto: se usan las fechas por defecto */ }
    return null;
  }

  function guardarRango(desde, hasta) {
    try {
      sessionStorage.setItem(CLAVE_RANGO, JSON.stringify({ desde, hasta }));
    } catch (e) { /* sin almacenamiento: las fechas no se recuerdan */ }
  }

  function fijarRangoInicial() {
    const guardado = leerRango();
    if (guardado) {
      $("e-desde").value = guardado.desde;
      $("e-hasta").value = guardado.hasta;
      return;
    }
    const hoy = new Date();
    $("e-hasta").value = textoDia(hoy);
    $("e-desde").value = textoDia(new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - (DIAS_POR_DEFECTO - 1)));
  }

  function marcarErrorFechas(mensaje) {
    $("e-fechas").textContent = mensaje || "";
    for (const id of ["e-desde", "e-hasta"]) {
      if (mensaje) $(id).setAttribute("aria-invalid", "true");
      else $(id).removeAttribute("aria-invalid");
    }
  }

  function aplicarRango() {
    const desde = $("e-desde").value;
    const hasta = $("e-hasta").value;
    if (desde && hasta && desde > hasta) {
      marcarErrorFechas("La fecha «desde» no puede ser posterior a «hasta».");
      return;
    }
    marcarErrorFechas("");
    if (desde && hasta) guardarRango(desde, hasta);
    estado.rango = agregarRango(new URLSearchParams(), desde, hasta);
    estado.version++;
    refrescarVisibles();
  }

  // Errores comunes al cargar: 401/403 ya muestran la pantalla de bloqueo; 422 de fechas va junto a los campos.
  function avisarError(e) {
    if (e.status === 401 || e.status === 403) return;
    const errores = e.errores || {};
    if (e.status === 422 && (errores.desde || errores.hasta)) marcarErrorFechas(errores.desde || errores.hasta);
    else toast("error", e.message);
  }

  async function exportarCsv(boton, url, nombrePorDefecto, sujeto) {
    setOcupado(boton, true, "Exportando…");
    try {
      const tope = await descargarCsv(url, nombrePorDefecto);
      if (tope) toast("aviso", `El archivo incluye solo los primeros ${numero.format(Number(tope))} ${sujeto}. Acota las fechas para exportar el resto.`);
      else toast("exito", "Archivo exportado.");
    } catch (e) {
      avisarError(e);
    } finally {
      setOcupado(boton, false);
    }
  }

  // -------------------------------------------------------------------------
  // Piezas comunes: tabla con estados (carga, vacío, error) y celdas de sesiones
  // -------------------------------------------------------------------------

  function crearTabla({ columnas, textoCarga, textoVacio, reintentar, conPie }) {
    const carga = el("div", { class: "estado", hidden: true }, [
      el("span", { class: "spinner", "aria-hidden": "true" }),
      el("span", { text: textoCarga }),
    ]);
    const textoVacioNodo = el("p", { text: textoVacio });
    const vacio = el("div", { class: "estado", hidden: true }, textoVacioNodo);
    const textoError = el("p", { text: "No se pudieron cargar los datos." });
    const botonReintentar = el("button", { type: "button", class: "btn btn-secundario", text: "Reintentar" });
    botonReintentar.addEventListener("click", reintentar);
    const error = el("div", { class: "estado estado-error", role: "alert", hidden: true }, [textoError, botonReintentar]);
    const cuerpo = el("tbody");
    const pie = conPie ? el("tfoot") : null;
    const tabla = el("table", { class: "tabla", hidden: true }, [
      el("thead", null, el("tr", null, columnas.map((c) => el("th", { scope: "col", class: c.clase, text: c.titulo })))),
      cuerpo,
      pie,
    ]);

    // `mensaje`: texto del error o, con "vacio", texto del estado vacío (si falta, el de por defecto).
    function mostrar(cual, mensaje) {
      carga.hidden = cual !== "carga";
      vacio.hidden = cual !== "vacio";
      error.hidden = cual !== "error";
      tabla.hidden = cual !== "tabla";
      if (cual === "vacio") textoVacioNodo.textContent = mensaje || textoVacio;
      else if (mensaje) textoError.textContent = mensaje;
    }

    return { nodos: [carga, vacio, error, tabla], cuerpo, pie, mostrar };
  }

  const COLUMNA_SIN_ACTIVIDAD = { titulo: "Sin actividad", clase: "td-num" };

  // `conSinActividad`: con la columna «Sin actividad» después de «Sesiones» (tabla de usuarios).
  function columnasSesiones(conSinActividad) {
    return [
      { titulo: "Sesiones", clase: "td-num" },
      ...(conSinActividad ? [COLUMNA_SIN_ACTIVIDAD] : []),
      { titulo: "Horas totales", clase: "td-num" },
      { titulo: "Promedio por sesión", clase: "td-num" },
      { titulo: "Última conexión" },
    ];
  }

  function ayuda(texto, title) {
    return el("span", { class: "ayuda-medidas", title, text: texto });
  }

  // Sesiones · [Sin actividad] · Horas totales · Promedio · Última conexión. Bajo las horas va «medidas: N de M»
  // si hay sesiones sin tiempo y, sin la columna, «sin actividad: K» si hay sesiones que nunca enviaron un latido.
  function celdasSesiones(d, conSinActividad) {
    const horas = el("td", { class: "td-num", "data-label": "Horas totales", text: duracion(d.segundosTotales) });
    if (d.sesiones > 0 && d.sesionesMedidas < d.sesiones) {
      horas.append(ayuda(
        `medidas: ${numero.format(d.sesionesMedidas)} de ${numero.format(d.sesiones)}`,
        "Sesiones con tiempo medido. Las demás no tienen latidos y no suman horas.",
      ));
    }
    if (!conSinActividad && d.sinActividad > 0) {
      horas.append(ayuda(
        `sin actividad: ${numero.format(d.sinActividad)}`,
        "Sesiones medibles que nunca enviaron un latido (cuentan 0 min).",
      ));
    }
    return [
      el("td", { class: "td-num", "data-label": "Sesiones", text: numero.format(d.sesiones) }),
      ...(conSinActividad
        ? [el("td", { class: "td-num", "data-label": "Sin actividad", text: numero.format(d.sinActividad) })]
        : []),
      horas,
      el("td", { class: "td-num", "data-label": "Promedio por sesión", text: duracion(d.promedioSeg) }),
      el("td", { "data-label": "Última conexión", text: fechaLocal(d.ultimaConexion) }),
    ];
  }

  // «7 usuarios» o, con filtro, «2 de 7 usuarios» (el plural sigue al total).
  function textoUsuarios(cantidad, de) {
    const total = de === undefined ? cantidad : de;
    const palabra = total === 1 ? "usuario" : "usuarios";
    return de === undefined
      ? `${numero.format(cantidad)} ${palabra}`
      : `${numero.format(cantidad)} de ${numero.format(de)} ${palabra}`;
  }

  // -------------------------------------------------------------------------
  // Vista «General por portal»: tabla del total por portal
  // -------------------------------------------------------------------------

  function montarTablaGeneral() {
    const exportar = el("button", { type: "button", class: "btn btn-secundario btn-chico", text: "Exportar a Excel" });
    const tabla = crearTabla({
      columnas: [{ titulo: "Portal" }, { titulo: "Usuarios únicos", clase: "td-num" }, ...columnasSesiones(false)],
      textoCarga: "Cargando estadísticas…",
      textoVacio: "Todavía no hay portales con accesos registrados.",
      reintentar: () => vista.cargar(),
      conPie: true,
    });
    $("general-cuerpo").append(
      el("div", { class: "subvista-barra" }, [
        el("p", { class: "resumen", text: "Sesiones = ingresos con resultado OK. Usuarios únicos del total: sin repetir entre portales." }),
        exportar,
      ]),
      ...tabla.nodos,
    );
    exportar.addEventListener("click", () => exportarCsv(
      exportar,
      `/api/estadisticas/portales/csv?${parametros({ tz_offset_min: tzOffsetMin() })}`,
      "estadisticas_portales.csv",
      "portales",
    ));

    // El nombre del portal enlaza a su vista (la fila del total no tiene slug).
    function filaPortal(nombre, d) {
      const celda = d.slug
        ? el("td", { "data-label": "Portal" }, el("a", { class: "enlace-portal", href: `/estadisticas/portal/${encodeURIComponent(d.slug)}`, text: nombre }))
        : el("td", { "data-label": "Portal", text: nombre });
      return el("tr", null, [
        celda,
        el("td", { class: "td-num", "data-label": "Usuarios únicos", text: numero.format(d.usuariosUnicos) }),
        ...celdasSesiones(d, false),
      ]);
    }

    let pedido = 0;
    const vista = registrarVista({
      visible: () => true,
      async cargar() {
        const actual = ++pedido;
        tabla.mostrar("carga");
        let r;
        try {
          r = await datosPortales();
        } catch (e) {
          if (actual !== pedido) return;
          tabla.mostrar("error", e.message);
          avisarError(e);
          return;
        }
        if (actual !== pedido) return;
        if (!r.portales.length) {
          tabla.mostrar("vacio");
          return;
        }
        tabla.cuerpo.replaceChildren(...r.portales.map((p) => filaPortal(p.portal, p)));
        const total = filaPortal(TOTAL_PORTAL_CORPORATIVO, r.total);
        total.classList.add("fila-total");
        tabla.pie.replaceChildren(total);
        tabla.mostrar("tabla");
      },
    });
  }


  // -------------------------------------------------------------------------
  // Gráficos (v16): piezas comunes
  // -------------------------------------------------------------------------

  const fmtSesiones = (n) => `${numero.format(n)} ${n === 1 ? "sesión" : "sesiones"}`;
  const porcentaje = (n, total) => (total ? `${numero.format(Math.round((n / total) * 100))} %` : "0 %");

  // Tooltip de un valor en horas: muestra la duración exacta («52 h 10 min») desde los segundos.
  const tooltipDuracion = (segundosDe) => ({
    callbacks: { label: (ctx) => ` ${ctx.dataset.label || ctx.label}: ${duracion(segundosDe(ctx))}` },
  });
  const ejeHoras = { beginAtZero: true, ticks: { callback: (v) => G.textoHoras(v) } };
  const ejeEnteros = { beginAtZero: true, ticks: { precision: 0 } };

  // Sección de gráficos con su propia vista (carga diferida y versión por rango).
  function seccionGraficos(visible, cargar) {
    const nodo = el("div", { class: "graficos" });
    const vista = registrarVista({ visible, cargar: () => cargar(vista) });
    return { nodo, vista };
  }

  // Ejecuta `pedir` y avisa a los paneles; descarta respuestas viejas (otro rango o reintento).
  // `alFallar(e)` (opcional) recibe el error de la respuesta vigente (p. ej. 422 del buscador por correo).
  async function cargarPaneles(vista, paneles, pedir, alFallar) {
    vista.pedido = (vista.pedido || 0) + 1;
    const actual = vista.pedido;
    paneles.forEach((p) => p.mostrar("carga"));
    try {
      const datos = await pedir();
      return actual === vista.pedido ? datos : null;
    } catch (e) {
      // La tabla ya avisa los errores con un toast; aquí basta el estado de cada panel.
      if (actual === vista.pedido) {
        paneles.forEach((p) => p.mostrar("error", e.message));
        if (alFallar) alFallar(e);
      }
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // Vista «General por portal»: gráficos (arriba de la tabla)
  // -------------------------------------------------------------------------

  function montarGraficosGeneral() {
    const reintentar = () => seccion.vista.cargar();
    const tarjetas = el("div", { class: "indicadores graficos-tarjetas" });
    const panelReparto = G.crearPanel({ titulo: "Reparto por portal", reintentar });
    const panelDias = G.crearPanel({ titulo: "Uso por día (sesiones por portal)", ancho: "completo", reintentar });
    const panelHoras = G.crearPanel({ titulo: "Horas por portal", reintentar });
    const paneles = [panelReparto, panelDias, panelHoras];

    // Selector Sesiones / Horas de la dona.
    let modo = "sesiones";
    let ultimo = null;
    const segmentos = ["sesiones", "horas"].map((valor) => {
      const boton = el("button", {
        type: "button", class: "segmento", "aria-pressed": String(valor === modo),
        text: valor === "sesiones" ? "Sesiones" : "Horas",
      });
      boton.addEventListener("click", () => {
        modo = valor;
        segmentos.forEach((b, i) => b.setAttribute("aria-pressed", String(["sesiones", "horas"][i] === modo)));
        if (ultimo) dibujarReparto(ultimo);
      });
      return boton;
    });
    panelReparto.extra.append(el("div", { class: "segmentos", role: "group", "aria-label": "Medir el reparto por" }, segmentos));

    const seccion = seccionGraficos(() => true, async (vista) => {
      tarjetas.replaceChildren();
      const datos = await cargarPaneles(vista, paneles, () => Promise.all([
        datosPortales(),
        api("GET", `/api/estadisticas/series?${parametros({ tz_offset_min: tzOffsetMin() })}`),
      ]));
      if (!datos) return;
      const [portales, series] = datos;
      ultimo = portales;
      G.tarjetas(tarjetas, portales.total);
      dibujarReparto(portales);
      dibujarDias(series);
      dibujarHoras(portales);
    });
    seccion.nodo.append(tarjetas, ...paneles.map((p) => p.nodo));
    $("general-cuerpo").prepend(seccion.nodo);

    function dibujarReparto(r) {
      const valores = r.portales.map((p) => (modo === "sesiones" ? p.sesiones : G.horas(p.segundosTotales)));
      const total = valores.reduce((a, b) => a + b, 0);
      if (!total) {
        panelReparto.mostrar("vacio");
        return;
      }
      const texto = (i) => (modo === "sesiones"
        ? fmtSesiones(r.portales[i].sesiones) : duracion(r.portales[i].segundosTotales || 0));
      panelReparto.dibujar({
        type: "doughnut",
        data: {
          labels: r.portales.map((p) => p.portal),
          datasets: [{
            data: valores,
            backgroundColor: r.portales.map((p) => G.colorPortal(p.portal)),
            borderColor: "rgba(3, 8, 20, 0.9)", borderWidth: 2,
          }],
        },
        options: {
          cutout: "62%",
          plugins: {
            legend: { position: "bottom" },
            tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${texto(ctx.dataIndex)} (${porcentaje(valores[ctx.dataIndex], total)})` } },
          },
        },
      }, r.portales.map((p, i) => `${p.portal} ${texto(i)} (${porcentaje(valores[i], total)})`).join(", ") + ".");
    }

    function dibujarDias(s) {
      if (!s.total.sesiones.some((n) => n > 0)) {
        panelDias.mostrar("vacio");
        return;
      }
      panelDias.dibujar({
        type: "bar",
        data: {
          labels: s.dias.map(G.diaCorto),
          datasets: s.portales.map((p) => ({
            label: p.portal, data: p.sesiones,
            backgroundColor: G.colorPortal(p.portal), borderRadius: 3, maxBarThickness: 28,
          })),
        },
        options: {
          scales: { x: { stacked: true, grid: { display: false } }, y: { ...ejeEnteros, stacked: true } },
          plugins: {
            legend: { position: "bottom" },
            tooltip: {
              mode: "index", intersect: false,
              callbacks: { footer: (items) => `Total: ${fmtSesiones(s.total.sesiones[items[0].dataIndex])}` },
            },
          },
        },
      }, G.resumenSerie(s.dias, s.total.sesiones, fmtSesiones));
    }

    function dibujarHoras(r) {
      if (!r.portales.some((p) => p.segundosTotales)) {
        panelHoras.mostrar("vacio");
        return;
      }
      panelHoras.dibujar({
        type: "bar",
        data: {
          labels: r.portales.map((p) => p.portal),
          datasets: [{
            label: "Horas", data: r.portales.map((p) => G.horas(p.segundosTotales)),
            backgroundColor: r.portales.map((p) => G.colorPortal(p.portal)), borderRadius: 4, maxBarThickness: 34,
          }],
        },
        options: {
          indexAxis: "y",
          scales: { x: ejeHoras, y: { grid: { display: false } } },
          plugins: {
            legend: { display: false },
            tooltip: tooltipDuracion((ctx) => r.portales[ctx.dataIndex].segundosTotales || 0),
          },
        },
      }, r.portales.map((p) => `${p.portal} ${duracion(p.segundosTotales || 0)}`).join(", ") + ".");
    }
  }

  // -------------------------------------------------------------------------
  // Gráficos de cada portal (genéricos: sirven para cualquier portal que devuelva la API)
  // -------------------------------------------------------------------------

  // Buscador por correo de los gráficos (v17): texto aplicado recordado durante la sesión del navegador,
  // una clave por portal (como las fechas). Las tablas de las pestañas tienen sus propios buscadores.
  const CLAVE_CORREO = `mira.estadisticas.correo.portal.${SLUG}`;
  const MAX_LARGO_CORREO = 256;
  const SIN_COINCIDENCIAS = "Sin sesiones que coincidan con la búsqueda";

  function leerCorreo() {
    try {
      const valor = (sessionStorage.getItem(CLAVE_CORREO) || "").trim();
      return valor.length <= MAX_LARGO_CORREO ? valor : "";
    } catch (e) {
      return "";  // sin almacenamiento: los gráficos empiezan sin filtro
    }
  }

  function guardarCorreo(valor) {
    try {
      if (valor) sessionStorage.setItem(CLAVE_CORREO, valor);
      else sessionStorage.removeItem(CLAVE_CORREO);
    } catch (e) { /* sin almacenamiento: el filtro no se recuerda */ }
  }

  // Devuelve [buscador, sección de gráficos]: el buscador va entre el filtro de fechas y las tarjetas.
  function graficosPortal(portal) {
    const color = G.colorPortal(portal);
    const reintentar = () => seccion.vista.cargar();

    const idCorreo = nuevoId("correo");
    const idErrorCorreo = nuevoId("error-correo");
    const campoCorreo = el("input", {
      type: "search", id: idCorreo, maxlength: String(MAX_LARGO_CORREO), placeholder: "Contiene…",
      autocomplete: "off", "aria-describedby": idErrorCorreo,
    });
    const errorCorreo = el("p", { class: "error-campo", id: idErrorCorreo, role: "alert" });
    const buscador = el("form", {
      class: "subvista-filtros buscador-graficos", novalidate: true,
      "aria-label": `Buscar por correo en los gráficos de ${portal}`,
    }, [
      el("div", { class: "campo campo-buscar" }, [el("label", { for: idCorreo, text: "Correo" }), campoCorreo, errorCorreo]),
      el("div", { class: "barra-acciones" }, [
        el("button", { type: "submit", class: "btn btn-primario btn-chico", text: "Buscar" }),
      ]),
    ]);
    const textoFiltro = el("strong");
    const quitar = el("button", {
      type: "button", class: "filtro-quitar", "aria-label": "Quitar filtro", title: "Quitar filtro", text: "×",
    });
    const chip = el("p", { class: "filtro-activo", hidden: true }, [
      el("span", { text: "Filtrado por: " }), textoFiltro, quitar,
    ]);

    // Texto aplicado con «Buscar» (o Enter): lo reusan el cambio de fechas y «Reintentar».
    let buscado = leerCorreo();
    campoCorreo.value = buscado;

    function pintarFiltro() {
      textoFiltro.textContent = buscado;
      chip.hidden = !buscado;
    }

    function marcarErrorCorreo(mensaje) {
      errorCorreo.textContent = mensaje || "";
      if (mensaje) campoCorreo.setAttribute("aria-invalid", "true");
      else campoCorreo.removeAttribute("aria-invalid");
    }

    function aplicarBusqueda(valor) {
      const texto = valor.trim();
      if (texto.length > MAX_LARGO_CORREO) {
        marcarErrorCorreo(`El correo no puede superar los ${MAX_LARGO_CORREO} caracteres.`);
        return;
      }
      marcarErrorCorreo("");
      buscado = texto;
      guardarCorreo(buscado);
      pintarFiltro();
      seccion.vista.cargar();
    }

    buscador.addEventListener("submit", (ev) => {
      ev.preventDefault();
      aplicarBusqueda(campoCorreo.value);
    });
    quitar.addEventListener("click", () => {
      campoCorreo.value = "";
      aplicarBusqueda("");
      campoCorreo.focus();
    });

    const tarjetas = el("div", { class: "indicadores graficos-tarjetas" });
    const panelDias = G.crearPanel({ titulo: "Sesiones y horas por día", ancho: "completo", alto: "alto", reintentar });
    const panelTop = G.crearPanel({ titulo: "Top 10 usuarios por horas", alto: "alto", reintentar });
    const panelCierres = G.crearPanel({ titulo: "Cómo terminan las sesiones", alto: "alto", reintentar });
    const panelDuracion = G.crearPanel({ titulo: "Duración de las sesiones", reintentar });
    const panelCalor = G.crearPanel({
      titulo: "Sesiones por día de la semana y hora", ancho: "completo", alto: "auto", reintentar, conLienzo: false,
    });
    const paneles = [panelDias, panelTop, panelCierres, panelDuracion, panelCalor];

    const seccion = seccionGraficos(() => true, async (vista) => {
      tarjetas.replaceChildren();
      // Con filtro, las tarjetas salen de /resumen (usuarios únicos contados con el filtro); sin filtro,
      // de la consulta de /portales que ya comparte la página.
      const correo = buscado;
      const filtros = (extra) => parametros({ portal, correo, ...extra });
      const conTz = () => filtros({ tz_offset_min: tzOffsetMin() });
      const datos = await cargarPaneles(vista, paneles, () => Promise.all([
        correo ? api("GET", `/api/estadisticas/resumen?${filtros()}`) : datosPortales(),
        api("GET", `/api/estadisticas/series?${conTz()}`),
        api("GET", `/api/estadisticas/distribucion?${conTz()}`),
        api("GET", `/api/estadisticas/usuarios?${filtros()}`),
      ]), (e) => {
        if (e.status === 422 && e.errores && e.errores.correo) marcarErrorCorreo(e.errores.correo);
      });
      if (!datos) return;
      const [base, series, distribucion, usuarios] = datos;
      const resumen = (correo ? base : base.portales.find((p) => p.portal === portal))
        || { usuariosUnicos: 0, sesiones: 0, segundosTotales: null, promedioSeg: null };
      G.tarjetas(tarjetas, resumen);
      if (!resumen.sesiones) {
        paneles.forEach((p) => p.mostrar("vacio", correo ? SIN_COINCIDENCIAS : ""));
        return;
      }
      dibujarDias(series);
      dibujarTop(usuarios.filas);
      dibujarCierres(distribucion.cierres);
      dibujarDuracion(distribucion.duracion);
      G.mapaCalor(panelCalor, distribucion.calor, color);
    });
    seccion.nodo.append(chip, tarjetas, ...paneles.map((p) => p.nodo));
    pintarFiltro();

    function dibujarDias(s) {
      const p = s.portales[0] || { sesiones: s.dias.map(() => 0), segundos: s.dias.map(() => 0) };
      if (!p.sesiones.some((n) => n > 0)) {
        panelDias.mostrar("vacio");
        return;
      }
      panelDias.dibujar({
        type: "bar",  // cada serie define su tipo (barras y línea)
        data: {
          labels: s.dias.map(G.diaCorto),
          datasets: [
            {
              type: "bar", label: "Sesiones", data: p.sesiones, yAxisID: "y",
              backgroundColor: G.conAlfa(color, 0.75), borderRadius: 3, maxBarThickness: 28, order: 2,
            },
            {
              type: "line", label: "Horas", data: p.segundos.map(G.horas), yAxisID: "y1",
              borderColor: variableTexto(), backgroundColor: variableTexto(), pointRadius: 2, tension: 0.25, order: 1,
            },
          ],
        },
        options: {
          interaction: { mode: "index", intersect: false },
          scales: {
            x: { grid: { display: false } },
            y: { ...ejeEnteros, position: "left", title: { display: true, text: "Sesiones" } },
            y1: { ...ejeHoras, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Horas" } },
          },
          plugins: {
            legend: { position: "bottom" },
            tooltip: {
              callbacks: {
                label: (ctx) => (ctx.dataset.yAxisID === "y1"
                  ? ` Horas: ${duracion(p.segundos[ctx.dataIndex])}`
                  : ` Sesiones: ${numero.format(ctx.parsed.y)}`),
              },
            },
          },
        },
      }, `${G.resumenSerie(s.dias, p.sesiones, fmtSesiones)} Horas en total: ${duracion(p.segundos.reduce((a, b) => a + b, 0))}.`);
    }

    function dibujarTop(filas) {
      const top = filas.filter((u) => u.segundosTotales > 0).slice(0, 10);
      if (!top.length) {
        panelTop.mostrar("vacio");
        return;
      }
      const nombre = (u) => u.usuario || u.correo || "—";
      panelTop.dibujar({
        type: "bar",
        data: {
          labels: top.map(nombre),
          datasets: [{
            label: "Horas", data: top.map((u) => G.horas(u.segundosTotales)),
            backgroundColor: G.conAlfa(color, 0.8), borderRadius: 4, maxBarThickness: 22,
          }],
        },
        options: {
          indexAxis: "y",
          scales: { x: ejeHoras, y: { grid: { display: false }, ticks: { autoSkip: false } } },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: (items) => nombre(top[items[0].dataIndex]),
                label: (ctx) => ` ${duracion(top[ctx.dataIndex].segundosTotales)} · ${fmtSesiones(top[ctx.dataIndex].sesiones)}`,
                afterLabel: (ctx) => (top[ctx.dataIndex].usuario ? ` ${top[ctx.dataIndex].correo}` : ""),
              },
            },
          },
        },
      }, top.slice(0, 3).map((u, i) => `${i + 1}. ${nombre(u)} ${duracion(u.segundosTotales)}`).join("; ") + ".");
    }

    function dibujarCierres(cierres) {
      const tipos = Object.keys(cierres).filter((t) => t !== "Otro" || cierres[t] > 0);
      const total = tipos.reduce((a, t) => a + cierres[t], 0);
      if (!total) {
        panelCierres.mostrar("vacio");
        return;
      }
      panelCierres.dibujar({
        type: "doughnut",
        data: {
          labels: tipos,
          datasets: [{
            data: tipos.map((t) => cierres[t]),
            backgroundColor: tipos.map((t) => G.COLORES_CIERRE[t] || "#6c7f99"),
            borderColor: "rgba(3, 8, 20, 0.9)", borderWidth: 2,
          }],
        },
        options: {
          cutout: "58%",
          plugins: {
            legend: { position: "bottom" },
            tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${fmtSesiones(ctx.parsed)} (${porcentaje(ctx.parsed, total)})` } },
          },
        },
      }, tipos.map((t) => `${t} ${numero.format(cierres[t])}`).join(", ") + ".");
    }

    function dibujarDuracion(d) {
      const total = d.rangos.reduce((a, r) => a + r.sesiones, 0);
      if (!total) {
        panelDuracion.mostrar("vacio");
      } else {
        panelDuracion.dibujar({
          type: "bar",
          data: {
            labels: d.rangos.map((r) => r.etiqueta),
            datasets: [{
              label: "Sesiones", data: d.rangos.map((r) => r.sesiones),
              backgroundColor: G.conAlfa(color, 0.8), borderRadius: 4, maxBarThickness: 46,
            }],
          },
          options: {
            scales: { x: { grid: { display: false } }, y: ejeEnteros },
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (ctx) => ` ${fmtSesiones(ctx.parsed.y)} (${porcentaje(ctx.parsed.y, total)})` } },
            },
          },
        }, d.rangos.map((r) => `${r.etiqueta}: ${numero.format(r.sesiones)}`).join(", ") + ".");
      }
      const notas = [];
      if (d.sinActividad) notas.push(`Sin actividad: ${numero.format(d.sinActividad)}`);
      if (d.sinMedir) notas.push(`Sin medir: ${numero.format(d.sinMedir)}`);
      // También con «vacío»: explica por qué no hay barras. Sin notas, el pie se limpia.
      panelDuracion.pie(notas.length ? `Solo sesiones con tiempo medido. Aparte: ${notas.join(" · ")}.` : "");
    }

    return [buscador, seccion.nodo];
  }

  // Color del texto principal (la línea de horas va en blanco para distinguirse de las barras del portal).
  let colorTexto = null;
  function variableTexto() {
    if (!colorTexto) colorTexto = getComputedStyle(document.documentElement).getPropertyValue("--texto").trim() || "#ffffff";
    return colorTexto;
  }

  // -------------------------------------------------------------------------
  // Vista «Portal <nombre>»: gráficos y sub-vistas en pestañas
  // -------------------------------------------------------------------------

  // Usuarios (general): una fila por usuario, de más a menos horas, con buscador por correo.
  // Mismo formulario que «Usuarios (detallado)», pero con su propio filtro.
  function vistaUsuarios(panel, portal, vista) {
    const idCorreo = nuevoId("correo");
    const correo = el("input", { type: "search", id: idCorreo, maxlength: "256", placeholder: "Contiene…", autocomplete: "off" });
    const exportar = el("button", { type: "button", class: "btn btn-secundario btn-chico", text: "Exportar a Excel" });
    const formulario = el("form", { class: "subvista-filtros", novalidate: true }, [
      el("div", { class: "campo campo-buscar" }, [el("label", { for: idCorreo, text: "Correo" }), correo]),
      el("div", { class: "barra-acciones" }, [
        el("button", { type: "submit", class: "btn btn-primario btn-chico", text: "Buscar" }),
        exportar,
      ]),
    ]);
    const resumen = el("p", { class: "resumen", "aria-live": "polite" });
    const tabla = crearTabla({
      columnas: [{ titulo: "Usuario" }, { titulo: "Correo" }, ...columnasSesiones(true)],
      textoCarga: "Cargando usuarios…",
      textoVacio: "No hay sesiones en el período seleccionado.",
      reintentar: () => vista.cargar(),
    });
    panel.append(formulario, resumen, ...tabla.nodos);

    // Texto aplicado con «Buscar»: lo reusan el cambio de fechas, «Reintentar» y la exportación,
    // así el archivo coincide con lo que se ve aunque el campo se haya editado sin buscar.
    let buscado = "";
    const filtros = (extra) => parametros({ portal, correo: buscado, ...extra });

    exportar.addEventListener("click", () => exportarCsv(
      exportar,
      `/api/estadisticas/usuarios/csv?${filtros({ tz_offset_min: tzOffsetMin() })}`,
      "estadisticas_usuarios.csv",
      "usuarios",
    ));
    formulario.addEventListener("submit", (ev) => {
      ev.preventDefault();
      buscado = correo.value.trim();
      vista.cargar();
    });

    let pedido = 0;
    vista.cargar = async () => {
      const actual = ++pedido;
      resumen.textContent = "";
      tabla.mostrar("carga");
      let r;
      try {
        r = await api("GET", `/api/estadisticas/usuarios?${filtros()}`);
      } catch (e) {
        if (actual !== pedido) return;
        tabla.mostrar("error", e.message);
        avisarError(e);
        return;
      }
      if (actual !== pedido) return;
      tabla.cuerpo.replaceChildren(...r.filas.map((u) => el("tr", null, [
        el("td", { "data-label": "Usuario", text: u.usuario || "—" }),
        el("td", { class: "td-correo", "data-label": "Correo", text: u.correo || "—" }),
        ...celdasSesiones(u, true),
      ])));
      const conFiltro = Boolean(r.correo);
      if (!r.total) {
        // Con filtro y sin coincidencias se muestra el total igual, para saber que el portal sí tiene usuarios.
        if (conFiltro && r.totalSinFiltro) resumen.textContent = textoUsuarios(0, r.totalSinFiltro);
        tabla.mostrar("vacio", conFiltro ? "Sin usuarios que coincidan con la búsqueda" : "");
        return;
      }
      resumen.textContent = (conFiltro ? textoUsuarios(r.total, r.totalSinFiltro) : textoUsuarios(r.totalSinFiltro))
        + (r.truncado ? ` (se muestran los primeros ${numero.format(r.total)})` : "");
      tabla.mostrar("tabla");
    };
  }

  // Usuarios (detallado): la tabla de /historial filtrada al portal, con correo, resultado, páginas y CSV.
  function vistaDetalle(panel, portal, vista) {
    const idCorreo = nuevoId("correo");
    const idResultado = nuevoId("resultado");
    const correo = el("input", { type: "search", id: idCorreo, maxlength: "256", placeholder: "Contiene…", autocomplete: "off" });
    const resultado = el("select", { id: idResultado }, [
      el("option", { value: "", text: "Todos" }),
      el("option", { value: "OK", text: "OK" }),
      el("option", { value: "Denegado", text: "Denegado" }),
    ]);
    const exportar = el("button", { type: "button", class: "btn btn-secundario btn-chico", text: "Exportar a Excel" });
    const formulario = el("form", { class: "subvista-filtros", novalidate: true }, [
      el("div", { class: "campo campo-buscar" }, [el("label", { for: idCorreo, text: "Correo" }), correo]),
      el("div", { class: "campo" }, [el("label", { for: idResultado, text: "Resultado" }), resultado]),
      el("div", { class: "barra-acciones" }, [
        el("button", { type: "submit", class: "btn btn-primario btn-chico", text: "Buscar" }),
        exportar,
      ]),
    ]);
    const resumen = el("p", { class: "resumen", "aria-live": "polite" });
    const tabla = crearTabla({
      columnas: ["Fecha", "Usuario", "Correo", "Resultado", "Final de sesión", "Tiempo de sesión", "Cierre"]
        .map((titulo) => ({ titulo })),
      textoCarga: "Cargando accesos…",
      textoVacio: "No hay accesos para los filtros seleccionados.",
      reintentar: () => cargarPagina(),
    });
    const anterior = el("button", { type: "button", class: "btn btn-fantasma btn-chico", text: "← Anterior" });
    const siguiente = el("button", { type: "button", class: "btn btn-fantasma btn-chico", text: "Siguiente →" });
    const textoPagina = el("span", { "aria-live": "polite" });
    const paginacion = el("nav", { class: "paginacion", "aria-label": `Paginación de ${portal}`, hidden: true },
      [anterior, textoPagina, siguiente]);
    panel.append(formulario, resumen, ...tabla.nodos, paginacion);

    let pagina = 1;
    let paginas = 1;
    let pedido = 0;

    const filtros = () => parametros({ portal, correo: correo.value.trim(), resultado: resultado.value });

    function filaAcceso(a) {
      const ok = a.Resultado === "OK";
      return el("tr", null, [
        el("td", { "data-label": "Fecha", text: fechaLocal(a.Fecha) }),
        el("td", { "data-label": "Usuario", text: a.Usuario || "—" }),
        el("td", { class: "td-correo", "data-label": "Correo", text: a.Correo }),
        el("td", { "data-label": "Resultado" },
          el("span", { class: `chip ${ok ? "chip-ok" : "chip-denegado"}`, text: a.Resultado })),
        a.EnCurso
          ? el("td", { "data-label": "Final de sesión" }, el("span", { class: "chip chip-en-curso", text: "En curso" }))
          : el("td", { "data-label": "Final de sesión", text: textoFinal(a) }),
        el("td", { class: "td-tiempo", "data-label": "Tiempo de sesión", text: textoTiempo(a) }),
        el("td", { "data-label": "Cierre", text: textoCierre(a) }),
      ]);
    }

    function mostrar(cual, mensaje) {
      tabla.mostrar(cual, mensaje);
      paginacion.hidden = cual !== "tabla" || paginas <= 1;
    }

    async function cargarPagina() {
      const actual = ++pedido;
      const params = filtros();
      params.set("pagina", String(pagina));
      resumen.textContent = "";
      mostrar("carga");
      let r;
      try {
        r = await api("GET", `/api/historial?${params}`);
      } catch (e) {
        if (actual !== pedido) return;
        mostrar("error", e.message);
        avisarError(e);
        return;
      }
      if (actual !== pedido) return;
      paginas = r.paginas;
      // Si la página quedó fuera de rango (cambiaron los datos), se vuelve a la última.
      if (!r.filas.length && r.total > 0 && pagina > r.paginas) {
        pagina = r.paginas;
        cargarPagina();
        return;
      }
      tabla.cuerpo.replaceChildren(...r.filas.map(filaAcceso));
      if (r.total === 0) {
        mostrar("vacio");
        return;
      }
      const desde = (r.pagina - 1) * r.tamano + 1;
      const hasta = desde + r.filas.length - 1;
      resumen.textContent = `${numero.format(r.total)} ${r.total === 1 ? "acceso" : "accesos"} · mostrando ${numero.format(desde)}–${numero.format(hasta)}`;
      textoPagina.textContent = `Página ${numero.format(r.pagina)} de ${numero.format(r.paginas)}`;
      anterior.disabled = r.pagina <= 1;
      siguiente.disabled = r.pagina >= r.paginas;
      mostrar("tabla");
    }

    function irAPagina(nueva) {
      if (nueva < 1 || nueva > paginas || nueva === pagina) return;
      pagina = nueva;
      cargarPagina();
      panel.scrollIntoView({ block: "start", behavior: "smooth" });
    }

    function buscar() {
      pagina = 1;
      cargarPagina();
    }

    formulario.addEventListener("submit", (ev) => {
      ev.preventDefault();
      buscar();
    });
    resultado.addEventListener("change", buscar);
    anterior.addEventListener("click", () => irAPagina(pagina - 1));
    siguiente.addEventListener("click", () => irAPagina(pagina + 1));
    exportar.addEventListener("click", () => exportarCsv(
      exportar,
      `/api/historial/csv?${filtros()}&tz_offset_min=${tzOffsetMin()}`,
      "historial_accesos.csv",
      "accesos más recientes",
    ));

    vista.cargar = buscar;
  }

  // Sub-vistas de cada portal, en orden de pestaña. `montar(panel, portal, vista)` arma la sub-vista
  // dentro de `panel` y define `vista.cargar()`. Nivel 3 (funcionalidades): agregar aquí su entrada.
  const SUBVISTAS = [
    { titulo: "Usuarios (general)", montar: vistaUsuarios },
    { titulo: "Usuarios (detallado)", montar: vistaDetalle },
  ];

  // Arma la vista de un portal dentro de #portal-cuerpo: gráficos arriba y las pestañas de SUBVISTAS.
  function montarPortal(portal) {
    const cuerpo = $("portal-cuerpo");
    const tablist = cuerpo.querySelector(".pestanas");
    tablist.setAttribute("aria-label", `Vistas del portal ${portal}`);
    const contenedor = cuerpo.querySelector(".subvistas");
    tablist.before(...graficosPortal(portal));

    const pestanas = SUBVISTAS.map((def, i) => {
      const idPanel = nuevoId("panel");
      const idPestana = nuevoId("pestana");
      const panel = el("div", { class: "subvista", role: "tabpanel", id: idPanel, "aria-labelledby": idPestana, tabindex: "-1", hidden: i !== 0 });
      const boton = el("button", {
        type: "button", role: "tab", class: "pestana", id: idPestana, "aria-controls": idPanel,
        "aria-selected": String(i === 0), tabindex: i === 0 ? "0" : "-1", text: def.titulo,
      });
      const vista = registrarVista({ visible: () => !panel.hidden, cargar: () => {} });
      def.montar(panel, portal, vista);
      tablist.append(boton);
      contenedor.append(panel);
      return { boton, panel };
    });

    function seleccionar(indice, enfocar) {
      pestanas.forEach(({ boton, panel }, i) => {
        boton.setAttribute("aria-selected", String(i === indice));
        boton.tabIndex = i === indice ? 0 : -1;
        panel.hidden = i !== indice;
      });
      if (enfocar) pestanas[indice].boton.focus();
      refrescarVisibles();
    }

    pestanas.forEach(({ boton }, i) => {
      boton.addEventListener("click", () => seleccionar(i, false));
      // Teclado de pestañas (WAI-ARIA): flechas, Inicio y Fin.
      boton.addEventListener("keydown", (ev) => {
        const ultimo = pestanas.length - 1;
        const destino = { ArrowRight: i === ultimo ? 0 : i + 1, ArrowLeft: i === 0 ? ultimo : i - 1, Home: 0, End: ultimo }[ev.key];
        if (destino === undefined) return;
        ev.preventDefault();
        seleccionar(destino, true);
      });
    });
  }

  // Busca el portal del slug en /api/estadisticas/portales (trae todos los portales conocidos, con su slug).
  let portalMontado = false;
  async function resolverPortal() {
    $("portal-carga").hidden = false;
    $("portal-error").hidden = true;
    let r;
    try {
      r = await datosPortales();
    } catch (e) {
      $("portal-carga").hidden = true;
      $("portal-error-texto").textContent = e.message || "No se pudieron cargar los datos.";
      $("portal-error").hidden = false;
      avisarError(e);
      return;
    }
    $("portal-carga").hidden = true;
    const p = r.portales.find((x) => x.slug === SLUG);
    if (!p) {
      $("form-rango").hidden = true;
      $("portal-no-encontrado").hidden = false;
      $("titulo-portal").textContent = "Portal no encontrado";
      document.title = "Portal no encontrado · Estadísticas | MiraGroup";
      return;
    }
    $("titulo-portal").textContent = `Portal ${p.portal}`;
    document.title = `Portal ${p.portal} · Estadísticas | MiraGroup`;
    if (!portalMontado) {
      portalMontado = true;
      montarPortal(p.portal);
    }
    $("portal-cuerpo").hidden = false;
    refrescarVisibles();
  }

  // -------------------------------------------------------------------------
  // Eventos e inicio
  // -------------------------------------------------------------------------

  $("form-rango").addEventListener("submit", (ev) => {
    ev.preventDefault();
    aplicarRango();
  });

  fijarRangoInicial();
  if (VISTA === "general") {
    montarTablaGeneral();
    montarGraficosGeneral();
    aplicarRango();
  } else if (VISTA === "portal") {
    $("portal-reintentar").addEventListener("click", resolverPortal);
    aplicarRango();
    resolverPortal();
  }
})();
