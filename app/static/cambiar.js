/* Cambiar contraseña: obligatorio tras ingresar con la contraseña por defecto, o voluntario. */
"use strict";

(() => {
  const { $, api, setOcupado, toast, sesion, errorContrasena, marcarReglas } = window.Mira;

  const CAMPOS = ["actual", "nueva", "confirmacion"];

  function limpiarErrores() {
    for (const campo of CAMPOS) {
      $(`e-${campo}`).textContent = "";
      $(`f-${campo}`).removeAttribute("aria-invalid");
    }
    $("error-general").hidden = true;
    $("error-general").textContent = "";
  }

  function mostrarErrores(errores, mensajeGeneral) {
    let primero = null;
    for (const campo of CAMPOS) {
      if (!errores[campo]) continue;
      $(`e-${campo}`).textContent = errores[campo];
      $(`f-${campo}`).setAttribute("aria-invalid", "true");
      primero = primero || $(`f-${campo}`);
    }
    if (!primero && mensajeGeneral) {
      $("error-general").textContent = mensajeGeneral;
      $("error-general").hidden = false;
    }
    if (primero) primero.focus();
  }

  function validar(datos) {
    const errores = {};
    if (!datos.actual) errores.actual = "Ingresa tu contraseña actual.";
    const error = errorContrasena(datos.nueva, datos.actual);
    if (error) errores.nueva = error;
    if (datos.nueva !== datos.confirmacion) errores.confirmacion = "Las contraseñas no coinciden.";
    return errores;
  }

  const actualizarReglas = () => marcarReglas($("reglas"), $("f-nueva").value, $("f-actual").value);
  $("f-nueva").addEventListener("input", actualizarReglas);
  $("f-actual").addEventListener("input", actualizarReglas);

  $("form-cambio").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    limpiarErrores();
    const datos = Object.fromEntries(CAMPOS.map((c) => [c, $(`f-${c}`).value]));
    const errores = validar(datos);
    if (Object.keys(errores).length) {
      mostrarErrores(errores);
      return;
    }
    const boton = $("btn-cambiar");
    setOcupado(boton, true, "Guardando…");
    try {
      const r = await api("POST", "/api/auth/cambiar-contrasena", datos);
      toast("exito", r.mensaje);
      window.location.href = r.redirect || "/";
      return;
    } catch (e) {
      if (e.status === 401) return;
      mostrarErrores(e.errores, e.message);
    }
    setOcupado(boton, false);
  });

  sesion.then((me) => {
    if (!me) return;
    // Mientras deba cambiarla no puede ir a otras páginas: se oculta «Inicio».
    $("aviso-obligatorio").hidden = !me.debeCambiarContrasena;
    $("nav-inicio").hidden = me.debeCambiarContrasena;
    $("f-actual").focus();
  });
})();
