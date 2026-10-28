/* Utilidades comunes de Inicio e Historial (JavaScript sin librerías): API, avisos y encabezado. */
"use strict";

window.Mira = (() => {
  const PORTAL_URL = document.body.dataset.portalUrl || "/";

  const $ = (id) => document.getElementById(id);

  // -------------------------------------------------------------------------
  // Cliente de la API
  // -------------------------------------------------------------------------

  class ErrorApi extends Error {
    constructor(status, detail, errores) {
      super(detail);
      this.status = status;
      this.errores = errores || {};
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
      mostrarBloqueo("sesion");
    } else if (resp.status === 403 && /permisos/i.test(detail)) {
      mostrarBloqueo("permisos");
    }
    throw new ErrorApi(resp.status, detail, datos && datos.errores);
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

  function mostrarBloqueo(motivo) {
    const bloqueo = $("bloqueo");
    if (!bloqueo.hidden) return;
    if (motivo === "permisos") {
      $("bloqueo-titulo").textContent = "No tienes permisos de administrador";
      $("bloqueo-texto").textContent = "Tu usuario ya no tiene habilitada la Administración de usuarios.";
    } else {
      $("bloqueo-titulo").textContent = "Tu sesión venció";
      $("bloqueo-texto").textContent = "Tu sesión venció, vuelve a ingresar desde el Portal Corporativo.";
    }
    document.querySelector(".encabezado").inert = true;
    $("contenido").inert = true;
    bloqueo.hidden = false;
    $("bloqueo-link").focus();
  }

  // -------------------------------------------------------------------------
  // Encabezado: administrador conectado y cierre de sesión
  // -------------------------------------------------------------------------

  $("btn-logout").addEventListener("click", async (ev) => {
    setOcupado(ev.currentTarget, true, "Cerrando…");
    try {
      await fetch("/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "mira-admin" },
        body: "{}",
      });
    } catch (e) {
      // Aunque falle la red, se envía al usuario al portal.
    }
    window.location.href = PORTAL_URL;
  });

  async function cargarSesion() {
    try {
      const me = await api("GET", "/api/me");
      if (me.authEnabled === false) {
        // Sin inicio de sesión: se ocultan el correo del admin, «Volver al portal» y «Cerrar sesión».
        document.querySelector(".sesion").hidden = true;
      } else {
        $("admin-correo").textContent = me.correo;
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      toast("error", e.message);
    }
  }

  cargarSesion();

  return { $, el, api, solicitar, setOcupado, toast, ErrorApi };
})();
