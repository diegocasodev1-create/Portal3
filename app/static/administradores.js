/* Centro de administración principal: administradores en cards, verificación por contraseña y ficha. */
"use strict";

(() => {
  const { $, el, api, setOcupado, toast, abrirModal, cerrarModal, fechaLocal, errorContrasena, marcarReglas } = window.Mira;

  const CORREO_RE = /^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
  const TEXTO_ESTADO = { activo: "Activo", bloqueado: "Bloqueado", inactivo: "Inactivo" };

  const estado = {
    admins: [],
    elegido: null,     // administrador de la card elegida
    permiso: null,     // permiso de edición (solo en memoria)
    venceEn: 0,        // Date.now() en que vence el permiso
    reloj: null,
  };

  // -------------------------------------------------------------------------
  // Lista de cards
  // -------------------------------------------------------------------------

  function mostrarEstado(cual) {
    $("estado-carga").hidden = cual !== "carga";
    $("estado-error").hidden = cual !== "error";
    $("estado-vacio").hidden = cual !== "vacio";
    $("lista-admins").hidden = cual !== "lista";
  }

  function horaLocal(iso) {
    const f = new Date(iso);
    return `${String(f.getHours()).padStart(2, "0")}:${String(f.getMinutes()).padStart(2, "0")}`;
  }

  function cardAdmin(a) {
    const abrible = a.estado === "activo";
    let detalleEstado = TEXTO_ESTADO[a.estado] || a.estado;
    if (a.estado === "bloqueado" && a.bloqueadoHasta) detalleEstado += ` hasta las ${horaLocal(a.bloqueadoHasta)}`;
    const motivo = a.estado === "inactivo" ? "Inactivo: no se puede editar." : `Bloqueado por intentos fallidos. Intenta más tarde.`;

    const boton = el("button", {
      type: "button",
      class: "card card-admin",
      dataset: { id: a.id },
      disabled: !abrible,
      "aria-label": abrible ? `Editar a ${a.nombre} (${a.correo})` : `${a.nombre} (${a.correo}). ${motivo}`,
      title: abrible ? null : motivo,
    }, [
      el("span", { class: "admin-cabecera" }, [
        el("span", { class: "admin-titulo", text: a.nombre }),
        a.esYo ? el("span", { class: "etiqueta-yo", text: "tú" }) : null,
      ]),
      el("span", { class: "admin-correo-card", text: a.correo }),
      el("span", { class: "admin-dato" }, [
        el("span", { class: "admin-dato-nombre", text: "Último acceso" }),
        el("span", { text: a.ultimoAcceso ? fechaLocal(a.ultimoAcceso) : "Nunca" }),
      ]),
      el("span", { class: `chip chip-estado chip-${a.estado}`, text: detalleEstado }),
    ]);
    return el("li", null, boton);
  }

  function renderLista() {
    if (estado.admins.length === 0) {
      $("resumen").textContent = "";
      mostrarEstado("vacio");
      return;
    }
    $("lista-admins").replaceChildren(...estado.admins.map(cardAdmin));
    const n = estado.admins.length;
    $("resumen").textContent = `${n} ${n === 1 ? "administrador" : "administradores"}`;
    mostrarEstado("lista");
  }

  async function cargar() {
    mostrarEstado("carga");
    $("btn-reintentar").disabled = true;
    try {
      estado.admins = await api("GET", "/api/administradores");
      renderLista();
    } catch (e) {
      if (e.status === 401 || e.status === 403) return;
      $("texto-error").textContent = e.message || "No se pudieron cargar los administradores.";
      mostrarEstado("error");
    } finally {
      $("btn-reintentar").disabled = false;
    }
  }

  // -------------------------------------------------------------------------
  // Errores de formulario
  // -------------------------------------------------------------------------

  function limpiarErrores(campos, general) {
    for (const [campo, input] of Object.entries(campos)) {
      $(`e-${campo}`).textContent = "";
      $(input).removeAttribute("aria-invalid");
    }
    $(general).hidden = true;
    $(general).textContent = "";
  }

  function mostrarErrores(campos, general, errores, mensajeGeneral) {
    let primero = null;
    for (const [campo, mensaje] of Object.entries(errores || {})) {
      if (!campos[campo]) continue;
      $(`e-${campo}`).textContent = mensaje;
      $(campos[campo]).setAttribute("aria-invalid", "true");
      primero = primero || $(campos[campo]);
    }
    if (!primero && mensajeGeneral) {
      $(general).textContent = mensajeGeneral;
      $(general).hidden = false;
    }
    if (primero) primero.focus();
  }

  // -------------------------------------------------------------------------
  // Paso 1: contraseña del administrador elegido
  // -------------------------------------------------------------------------

  const CAMPOS_VERIFICAR = { contrasena: "v-contrasena" };

  function pedirContrasena(admin) {
    estado.elegido = admin;
    $("form-verificar").reset();
    limpiarErrores(CAMPOS_VERIFICAR, "verificar-error-general");
    $("verificar-nombre").textContent = admin.nombre;
    abrirModal($("modal-verificar"), $("v-contrasena"));
  }

  $("form-verificar").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    limpiarErrores(CAMPOS_VERIFICAR, "verificar-error-general");
    const contrasena = $("v-contrasena").value;
    if (!contrasena) {
      mostrarErrores(CAMPOS_VERIFICAR, "verificar-error-general", { contrasena: "Ingresa la contraseña." });
      return;
    }
    const modal = $("modal-verificar");
    const boton = $("btn-verificar");
    modal.dataset.ocupado = "1";
    setOcupado(boton, true, "Verificando…");
    try {
      const r = await api("POST", `/api/administradores/${estado.elegido.id}/verificar`, { contrasena });
      modal.dataset.ocupado = "";
      setOcupado(boton, false);
      abrirFicha(r);
      return;
    } catch (e) {
      if (e.status === 401 || (e.status === 403 && e.datos.cambioRequerido)) return;
      modal.dataset.ocupado = "";
      $("v-contrasena").value = "";
      mostrarErrores(CAMPOS_VERIFICAR, "verificar-error-general", e.errores, e.message);
      if (!Object.keys(e.errores).length) $("v-contrasena").focus();
      // Bloqueado, inactivo o eliminado: la lista ya no está al día.
      if (e.status === 423 || e.status === 403 || e.status === 404) cargar();
    }
    setOcupado(boton, false);
  });

  // -------------------------------------------------------------------------
  // Paso 2: ficha (el permiso dura 5 minutos)
  // -------------------------------------------------------------------------

  const CAMPOS_FICHA = {
    nombre: "a-nombre", correo: "a-correo", nuevaContrasena: "a-nueva", confirmacion: "a-confirmacion",
  };

  function olvidarPermiso() {
    estado.permiso = null;
    clearInterval(estado.reloj);
    estado.reloj = null;
    $("a-nueva").value = "";
    $("a-confirmacion").value = "";
  }

  function mostrarVencimiento() {
    const restante = Math.max(0, Math.round((estado.venceEn - Date.now()) / 1000));
    if (restante === 0) {
      cerrarModal(true);
      toast("aviso", "El permiso de edición venció. Vuelve a elegir la card para continuar.");
      return;
    }
    $("ficha-vence").textContent =
      `Puedes editar durante ${Math.floor(restante / 60)}:${String(restante % 60).padStart(2, "0")} min.`;
  }

  function abrirFicha(r) {
    estado.permiso = r.permiso;
    estado.venceEn = Date.now() + r.expiraEnSeg * 1000;
    $("form-ficha").reset();
    limpiarErrores(CAMPOS_FICHA, "ficha-error-general");
    $("ficha-titulo").textContent = `Ficha de ${r.administrador.nombre}`;
    $("a-nombre").value = r.administrador.nombre;
    $("a-correo").value = r.administrador.correo;
    marcarReglas($("reglas"), "", null);
    mostrarVencimiento();
    estado.reloj = setInterval(mostrarVencimiento, 1000);
    // Al cerrar la ficha (guardar, cancelar, Esc o vencimiento) el permiso se descarta.
    abrirModal($("modal-ficha"), $("a-nombre"), olvidarPermiso);
  }

  $("a-nueva").addEventListener("input", () => marcarReglas($("reglas"), $("a-nueva").value, null));

  function validarFicha(datos) {
    const errores = {};
    if (!datos.nombre) errores.nombre = "El nombre es obligatorio.";
    if (!datos.correo) errores.correo = "El correo es obligatorio.";
    else if (!CORREO_RE.test(datos.correo)) errores.correo = "El correo no tiene un formato válido.";
    if (datos.nuevaContrasena || datos.confirmacion) {
      const error = errorContrasena(datos.nuevaContrasena);
      if (error) errores.nuevaContrasena = error;
      if (datos.nuevaContrasena !== datos.confirmacion) errores.confirmacion = "Las contraseñas no coinciden.";
    }
    return errores;
  }

  $("form-ficha").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    limpiarErrores(CAMPOS_FICHA, "ficha-error-general");
    const datos = {
      permiso: estado.permiso,
      nombre: $("a-nombre").value.trim(),
      correo: $("a-correo").value.trim().toLowerCase(),
      nuevaContrasena: $("a-nueva").value,
      confirmacion: $("a-confirmacion").value,
    };
    const errores = validarFicha(datos);
    if (Object.keys(errores).length) {
      mostrarErrores(CAMPOS_FICHA, "ficha-error-general", errores);
      return;
    }
    const modal = $("modal-ficha");
    const boton = $("btn-guardar");
    modal.dataset.ocupado = "1";
    setOcupado(boton, true, "Guardando…");
    try {
      const r = await api("PUT", `/api/administradores/${estado.elegido.id}`, datos);
      const i = estado.admins.findIndex((a) => a.id === r.administrador.id);
      if (i >= 0) estado.admins[i] = r.administrador;
      if (r.administrador.esYo) {
        $("admin-nombre").textContent = r.administrador.nombre;
        $("admin-nombre").title = r.administrador.correo;
      }
      cerrarModal(true);
      renderLista();
      toast("exito", r.mensaje);
    } catch (e) {
      if (e.status === 401 || (e.status === 403 && e.datos.cambioRequerido)) return;
      modal.dataset.ocupado = "";
      if (e.datos.permisoVencido || e.status === 403 || e.status === 404) {
        cerrarModal(true);
        toast("aviso", e.message);
        cargar();
      } else {
        mostrarErrores(CAMPOS_FICHA, "ficha-error-general", e.errores, e.message);
      }
    } finally {
      modal.dataset.ocupado = "";
      setOcupado(boton, false);
    }
  });

  // -------------------------------------------------------------------------
  // Inicio
  // -------------------------------------------------------------------------

  $("lista-admins").addEventListener("click", (ev) => {
    const boton = ev.target.closest("button.card-admin");
    if (!boton || boton.disabled) return;
    const admin = estado.admins.find((a) => String(a.id) === boton.dataset.id);
    if (admin) pedirContrasena(admin);
  });
  $("btn-reintentar").addEventListener("click", cargar);

  cargar();
})();
