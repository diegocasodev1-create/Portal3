/* Logs control de ingresos – lógica de la página (JavaScript sin librerías). */
"use strict";

(() => {
  const {
    $, el, api, setOcupado, toast,
    numero, textoDia, inicioDiaLocal, agregarRango, tzOffsetMin, fechaLocal, duracion, textoCierre, textoTiempo, textoFinal, descargarCsv,
  } = window.Mira;

  const DIAS_POR_DEFECTO = 7;
  const MAX_DIAS_CON_CEROS = 92; // en rangos más largos el gráfico muestra solo los días con accesos

  const estado = {
    params: null, // URLSearchParams de los filtros aplicados (sin página)
    rango: null,  // { desde, hasta } en texto AAAA-MM-DD (días locales) o null
    pagina: 1,
    paginas: 1,
    pedidoTabla: 0,   // descarta respuestas viejas si el usuario cambia de página rápido
    pedidoResumen: 0,
  };

  // -------------------------------------------------------------------------
  // Días del gráfico (los formatos comunes están en comun.js)
  // -------------------------------------------------------------------------

  function diaCorto(valor) {
    const [, m, d] = valor.split("-");
    return `${d}/${m}`;
  }

  function diaLargo(valor) {
    const [a, m, d] = valor.split("-");
    return `${d}/${m}/${a}`;
  }

  // -------------------------------------------------------------------------
  // Filtros
  // -------------------------------------------------------------------------

  function fijarUltimosDias() {
    const hoy = new Date();
    $("h-hasta").value = textoDia(hoy);
    $("h-desde").value = textoDia(new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - (DIAS_POR_DEFECTO - 1)));
  }

  function marcarErrorFechas(mensaje) {
    $("e-fechas").textContent = mensaje || "";
    for (const id of ["h-desde", "h-hasta"]) {
      if (mensaje) $(id).setAttribute("aria-invalid", "true");
      else $(id).removeAttribute("aria-invalid");
    }
  }

  // Lee el formulario. Devuelve null (y muestra el error) si las fechas no son válidas.
  function leerFiltros() {
    const desde = $("h-desde").value;
    const hasta = $("h-hasta").value;
    if (desde && hasta && desde > hasta) {
      marcarErrorFechas("La fecha «desde» no puede ser posterior a «hasta».");
      return null;
    }
    marcarErrorFechas("");

    const params = new URLSearchParams();
    const correo = $("h-correo").value.trim();
    if (correo) params.set("correo", correo);
    if ($("h-portal").value) params.set("portal", $("h-portal").value);
    if ($("h-resultado").value) params.set("resultado", $("h-resultado").value);
    agregarRango(params, desde, hasta);
    return { params, rango: { desde, hasta } };
  }

  function aplicarFiltros() {
    const filtros = leerFiltros();
    if (!filtros) return;
    estado.params = filtros.params;
    estado.rango = filtros.rango;
    estado.pagina = 1;
    cargarResumen();
    cargarTabla();
  }

  function mostrarErroresApi(e) {
    // 422 de fechas: se muestra junto a los campos; el resto como aviso.
    const errores = e.errores || {};
    if (errores.desde || errores.hasta) marcarErrorFechas(errores.desde || errores.hasta);
    else toast("error", e.message);
  }

  // -------------------------------------------------------------------------
  // Indicadores y gráfico
  // -------------------------------------------------------------------------

  function limpiarIndicadores() {
    const ids = ["i-total", "i-unicos", "i-energia", "i-mirastock", "i-denegados",
      "i-promedio", "i-tiempo-energia", "i-tiempo-mirastock", "i-en-curso", "i-cerradas-boton"];
    for (const id of ids) $(id).textContent = "—";
    $("grafico").replaceChildren();
    $("grafico").setAttribute("aria-label", "Sin datos");
    $("grafico-vacio").hidden = true;
  }

  async function cargarResumen() {
    const pedido = ++estado.pedidoResumen;
    const params = new URLSearchParams(estado.params);
    params.set("tz_offset_min", tzOffsetMin());
    let r;
    try {
      r = await api("GET", `/api/historial/resumen?${params}`);
    } catch (e) {
      if (pedido !== estado.pedidoResumen) return;
      limpiarIndicadores();
      if (e.status === 401 || e.status === 403) return;
      if (e.status === 422) mostrarErroresApi(e);
      else toast("error", e.message);
      return;
    }
    if (pedido !== estado.pedidoResumen) return;
    $("i-total").textContent = numero.format(r.total);
    $("i-unicos").textContent = numero.format(r.usuariosUnicos);
    $("i-energia").textContent = numero.format(r.porPortal["Energía"] || 0);
    $("i-mirastock").textContent = numero.format(r.porPortal.MiraStock || 0);
    $("i-denegados").textContent = numero.format(r.denegados);
    $("i-promedio").textContent = duracion(r.tiempoPromedioSeg);
    $("i-tiempo-energia").textContent = duracion(r.tiempoTotalSeg["Energía"] || 0);
    $("i-tiempo-mirastock").textContent = duracion(r.tiempoTotalSeg.MiraStock || 0);
    $("i-en-curso").textContent = numero.format(r.enCurso);
    $("i-cerradas-boton").textContent = numero.format(r.cerradasBoton);
    dibujarGrafico(r.porDia, r.total);
  }

  // Días a mostrar: todo el rango con ceros si es razonable; si no, solo los días con accesos.
  function diasDelGrafico(porDia) {
    const conteo = new Map(porDia.map((d) => [d.dia, d.total]));
    const desde = estado.rango.desde || (porDia[0] && porDia[0].dia);
    const hasta = estado.rango.hasta || (porDia.length && porDia[porDia.length - 1].dia);
    if (!desde || !hasta) return porDia;

    const dias = [];
    for (let f = inicioDiaLocal(desde); textoDia(f) <= hasta; f = new Date(f.getFullYear(), f.getMonth(), f.getDate() + 1)) {
      if (dias.length > MAX_DIAS_CON_CEROS) return porDia;
      const dia = textoDia(f);
      dias.push({ dia, total: conteo.get(dia) || 0 });
    }
    return dias;
  }

  function dibujarGrafico(porDia, total) {
    const grafico = $("grafico");
    const dias = diasDelGrafico(porDia);
    const maximo = Math.max(1, ...dias.map((d) => d.total));
    const conEtiquetas = dias.length <= 31;

    grafico.classList.toggle("grafico-denso", !conEtiquetas);
    grafico.replaceChildren(...dias.map((d) => {
      const relleno = el("span", { class: "columna-relleno" });
      // La CSP permite asignar estilos desde JS (CSSOM); lo bloqueado es el atributo style="" en el HTML.
      relleno.style.height = `${(d.total / maximo) * 100}%`;
      return el("div", { class: "columna-dia", title: `${diaLargo(d.dia)}: ${numero.format(d.total)} accesos` }, [
        el("span", { class: "columna-valor", text: d.total ? numero.format(d.total) : "" }),
        el("span", { class: "columna-pista" }, relleno),
        conEtiquetas ? el("span", { class: "columna-dia-texto", text: diaCorto(d.dia) }) : null,
      ]);
    }));
    grafico.setAttribute("aria-label", `Accesos por día: ${numero.format(total)} en ${dias.length} días`);
    $("grafico-vacio").hidden = total > 0;
    grafico.hidden = total === 0;
  }

  // -------------------------------------------------------------------------
  // Tabla y paginación
  // -------------------------------------------------------------------------

  function mostrarEstadoTabla(cual) {
    $("estado-carga").hidden = cual !== "carga";
    $("estado-vacio").hidden = cual !== "vacio";
    $("estado-error").hidden = cual !== "error";
    $("tabla").hidden = cual !== "tabla";
    $("paginacion").hidden = cual !== "tabla" || estado.paginas <= 1;
  }

  function filaAcceso(a) {
    const ok = a.Resultado === "OK";
    return el("tr", null, [
      el("td", { "data-label": "Fecha", text: fechaLocal(a.Fecha) }),
      el("td", { "data-label": "Usuario", text: a.Usuario || "—" }),
      el("td", { class: "td-correo", "data-label": "Correo", text: a.Correo }),
      el("td", { "data-label": "Portal", text: a.Portal }),
      el("td", { "data-label": "Resultado" },
        el("span", { class: `chip ${ok ? "chip-ok" : "chip-denegado"}`, text: a.Resultado })),
      a.EnCurso
        ? el("td", { "data-label": "Final de sesión" }, el("span", { class: "chip chip-en-curso", text: "En curso" }))
        : el("td", { "data-label": "Final de sesión", text: textoFinal(a) }),
      el("td", { class: "td-tiempo", "data-label": "Tiempo de sesión", text: textoTiempo(a) }),
      el("td", { "data-label": "Cierre", text: textoCierre(a) }),
    ]);
  }

  async function cargarTabla() {
    const pedido = ++estado.pedidoTabla;
    const params = new URLSearchParams(estado.params);
    params.set("pagina", String(estado.pagina));
    $("resumen").textContent = "";
    mostrarEstadoTabla("carga");
    let r;
    try {
      r = await api("GET", `/api/historial?${params}`);
    } catch (e) {
      if (pedido !== estado.pedidoTabla) return;
      if (e.status === 401 || e.status === 403) return;
      $("texto-error").textContent = e.message;
      mostrarEstadoTabla("error");
      if (e.status === 422) mostrarErroresApi(e);
      return;
    }
    if (pedido !== estado.pedidoTabla) return;

    estado.paginas = r.paginas;
    // Si la página quedó fuera de rango (cambiaron los datos), se vuelve a la última.
    if (!r.filas.length && r.total > 0 && estado.pagina > r.paginas) {
      estado.pagina = r.paginas;
      cargarTabla();
      return;
    }
    $("tabla-cuerpo").replaceChildren(...r.filas.map(filaAcceso));
    if (r.total === 0) {
      mostrarEstadoTabla("vacio");
      return;
    }
    const desde = (r.pagina - 1) * r.tamano + 1;
    const hasta = desde + r.filas.length - 1;
    $("resumen").textContent = `${numero.format(r.total)} ${r.total === 1 ? "acceso" : "accesos"} · mostrando ${numero.format(desde)}–${numero.format(hasta)}`;
    $("texto-pagina").textContent = `Página ${numero.format(r.pagina)} de ${numero.format(r.paginas)}`;
    $("btn-anterior").disabled = r.pagina <= 1;
    $("btn-siguiente").disabled = r.pagina >= r.paginas;
    mostrarEstadoTabla("tabla");
  }

  function irAPagina(pagina) {
    if (pagina < 1 || pagina > estado.paginas || pagina === estado.pagina) return;
    estado.pagina = pagina;
    cargarTabla();
    $("tabla").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  // -------------------------------------------------------------------------
  // Exportar a Excel (CSV con los filtros del formulario, fechas en hora local)
  // -------------------------------------------------------------------------

  async function exportar(ev) {
    const filtros = leerFiltros();
    if (!filtros) return;
    const boton = ev.currentTarget;
    setOcupado(boton, true, "Exportando…");
    try {
      filtros.params.set("tz_offset_min", tzOffsetMin());
      const tope = await descargarCsv(`/api/historial/csv?${filtros.params}`, "historial_accesos.csv");
      if (tope) {
        toast("aviso", `El archivo incluye solo los ${numero.format(Number(tope))} accesos más recientes. Acota las fechas para exportar el resto.`);
      } else {
        toast("exito", "Archivo exportado.");
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      if (e.status === 422) mostrarErroresApi(e);
      else toast("error", e.message);
    } finally {
      setOcupado(boton, false);
    }
  }

  // -------------------------------------------------------------------------
  // Eventos e inicio
  // -------------------------------------------------------------------------

  $("form-filtros").addEventListener("submit", (ev) => {
    ev.preventDefault();
    aplicarFiltros();
  });
  $("h-portal").addEventListener("change", aplicarFiltros);
  $("h-resultado").addEventListener("change", aplicarFiltros);
  $("btn-exportar").addEventListener("click", exportar);
  $("btn-anterior").addEventListener("click", () => irAPagina(estado.pagina - 1));
  $("btn-siguiente").addEventListener("click", () => irAPagina(estado.pagina + 1));
  $("btn-reintentar").addEventListener("click", () => {
    cargarResumen();
    cargarTabla();
  });

  fijarUltimosDias();
  aplicarFiltros();
})();
