/* Utilidades comunes de todas las páginas salvo /contactos (JavaScript sin librerías): API, avisos, modales,
   botón para mostrar u ocultar contraseñas, encabezado, formatos de fecha y duración, y descarga de CSV.
   En /login no hay encabezado: esas partes se saltan si sus elementos no existen. */
"use strict";

window.Mira = (() => {
  const $ = (id) => document.getElementById(id);

  // -------------------------------------------------------------------------
  // Cliente de la API
  // -------------------------------------------------------------------------

  class ErrorApi extends Error {
    constructor(status, detail, errores, datos) {
      super(detail);
      this.status = status;
      this.errores = errores || {};
      this.datos = datos || {};
    }
  }

  // Devuelve la respuesta si salió bien. Si no, lanza ErrorApi con el `detail` de la API.
  async function solicitar(method, url, body) {
    const opciones = {
      method,
      credentials: "same-origin",
      headers: { "Accept": "application/json", "X-Requested-With": "mira-admin" },
    };
    if (method !== "GET") {
      opciones.headers["Content-Type"] = "application/json";
      opciones.body = JSON.stringify(body || {});
    }

    let resp;
    try {
      resp = await fetch(url, opciones);
    } catch (e) {
      throw new ErrorApi(0, "No se pudo conectar con el servidor. Revisa tu conexión e intenta nuevamente.");
    }
    if (resp.ok) return resp;

    let datos = null;
    try { datos = await resp.json(); } catch (e) { datos = null; }
    const detail = (datos && typeof datos.detail === "string") ? datos.detail : "Ocurrió un error inesperado.";

    if (resp.status === 401) {
      mostrarBloqueo();
    } else if (resp.status === 403 && datos && datos.cambioRequerido) {
      // Entró con la contraseña por defecto: primero debe cambiarla.
      window.location.href = "/cambiar-contrasena";
    }
    throw new ErrorApi(resp.status, detail, datos && datos.errores, datos);
  }

  async function api(method, url, body) {
    const resp = await solicitar(method, url, body);
    try { return await resp.json(); } catch (e) { return null; }
  }

  // -------------------------------------------------------------------------
  // Utilidades de interfaz
  // -------------------------------------------------------------------------

  function el(tag, opciones, hijos) {
    const nodo = document.createElement(tag);
    if (opciones) {
      for (const [clave, valor] of Object.entries(opciones)) {
        if (valor === undefined || valor === null || valor === false) continue;
        if (clave === "class") nodo.className = valor;
        else if (clave === "text") nodo.textContent = valor;
        else if (clave === "dataset") Object.assign(nodo.dataset, valor);
        else nodo.setAttribute(clave, valor === true ? "" : valor);
      }
    }
    for (const hijo of [].concat(hijos || [])) {
      if (hijo !== null && hijo !== undefined) nodo.append(hijo);
    }
    return nodo;
  }

  function setOcupado(boton, ocupado, textoOcupado) {
    if (ocupado) {
      if (!boton.dataset.textoOriginal) boton.dataset.textoOriginal = boton.textContent;
      boton.disabled = true;
      boton.setAttribute("aria-busy", "true");
      boton.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), document.createTextNode(textoOcupado || boton.dataset.textoOriginal));
    } else {
      boton.disabled = false;
      boton.removeAttribute("aria-busy");
      if (boton.dataset.textoOriginal) boton.textContent = boton.dataset.textoOriginal;
      delete boton.dataset.textoOriginal;
    }
  }

  function toast(tipo, mensaje) {
    const cerrar = el("button", { type: "button", "aria-label": "Cerrar aviso", text: "×" });
    const nodo = el("div", { class: `toast toast-${tipo}`, role: tipo === "exito" ? "status" : "alert" }, [
      el("p", { text: mensaje }),
      cerrar,
    ]);
    const quitar = () => nodo.remove();
    cerrar.addEventListener("click", quitar);
    $("toasts").append(nodo);
    setTimeout(quitar, tipo === "exito" ? 6000 : 10000);
  }

  // Sesión vencida o administrador desactivado: se tapa la página y se ofrece volver a ingresar.
  function mostrarBloqueo() {
    const bloqueo = $("bloqueo");
    if (!bloqueo || !bloqueo.hidden) return;
    if (modalActivo) cerrarModal(true);
    document.querySelector(".encabezado").inert = true;
    $("contenido").inert = true;
    bloqueo.hidden = false;
    $("bloqueo-link").focus();
  }

  // -------------------------------------------------------------------------
  // Modales (Esc para cerrar, foco atrapado, foco devuelto al cerrar)
  // -------------------------------------------------------------------------

  let modalActivo = null;
  let focoPrevio = null;
  let alCerrar = null;

  function focables(contenedor) {
    return Array.from(contenedor.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((n) => n.offsetParent !== null);
  }

  // `cerrado` se llama cada vez que el modal se cierra (Esc, fondo, «Cancelar» o cerrarModal).
  function abrirModal(modal, focoInicial, cerrado) {
    if (modalActivo && modalActivo !== modal) cerrarModal(true);
    if (!modalActivo) focoPrevio = document.activeElement;
    modal.hidden = false;
    modalActivo = modal;
    alCerrar = cerrado || null;
    prepararOjos(modal);
    ocultarClaves(modal);
    document.body.classList.add("modal-abierto");
    document.querySelector(".encabezado").inert = true;
    $("contenido").inert = true;
    (focoInicial || focables(modal)[0] || modal).focus();
  }

  function cerrarModal(forzar) {
    if (!modalActivo) return;
    if (!forzar && modalActivo.dataset.ocupado === "1") return;
    modalActivo.hidden = true;
    modalActivo.dataset.ocupado = "";
    ocultarClaves(modalActivo);
    modalActivo = null;
    document.body.classList.remove("modal-abierto");
    document.querySelector(".encabezado").inert = false;
    $("contenido").inert = false;
    if (focoPrevio && document.contains(focoPrevio) && !focoPrevio.disabled) focoPrevio.focus();
    focoPrevio = null;
    const avisar = alCerrar;
    alCerrar = null;
    if (avisar) avisar();
  }

  document.addEventListener("keydown", (ev) => {
    if (!modalActivo) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      cerrarModal(false);
      return;
    }
    if (ev.key === "Tab") {
      const lista = focables(modalActivo);
      if (lista.length === 0) { ev.preventDefault(); return; }
      const primero = lista[0];
      const ultimo = lista[lista.length - 1];
      if (ev.shiftKey && (document.activeElement === primero || !modalActivo.contains(document.activeElement))) {
        ev.preventDefault();
        ultimo.focus();
      } else if (!ev.shiftKey && (document.activeElement === ultimo || !modalActivo.contains(document.activeElement))) {
        ev.preventDefault();
        primero.focus();
      }
    }
  });

  for (const fondo of document.querySelectorAll(".modal-fondo")) {
    fondo.addEventListener("click", (ev) => {
      if (ev.target === fondo || ev.target.closest("[data-cerrar]")) cerrarModal(false);
    });
  }

  // -------------------------------------------------------------------------
  // Formatos: días locales del navegador → UTC para la API, fechas y duraciones
  // -------------------------------------------------------------------------

  const numero = new Intl.NumberFormat("es");
  const dos = (n) => String(n).padStart(2, "0");

  function textoDia(fecha) {
    return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
  }

  // Medianoche local del día AAAA-MM-DD, más `sumarDias`.
  function inicioDiaLocal(valor, sumarDias) {
    const [a, m, d] = valor.split("-").map(Number);
    return new Date(a, m - 1, d + (sumarDias || 0));
  }

  // Agrega `desde`/`hasta` (días locales AAAA-MM-DD) a `params`.
  // «Hasta» incluye el día completo: se envía el día siguiente a las 00:00 locales (exclusivo).
  function agregarRango(params, desde, hasta) {
    if (desde) params.set("desde", inicioDiaLocal(desde).toISOString());
    if (hasta) params.set("hasta", inicioDiaLocal(hasta, 1).toISOString());
    return params;
  }

  // Minutos que hay que sumar a UTC para llegar a la hora local (para agrupar días y para los CSV).
  const tzOffsetMin = () => String(-new Date().getTimezoneOffset());

  function fechaLocal(iso) {
    if (!iso) return "—";
    const f = new Date(iso);
    return `${dos(f.getDate())}/${dos(f.getMonth() + 1)}/${f.getFullYear()} ${dos(f.getHours())}:${dos(f.getMinutes())}`;
  }

  // Duración en segundos → «< 1 min», «44 min» o «52 h 10 min» (minutos truncados).
  function duracion(segundos) {
    if (segundos === null || segundos === undefined) return "—";
    if (segundos < 60) return "< 1 min";
    const minutos = Math.floor(segundos / 60);
    if (minutos < 60) return `${minutos} min`;
    return `${numero.format(Math.floor(minutos / 60))} h ${dos(minutos % 60)} min`;
  }

  // Cómo terminó la sesión (los mismos textos que la columna «Cierre» del CSV).
  function textoCierre(a) {
    if (a.CierreExplicito) return "Botón";
    if (a.EnCurso) return "En curso";
    return a.FinalSesion ? "Inactividad" : "—";
  }

  // -------------------------------------------------------------------------
  // Exportar a Excel: el CSV se baja con fetch + blob, así 401/422 se muestran en la página
  // -------------------------------------------------------------------------

  // Devuelve el tope de filas si la API truncó el archivo, o null.
  async function descargarCsv(url, nombrePorDefecto) {
    const resp = await solicitar("GET", url);
    const blob = await resp.blob();
    const m = /filename="([^"]+)"/.exec(resp.headers.get("Content-Disposition") || "");
    const enlaceUrl = URL.createObjectURL(blob);
    const enlace = el("a", { href: enlaceUrl, download: m ? m[1] : nombrePorDefecto, hidden: true });
    document.body.append(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(enlaceUrl), 1000);
    return resp.headers.get("X-Historial-Truncado");
  }

  // -------------------------------------------------------------------------
  // Política de contraseñas (las mismas reglas que app/claves.py; la API vuelve a validar)
  // -------------------------------------------------------------------------

  const CONTRASENA_POR_DEFECTO = "Admin@123456";
  const REGLAS_CONTRASENA = [
    ["largo", "La contraseña debe tener al menos 10 caracteres.", (c) => c.length >= 10],
    ["mayuscula", "La contraseña debe tener al menos una mayúscula.", (c) => /[A-ZÁÉÍÓÚÑÜ]/.test(c)],
    ["minuscula", "La contraseña debe tener al menos una minúscula.", (c) => /[a-záéíóúñü]/.test(c)],
    ["numero", "La contraseña debe tener al menos un número.", (c) => /[0-9]/.test(c)],
    ["simbolo", "La contraseña debe tener al menos un símbolo.", (c) => /[^A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü\s]/.test(c)],
  ];

  // Mensaje de la primera regla que no cumple, o "" si está bien. `actual` es opcional.
  function errorContrasena(nueva, actual) {
    if (nueva.length > 128) return "La contraseña no puede superar 128 caracteres.";
    const falla = REGLAS_CONTRASENA.find(([, , cumple]) => !cumple(nueva));
    if (falla) return falla[1];
    if (nueva === CONTRASENA_POR_DEFECTO) return "No puedes usar la contraseña por defecto.";
    if (actual && nueva === actual) return "La contraseña nueva debe ser distinta de la actual.";
    return "";
  }

  // Marca en la lista <ul> de requisitos (li[data-regla]) cuáles ya se cumplen.
  function marcarReglas(lista, nueva, actual) {
    for (const [nombre, , cumple] of REGLAS_CONTRASENA) {
      const li = lista.querySelector(`[data-regla="${nombre}"]`);
      if (li) li.classList.toggle("cumple", cumple(nueva));
    }
    const distinta = lista.querySelector('[data-regla="distinta"]');
    if (distinta) distinta.classList.toggle("cumple", nueva !== "" && nueva !== CONTRASENA_POR_DEFECTO && nueva !== actual);
  }

  // -------------------------------------------------------------------------
  // Mostrar u ocultar contraseñas: un botón con ojo dentro de cada input[type="password"]
  // -------------------------------------------------------------------------

  const SVG_NS = "http://www.w3.org/2000/svg";

  function iconoOjo() {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const trazos = [
      ["path", { d: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" }],
      ["circle", { cx: "12", cy: "12", r: "3" }],
      ["path", { d: "M4 4l16 16", class: "ojo-tachado" }],  // visible solo con la contraseña a la vista
    ];
    for (const [tag, atributos] of trazos) {
      const nodo = document.createElementNS(SVG_NS, tag);
      for (const [clave, valor] of Object.entries(atributos)) nodo.setAttribute(clave, valor);
      svg.append(nodo);
    }
    return svg;
  }

  function mostrarClave(input, boton, visible) {
    input.type = visible ? "text" : "password";
    boton.setAttribute("aria-pressed", String(visible));
    boton.setAttribute("aria-label", visible ? "Ocultar contraseña" : "Mostrar contraseña");
    boton.title = visible ? "Ocultar contraseña" : "Mostrar contraseña";
  }

  // Agrega el botón a cada contraseña dentro de `raiz` que todavía no lo tenga (se puede llamar varias veces).
  function prepararOjos(raiz) {
    for (const input of (raiz || document).querySelectorAll('input[type="password"]:not([data-ojo])')) {
      input.dataset.ojo = "1";
      const envoltura = el("span", { class: "campo-clave" });
      const boton = el("button", { type: "button", class: "btn-ojo" }, iconoOjo());
      mostrarClave(input, boton, false);
      input.replaceWith(envoltura);
      envoltura.append(input, boton);
      // Con el mouse, el foco no sale del campo; con teclado (Enter o Espacio) vuelve a él.
      boton.addEventListener("mousedown", (ev) => ev.preventDefault());
      boton.addEventListener("click", () => {
        const inicio = input.selectionStart;
        const fin = input.selectionEnd;
        mostrarClave(input, boton, input.type === "password");
        input.focus();
        if (inicio !== null && fin !== null) input.setSelectionRange(inicio, fin);
      });
    }
  }

  // Vuelve a ocultar las contraseñas de `raiz` (al enviar un formulario o cerrar un modal).
  function ocultarClaves(raiz) {
    for (const input of (raiz || document).querySelectorAll("input[data-ojo]")) {
      const boton = input.parentElement.querySelector(".btn-ojo");
      if (boton) mostrarClave(input, boton, false);
    }
  }

  // Fase de captura: se ocultan antes de que corra el manejador del formulario.
  document.addEventListener("submit", (ev) => ocultarClaves(ev.target), true);
  prepararOjos(document);

  // -------------------------------------------------------------------------
  // Encabezado: administrador conectado y cierre de sesión
  // -------------------------------------------------------------------------

  if ($("btn-logout")) $("btn-logout").addEventListener("click", async (ev) => {
    setOcupado(ev.currentTarget, true, "Cerrando…");
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "mira-admin" },
        body: "{}",
      });
    } catch (e) {
      // Aunque falle la red, se vuelve al ingreso.
    }
    window.location.href = "/login";
  });

  // Promesa con el administrador conectado ({id, nombre, correo, debeCambiarContrasena}) o null.
  const sesion = !$("admin-nombre") ? Promise.resolve(null) : (async () => {
    try {
      const me = await api("GET", "/api/me");
      $("admin-nombre").textContent = me.nombre;
      $("admin-nombre").title = me.correo;
      return me;
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast("error", e.message);
      return null;
    }
  })();

  return {
    $, el, api, solicitar, setOcupado, toast, ErrorApi, abrirModal, cerrarModal, sesion, errorContrasena, marcarReglas,
    prepararOjos, ocultarClaves,
    numero, dos, textoDia, inicioDiaLocal, agregarRango, tzOffsetMin, fechaLocal, duracion, textoCierre, descargarCsv,
  };
})();
