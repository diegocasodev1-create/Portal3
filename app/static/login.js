/* Ingreso de administradores (JavaScript sin librerías). */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("form-ingreso");
  const boton = $("btn-ingresar");

  function mostrarError(mensaje) {
    $("error-general").textContent = mensaje;
    $("error-general").hidden = !mensaje;
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const correo = $("f-correo").value.trim().toLowerCase();
    const contrasena = $("f-contrasena").value;
    if (!correo || !contrasena) {
      mostrarError("Ingresa tu correo y tu contraseña.");
      (correo ? $("f-contrasena") : $("f-correo")).focus();
      return;
    }
    mostrarError("");
    boton.disabled = true;
    boton.textContent = "Ingresando…";

    // `siguiente` vuelve a la página que se pidió antes de ingresar (la API solo acepta rutas internas).
    const siguiente = new URLSearchParams(window.location.search).get("siguiente");
    const url = "/api/auth/login" + (siguiente ? `?siguiente=${encodeURIComponent(siguiente)}` : "");
    try {
      const resp = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Accept": "application/json", "Content-Type": "application/json", "X-Requested-With": "mira-admin" },
        body: JSON.stringify({ correo, contrasena }),
      });
      let datos = null;
      try { datos = await resp.json(); } catch (e) { datos = null; }
      if (resp.ok && datos && datos.redirect) {
        window.location.href = datos.redirect;
        return;
      }
      mostrarError((datos && typeof datos.detail === "string") ? datos.detail : "Ocurrió un error inesperado.");
      $("f-contrasena").value = "";
      $("f-contrasena").focus();
    } catch (e) {
      mostrarError("No se pudo conectar con el servidor. Revisa tu conexión e intenta nuevamente.");
    }
    boton.disabled = false;
    boton.textContent = "Ingresar";
  });

  $("f-correo").focus();
})();
