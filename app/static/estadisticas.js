/* Estadísticas del Portal Corporativo – lógica de la página (JavaScript sin librerías).

   Niveles: 1) «General por portal»; 2) un bloque por cada portal que devuelve la API, con sub-vistas en
   pestañas (SUBVISTAS). Los niveles 3 y 4 (funcionalidades y subfuncionalidades) se sumarán como otra
   entrada de SUBVISTAS, sin tocar el resto de la página. */
"use strict";

(() => {
  const {
    $, el, api, setOcupado, toast,
    numero, textoDia, agregarRango, tzOffsetMin, fechaLocal, duracion, textoCierre, textoTiempo, textoFinal, descargarCsv,
  } = window.Mira;

  const DIAS_POR_DEFECTO = 30;
  const TOTAL_PORTAL_CORPORATIVO = "Total Portal Corporativo";

  const estado = {
    rango: null,  // URLSearchParams con desde/hasta aplicados
    version: 0,   // sube con cada cambio de fechas; cada vista recuerda con qué versión cargó
  };

  // Vistas que dependen del rango: { visible(), cargar(), version }. Solo se cargan las visibles;
  // las demás se cargan al abrirse (bloque o pestaña), así no se consulta lo que nadie mira.
  const vistas = [];
  const bloques = new Map(); // portal → { meta }

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

  // -------------------------------------------------------------------------
  // Filtro de fechas común
  // -------------------------------------------------------------------------

  function fijarUltimosDias() {
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

  function textoMeta(d) {
    if (!d.sesiones) return "Sin sesiones en el período";
    const sesiones = `${numero.format(d.sesiones)} ${d.sesiones === 1 ? "sesión" : "sesiones"}`;
    return d.segundosTotales === null ? sesiones : `${sesiones} · ${duracion(d.segundosTotales)}`;
  }

  // -------------------------------------------------------------------------
  // Nivel 1: General por portal (siempre se carga: de aquí sale la lista de portales)
  // -------------------------------------------------------------------------

  (() => {
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

    function filaPortal(nombre, d) {
      return el("tr", null, [
        el("td", { "data-label": "Portal", text: nombre }),
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
        $("general-meta").textContent = "";
        let r;
        try {
          r = await api("GET", `/api/estadisticas/portales?${parametros()}`);
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
        $("general-meta").textContent = textoMeta(r.total);
        // Un portal nuevo en la vista aparece como un bloque más (cerrado: se carga al abrirlo).
        for (const p of r.portales) asegurarBloque(p.portal).meta.textContent = textoMeta(p);
        tabla.mostrar("tabla");
      },
    });
  })();

  // -------------------------------------------------------------------------
  // Nivel 2: un bloque por portal, con sub-vistas en pestañas
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

  function asegurarBloque(portal) {
    if (bloques.has(portal)) return bloques.get(portal);

    const nodo = $("tpl-portal").content.firstElementChild.cloneNode(true);
    nodo.querySelector(".bloque-nombre").textContent = `Portal ${portal}`;
    const tablist = nodo.querySelector(".pestanas");
    tablist.setAttribute("aria-label", `Vistas del portal ${portal}`);
    const contenedor = nodo.querySelector(".subvistas");

    const pestanas = SUBVISTAS.map((def, i) => {
      const idPanel = nuevoId("panel");
      const idPestana = nuevoId("pestana");
      const panel = el("div", { class: "subvista", role: "tabpanel", id: idPanel, "aria-labelledby": idPestana, tabindex: "-1", hidden: i !== 0 });
      const boton = el("button", {
        type: "button", role: "tab", class: "pestana", id: idPestana, "aria-controls": idPanel,
        "aria-selected": String(i === 0), tabindex: i === 0 ? "0" : "-1", text: def.titulo,
      });
      const vista = registrarVista({ visible: () => nodo.open && !panel.hidden, cargar: () => {} });
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
    nodo.addEventListener("toggle", refrescarVisibles);

    const bloque = { meta: nodo.querySelector(".bloque-meta") };
    bloques.set(portal, bloque);
    $("bloques-portales").append(nodo);
    return bloque;
  }

  // -------------------------------------------------------------------------
  // Eventos e inicio
  // -------------------------------------------------------------------------

  $("form-rango").addEventListener("submit", (ev) => {
    ev.preventDefault();
    aplicarRango();
  });

  fijarUltimosDias();
  aplicarRango();
})();
