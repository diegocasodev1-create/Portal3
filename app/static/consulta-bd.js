/* v19: «Consulta de base de datos» (solo lectura). Una tabla de la lista cerrada, sus últimos 500 registros
   y un buscador «contiene» sobre las columnas de SKU, correo y ticket JIRA de esa tabla (búsqueda en la base,
   no en lo visible). Todo se arma con textContent: los datos pueden traer cualquier texto (JSON, HTML…). */
(() => {
  "use strict";
  const { $, el, api, ErrorApi, dos } = Mira;

  const CLAVE_TABLA = "mira.consultaBd.tabla";
  const NUMERICOS = new Set(["entero", "decimal"]);
  const LARGO_TITULO = 40;   // textos más largos llevan title (la celda los corta con «…»)
  const numero = new Intl.NumberFormat("es-PE");

  let tablas = [];           // [{clave, nombre, camposBusqueda}]
  let buscado = "";          // texto aplicado (con «Buscar» o Enter)
  let pedido = 0;            // descarta respuestas de pedidos anteriores

  const leerGuardada = () => {
    try { return sessionStorage.getItem(CLAVE_TABLA) || ""; } catch (e) { return ""; }
  };
  const guardar = (clave) => {
    try { sessionStorage.setItem(CLAVE_TABLA, clave); } catch (e) { /* sin almacenamiento: no pasa nada */ }
  };

  const tablaElegida = () => tablas.find((t) => t.clave === $("c-tabla").value) || null;

  function mostrar(estado) {
    $("estado-carga").hidden = estado !== "carga";
    $("estado-vacio").hidden = estado !== "vacio";
    $("estado-error").hidden = estado !== "error";
    $("envoltura").hidden = estado !== "tabla";
  }

  function mostrarError(mensaje, reintentar) {
    $("texto-error").textContent = mensaje;
    $("btn-reintentar").hidden = !reintentar;
    $("resumen").textContent = "";
    mostrar("error");
  }

  function errorTexto(mensaje) {
    $("e-texto").textContent = mensaje || "";
    if (mensaje) $("c-texto").setAttribute("aria-invalid", "true");
    else $("c-texto").removeAttribute("aria-invalid");
  }

  // El buscador solo aparece si la tabla tiene columnas para buscar; la etiqueta nombra esas columnas.
  function prepararBuscador(tabla) {
    const campos = tabla ? tabla.camposBusqueda : [];
    const conBuscador = campos.length > 0;
    $("c-buscador").hidden = !conBuscador;
    $("c-acciones").hidden = !conBuscador;
    $("c-etiqueta").textContent = conBuscador ? `Buscar en: ${campos.join(", ")}` : "Buscar";
    $("c-texto").value = "";
    buscado = "";
    errorTexto("");
  }

  // ---------------------------------------------------------------------------
  // Formato de cada tipo
  // ---------------------------------------------------------------------------

  function fechaHoraLocal(iso) {
    const f = new Date(iso);
    if (Number.isNaN(f.getTime())) return iso;
    return `${dos(f.getDate())}/${dos(f.getMonth() + 1)}/${f.getFullYear()} ${dos(f.getHours())}:${dos(f.getMinutes())}:${dos(f.getSeconds())}`;
  }

  // Solo fecha (sin hora): no se convierte de zona.
  function fechaSola(texto) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto);
    return m ? `${m[3]}/${m[2]}/${m[1]}` : texto;
  }

  function celda(tipo, valor, columna) {
    if (valor === null || valor === undefined) {
      return el("td", { class: "celda-nula", "data-label": columna }, [
        el("span", { "aria-hidden": "true", text: "—" }),
        el("span", { class: "sr-only", text: "vacío" }),
      ]);
    }
    let texto;
    let clase = "";
    if (tipo === "fechaHora") texto = fechaHoraLocal(valor);
    else if (tipo === "fecha") texto = fechaSola(valor);
    else if (tipo === "bit") texto = valor ? "Sí" : "No";
    else texto = String(valor);
    if (NUMERICOS.has(tipo)) clase = "celda-num";
    else if (tipo === "texto" || tipo === "textoLargo") clase = "celda-texto";
    return el("td", {
      class: clase || undefined,
      "data-label": columna,
      title: clase === "celda-texto" && texto.length > LARGO_TITULO ? texto : undefined,
      text: texto,
    });
  }

  function dibujarTabla(datos) {
    const encabezado = $("tabla-encabezado");
    encabezado.replaceChildren(...datos.columnas.map((c) => el("th", {
      scope: "col",
      class: NUMERICOS.has(c.tipo) ? "celda-num" : undefined,
      title: c.tipo === "fechaHora" ? "Hora local" : undefined,
      text: c.nombre,
    })));
    const cuerpo = document.createDocumentFragment();
    for (const fila of datos.filas) {
      cuerpo.append(el("tr", null, fila.map((v, i) => celda(datos.columnas[i].tipo, v, datos.columnas[i].nombre))));
    }
    $("tabla-cuerpo").replaceChildren(cuerpo);
    $("envoltura").scrollTop = 0;
    $("envoltura").scrollLeft = 0;
  }

  function textoResumen(datos) {
    const n = numero.format(datos.mostrando);
    if (datos.busqueda) {
      const extra = datos.total > datos.mostrando ? ` (se muestran las primeras ${numero.format(datos.tope)})` : "";
      return `Mostrando ${n} de ${numero.format(datos.total)} coincidencias con «${datos.busqueda}»${extra} · ${numero.format(datos.totalTabla)} registros en la tabla`;
    }
    const extra = datos.total > datos.mostrando ? " (los más recientes)" : "";
    return `Mostrando ${n} de ${numero.format(datos.total)} registros${extra}`;
  }

  // ---------------------------------------------------------------------------
  // Carga
  // ---------------------------------------------------------------------------

  async function cargar() {
    const tabla = tablaElegida();
    if (!tabla) return;
    const mio = ++pedido;
    $("titulo-tabla").textContent = tabla.nombre;
    $("resumen").textContent = "";
    errorTexto("");
    mostrar("carga");
    const params = new URLSearchParams({ tabla: tabla.clave });
    if (buscado) params.set("q", buscado);
    try {
      const datos = await api("GET", `/api/consulta-bd/filas?${params}`);
      if (mio !== pedido) return;
      $("resumen").textContent = textoResumen(datos);
      if (!datos.filas.length) {
        $("texto-vacio").textContent = datos.busqueda
          ? "Sin registros que coincidan con la búsqueda."
          : "La tabla no tiene registros.";
        mostrar("vacio");
        return;
      }
      dibujarTabla(datos);
      mostrar("tabla");
    } catch (e) {
      if (mio !== pedido) return;
      if (e instanceof ErrorApi && e.status === 401) return;   // comun.js ya muestra «Tu sesión venció»
      if (e instanceof ErrorApi && e.status === 422 && e.errores.q) {
        errorTexto(e.errores.q);
        mostrar(null);
        $("c-texto").focus();
        return;
      }
      mostrarError(e.message || "No se pudieron cargar los registros.", true);
    }
  }

  async function iniciar() {
    const select = $("c-tabla");
    let datos;
    try {
      datos = await api("GET", "/api/consulta-bd/tablas");
    } catch (e) {
      if (e instanceof ErrorApi && e.status === 401) return;
      select.replaceChildren(el("option", { value: "", text: "No se pudieron cargar las tablas" }));
      mostrarError(e.message || "No se pudieron cargar las tablas.", false);
      return;
    }
    tablas = datos.tablas;
    select.replaceChildren(
      el("option", { value: "", text: "Elige una tabla…" }),
      ...tablas.map((t) => el("option", { value: t.clave, text: t.nombre })),
    );
    select.disabled = false;
    const guardada = leerGuardada();
    if (tablas.some((t) => t.clave === guardada)) {
      select.value = guardada;
      prepararBuscador(tablaElegida());
      cargar();
    }
  }

  $("c-tabla").addEventListener("change", () => {
    const tabla = tablaElegida();
    prepararBuscador(tabla);
    if (!tabla) {
      pedido++;
      $("titulo-tabla").textContent = "Elige una tabla";
      $("resumen").textContent = "";
      mostrar(null);
      return;
    }
    guardar(tabla.clave);
    cargar();
  });

  $("form-consulta").addEventListener("submit", (ev) => {
    ev.preventDefault();
    if ($("c-buscador").hidden) return;
    buscado = $("c-texto").value.trim();
    cargar();
  });

  $("btn-limpiar").addEventListener("click", () => {
    $("c-texto").value = "";
    if (!buscado) { errorTexto(""); $("c-texto").focus(); return; }
    buscado = "";
    cargar();
    $("c-texto").focus();
  });

  $("btn-reintentar").addEventListener("click", cargar);

  iniciar();
})();
