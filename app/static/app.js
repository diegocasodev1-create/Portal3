/* Administración de usuarios – lógica de la interfaz (JavaScript sin librerías). */
"use strict";

(() => {
  const PORTAL_URL = document.body.dataset.portalUrl || "/";
  const CORREO_RE = /^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

  const estado = {
    admin: "",        // vacío cuando AUTH_ENABLED=false (no hay usuario identificado)
    iniciado: false,  // /api/me respondió bien
    usuarios: [],
    gerencias: [],
    gerenciasCargadas: false,
    editando: null,   // usuario en edición (null = creación)
    eliminando: null, // usuario a eliminar
  };

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

  async function api(method, url, body) {
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

    let datos = null;
    try { datos = await resp.json(); } catch (e) { datos = null; }
    const detail = (datos && typeof datos.detail === "string") ? datos.detail : "Ocurrió un error inesperado.";

    if (resp.status === 401) {
      mostrarBloqueo("sesion");
      throw new ErrorApi(401, detail);
    }
    if (resp.status === 403 && /permisos/i.test(detail)) {
      mostrarBloqueo("permisos");
      throw new ErrorApi(403, detail);
    }
    if (!resp.ok) {
      throw new ErrorApi(resp.status, detail, datos && datos.errores);
    }
    return datos;
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

  function normalizarBusqueda(texto) {
    return (texto || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
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
    for (const id of ["modal-usuario", "modal-eliminar"]) $(id).hidden = true;
    modalActivo = null;
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

  function focables(contenedor) {
    return Array.from(contenedor.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((n) => n.offsetParent !== null);
  }

  function abrirModal(modal, focoInicial) {
    focoPrevio = document.activeElement;
    modal.hidden = false;
    modalActivo = modal;
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
    modalActivo = null;
    document.body.classList.remove("modal-abierto");
    document.querySelector(".encabezado").inert = false;
    $("contenido").inert = false;
    if (focoPrevio && document.contains(focoPrevio) && !focoPrevio.disabled) focoPrevio.focus();
    focoPrevio = null;
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
  // Lista de usuarios
  // -------------------------------------------------------------------------

  function mostrarEstadoLista(cual) {
    $("estado-carga").hidden = cual !== "carga";
    $("estado-error").hidden = cual !== "error";
    $("estado-vacio").hidden = cual !== "vacio";
    $("tabla").hidden = cual !== "tabla";
  }

  function chip(valor) {
    return el("span", { class: valor ? "chip chip-si" : "chip chip-no", text: valor ? "Sí" : "No" });
  }

  function celda(etiqueta, contenido, clase) {
    return el("td", { "data-label": etiqueta, class: clase }, contenido);
  }

  function filaUsuario(u) {
    const esYo = u.Correo === estado.admin;
    const nombreCompleto = `${u.Nombre} ${u.Apellido || ""}`.trim();
    const btnEditar = el("button", {
      type: "button", class: "btn btn-chico btn-secundario", text: "Editar",
      dataset: { accion: "editar", id: u.Id }, "aria-label": `Editar a ${nombreCompleto}`,
    });
    // Sin correo enviado → "Enviar correo"; ya enviado → "Reenviar correo". Ambos usan /enviar-correo.
    const textoCorreo = u.InvitacionEnviada ? "Reenviar correo" : "Enviar correo";
    const btnCorreo = el("button", {
      type: "button", class: "btn btn-chico btn-fantasma", text: textoCorreo,
      dataset: { accion: "enviar-correo", id: u.Id }, "aria-label": `${textoCorreo} a ${u.Correo}`,
    });
    const btnEliminar = el("button", {
      type: "button", class: "btn btn-chico btn-peligro", text: "Eliminar",
      dataset: { accion: "eliminar", id: u.Id },
      "aria-label": esYo ? "No puedes eliminar tu propio usuario" : `Eliminar a ${u.Correo}`,
      title: esYo ? "No puedes eliminar tu propio usuario" : null,
      disabled: esYo,
    });

    return el("tr", null, [
      celda("Correo", [document.createTextNode(u.Correo), esYo ? el("span", { class: "etiqueta-yo", text: "tú" }) : null], "td-correo"),
      celda("Nombre", u.Nombre),
      celda("Apellido", u.Apellido || "—"),
      celda("Gerencia", u.Gerencia || "—"),
      celda("Energía", chip(u.Portal1), "td-centro"),
      celda("MiraStock", chip(u.Portal2), "td-centro"),
      celda("Admin", chip(u.Portal3), "td-centro"),
      celda("Correo enviado", chip(u.InvitacionEnviada), "td-centro"),
      celda("Fecha alta", u.FechaAlta || "—"),
      celda("Acciones", el("div", { class: "acciones" }, [btnEditar, btnCorreo, btnEliminar]), "td-acciones"),
    ]);
  }

  // Actualiza solo la fila (o tarjeta en móvil) de un usuario, sin redibujar la tabla.
  function actualizarFila(usuario, filaActual) {
    const nueva = filaUsuario(usuario);
    filaActual.replaceWith(nueva);
    return nueva;
  }

  function usuariosFiltrados() {
    const texto = normalizarBusqueda($("buscar").value.trim());
    const portal = $("filtro-portal").value;
    return estado.usuarios.filter((u) => {
      if (portal && !u[portal]) return false;
      if (!texto) return true;
      return [u.Correo, u.Nombre, u.Apellido, u.Gerencia].some((v) => normalizarBusqueda(v).includes(texto));
    });
  }

  function renderLista() {
    const lista = usuariosFiltrados();
    const total = estado.usuarios.length;
    if (lista.length === 0) {
      $("texto-vacio").textContent = total === 0
        ? "Todavía no hay usuarios registrados."
        : "Ningún usuario coincide con la búsqueda o el filtro.";
      $("resumen").textContent = "";
      mostrarEstadoLista("vacio");
      return;
    }
    $("tabla-cuerpo").replaceChildren(...lista.map(filaUsuario));
    $("resumen").textContent = lista.length === total
      ? `${total} ${total === 1 ? "usuario" : "usuarios"}`
      : `Mostrando ${lista.length} de ${total} usuarios`;
    mostrarEstadoLista("tabla");
  }

  async function cargarUsuarios() {
    const botones = [$("btn-nuevo"), $("btn-reintentar")];
    botones.forEach((b) => { b.disabled = true; });
    $("resumen").textContent = "";
    mostrarEstadoLista("carga");
    try {
      estado.usuarios = await api("GET", "/api/usuarios");
      renderLista();
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      $("texto-error").textContent = e.message || "No se pudieron cargar los usuarios.";
      mostrarEstadoLista("error");
    } finally {
      botones.forEach((b) => { b.disabled = false; });
    }
  }

  async function cargarGerencias() {
    estado.gerencias = await api("GET", "/api/gerencias");
    estado.gerenciasCargadas = true;
  }

  function reemplazarUsuario(usuario) {
    const i = estado.usuarios.findIndex((u) => u.Id === usuario.Id);
    if (i >= 0) estado.usuarios[i] = usuario;
  }

  // -------------------------------------------------------------------------
  // Formulario crear / editar
  // -------------------------------------------------------------------------

  const CAMPOS_ERROR = {
    correo: { error: "e-correo", input: "f-correo" },
    nombre: { error: "e-nombre", input: "f-nombre" },
    apellido: { error: "e-apellido", input: "f-apellido" },
    gerencia: { error: "e-gerencia", input: "f-gerencia" },
    portales: { error: "e-portales", input: null },
    portal1: { error: "e-portales", input: null },
    portal2: { error: "e-portales", input: null },
    portal3: { error: "e-portales", input: null },
  };

  function limpiarErrores() {
    for (const { error, input } of Object.values(CAMPOS_ERROR)) {
      $(error).textContent = "";
      if (input) $(input).removeAttribute("aria-invalid");
    }
    document.querySelector("fieldset.portales").removeAttribute("aria-invalid");
    $("error-general").hidden = true;
    $("error-general").textContent = "";
  }

  function mostrarErrores(errores, mensajeGeneral) {
    let primerFoco = null;
    let alguno = false;
    for (const [campo, mensaje] of Object.entries(errores || {})) {
      const destino = CAMPOS_ERROR[campo];
      if (!destino) continue;
      alguno = true;
      $(destino.error).textContent = mensaje;
      if (destino.input) {
        $(destino.input).setAttribute("aria-invalid", "true");
        primerFoco = primerFoco || $(destino.input);
      } else {
        document.querySelector("fieldset.portales").setAttribute("aria-invalid", "true");
        primerFoco = primerFoco || $("f-portal1");
      }
    }
    if (!alguno && mensajeGeneral) {
      $("error-general").textContent = mensajeGeneral;
      $("error-general").hidden = false;
    }
    if (primerFoco) primerFoco.focus();
  }

  function llenarGerencias(seleccionada) {
    const select = $("f-gerencia");
    const opciones = [el("option", { value: "", text: "Selecciona una gerencia" })];
    for (const g of estado.gerencias) opciones.push(el("option", { value: g, text: g }));
    select.replaceChildren(...opciones);
    select.value = seleccionada && estado.gerencias.includes(seleccionada) ? seleccionada : "";
  }

  function leerFormulario() {
    return {
      correo: $("f-correo").value.trim().toLowerCase(),
      nombre: $("f-nombre").value.trim(),
      apellido: $("f-apellido").value.trim(),
      gerencia: $("f-gerencia").value,
      portal1: $("f-portal1").checked,
      portal2: $("f-portal2").checked,
      portal3: $("f-portal3").checked,
    };
  }

  // Mismas reglas que la API.
  function validar(datos, creando) {
    const errores = {};
    if (creando) {
      if (!datos.correo) errores.correo = "El correo es obligatorio.";
      else if (datos.correo.length > 256) errores.correo = "El correo no puede superar 256 caracteres.";
      else if (!CORREO_RE.test(datos.correo)) errores.correo = "El correo no tiene un formato válido.";
    }
    if (!datos.nombre) errores.nombre = "El nombre es obligatorio.";
    if (!datos.gerencia) errores.gerencia = "La gerencia es obligatoria.";
    else if (!estado.gerencias.includes(datos.gerencia)) errores.gerencia = "La gerencia seleccionada no es válida.";
    if (!datos.portal1 && !datos.portal2 && !datos.portal3) errores.portales = "Debes marcar al menos un portal.";
    else if (!creando && estado.editando && estado.editando.Correo === estado.admin && !datos.portal3) {
      errores.portal3 = "No puedes quitarte tu propio acceso a Administración de usuarios.";
    }
    return errores;
  }

  async function abrirFormulario(usuario, disparador) {
    if (!estado.gerenciasCargadas) {
      if (disparador) setOcupado(disparador, true, "Cargando…");
      try {
        await cargarGerencias();
      } catch (e) {
        if (e.status !== 401 && e.status !== 403) toast("error", `No se pudieron cargar las gerencias: ${e.message}`);
        return;
      } finally {
        if (disparador) setOcupado(disparador, false);
      }
    }

    estado.editando = usuario;
    const creando = !usuario;
    $("form-usuario").reset();
    limpiarErrores();
    $("modal-usuario-titulo").textContent = creando ? "Nuevo usuario" : "Editar usuario";
    $("f-correo").readOnly = !creando;
    $("f-correo").value = creando ? "" : usuario.Correo;
    $("f-nombre").value = creando ? "" : usuario.Nombre;
    $("f-apellido").value = creando ? "" : (usuario.Apellido || "");
    llenarGerencias(creando ? "" : usuario.Gerencia);
    $("f-portal1").checked = !creando && usuario.Portal1;
    $("f-portal2").checked = !creando && usuario.Portal2;
    $("f-portal3").checked = !creando && usuario.Portal3;
    $("btn-guardar").textContent = creando ? "Crear usuario" : "Guardar cambios";

    abrirModal($("modal-usuario"), creando ? $("f-correo") : $("f-nombre"));
  }

  $("form-usuario").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const creando = !estado.editando;
    const datos = leerFormulario();
    limpiarErrores();
    const errores = validar(datos, creando);
    if (Object.keys(errores).length) {
      mostrarErrores(errores);
      return;
    }

    const modal = $("modal-usuario");
    const boton = $("btn-guardar");
    modal.dataset.ocupado = "1";
    setOcupado(boton, true, "Guardando…");
    try {
      if (creando) {
        const r = await api("POST", "/api/usuarios", datos);
        estado.usuarios.unshift(r.usuario);
        cerrarModal(true);
        renderLista();
        if (r.avisoCuenta) toast("aviso", r.mensaje);
        else toast("exito", "Usuario creado. Usa «Enviar correo» para enviarle la bienvenida.");
      } else {
        const { correo, ...cambios } = datos;
        const r = await api("PUT", `/api/usuarios/${estado.editando.Id}`, cambios);
        reemplazarUsuario(r.usuario);
        cerrarModal(true);
        renderLista();
        toast(r.avisoCuenta ? "aviso" : "exito", r.mensaje);
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      modal.dataset.ocupado = "";
      mostrarErrores(e.errores, e.message);
      if (e.status === 404) {
        toast("error", e.message);
        cerrarModal(true);
        cargarUsuarios();
      }
    } finally {
      modal.dataset.ocupado = "";
      setOcupado(boton, false);
    }
  });

  // -------------------------------------------------------------------------
  // Acciones de la tabla
  // -------------------------------------------------------------------------

  async function enviarCorreo(usuario, boton) {
    setOcupado(boton, true, "Enviando…");
    try {
      const r = await api("POST", `/api/usuarios/${usuario.Id}/enviar-correo`, {});
      const actualizado = { ...usuario, InvitacionEnviada: true };
      reemplazarUsuario(actualizado);
      // Solo se redibuja esta fila: "Correo enviado" pasa a Sí y el botón a "Reenviar correo".
      if (document.contains(boton)) {
        const nueva = actualizarFila(actualizado, boton.closest("tr"));
        const nuevoBoton = nueva.querySelector('button[data-accion="enviar-correo"]');
        if (nuevoBoton) nuevoBoton.focus();
      } else {
        renderLista(); // la tabla se redibujó mientras se enviaba (búsqueda o filtro)
      }
      toast("exito", r.mensaje);
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      // La fila queda igual y el botón vuelve a habilitarse para reintentar.
      if (document.contains(boton)) setOcupado(boton, false);
      toast("error", e.message);
      if (e.status === 404) cargarUsuarios();
    }
  }

  function pedirEliminar(usuario) {
    estado.eliminando = usuario;
    $("eliminar-correo").textContent = usuario.Correo;
    abrirModal($("modal-eliminar"), $("btn-confirmar-eliminar"));
  }

  $("btn-confirmar-eliminar").addEventListener("click", async () => {
    const usuario = estado.eliminando;
    if (!usuario) return;
    const modal = $("modal-eliminar");
    const boton = $("btn-confirmar-eliminar");
    modal.dataset.ocupado = "1";
    setOcupado(boton, true, "Eliminando…");
    try {
      const r = await api("DELETE", `/api/usuarios/${usuario.Id}`, {});
      estado.usuarios = estado.usuarios.filter((u) => u.Id !== usuario.Id);
      cerrarModal(true);
      renderLista();
      toast(r.avisoCuenta ? "aviso" : "exito", r.mensaje);
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      cerrarModal(true);
      toast("error", e.message);
      if (e.status === 404) cargarUsuarios();
    } finally {
      setOcupado(boton, false);
      estado.eliminando = null;
    }
  });

  $("tabla-cuerpo").addEventListener("click", (ev) => {
    const boton = ev.target.closest("button[data-accion]");
    if (!boton || boton.disabled) return;
    const usuario = estado.usuarios.find((u) => String(u.Id) === boton.dataset.id);
    if (!usuario) return;
    if (boton.dataset.accion === "editar") abrirFormulario(usuario, boton);
    else if (boton.dataset.accion === "enviar-correo") enviarCorreo(usuario, boton);
    else if (boton.dataset.accion === "eliminar") pedirEliminar(usuario);
  });

  // -------------------------------------------------------------------------
  // Barra, sesión e inicio
  // -------------------------------------------------------------------------

  $("buscar").addEventListener("input", renderLista);
  $("filtro-portal").addEventListener("change", renderLista);
  $("btn-nuevo").addEventListener("click", (ev) => abrirFormulario(null, ev.currentTarget));
  $("btn-reintentar").addEventListener("click", () => (estado.iniciado ? cargarUsuarios() : iniciar()));

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

  async function iniciar() {
    mostrarEstadoLista("carga");
    try {
      const me = await api("GET", "/api/me");
      estado.admin = me.correo || "";
      estado.iniciado = true;
      if (me.authEnabled === false) {
        // Sin inicio de sesión: se ocultan el correo del admin, «Volver al portal» y «Cerrar sesión».
        document.querySelector(".sesion").hidden = true;
      } else {
        $("admin-correo").textContent = me.correo;
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      $("texto-error").textContent = e.message;
      mostrarEstadoLista("error");
      return;
    }
    cargarGerencias().catch(() => { /* se reintenta al abrir el formulario */ });
    await cargarUsuarios();
  }

  iniciar();
})();
