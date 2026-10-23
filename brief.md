# Brief – App "Administración de usuarios" del Portal Externo MiraGroup

## 0. Contexto
Tengo un Portal Externo en Power Pages (https://miragroup-portal-externo.powerappsportals.com) con login de Microsoft Entra External ID. Los accesos se controlan con la tabla SQL core.UsuariosEntel en Azure SQL:
- Portal1 = Portal de Energía
- Portal2 = Portal MiraStock
- Portal3 = Administración de usuarios (esta app)

La home del portal tiene una card "Administración de usuarios" que se habilita solo si el usuario tiene Portal3 = 1. Al hacer clic, la home abrirá ESTA app. La parte de Power Pages la hago yo aparte: no la modifiques ni generes archivos de Power Pages.

## 1. Objetivo
Construir una aplicación web independiente en Python (FastAPI) con su propia URL, desplegada en Azure Container Apps, que:
- Sirva una interfaz web completa (HTML/CSS/JS estáticos, vanilla, sin frameworks ni librerías externas).
- Exponga una API para registrar, listar, editar y eliminar usuarios de core.UsuariosEntel, y reenviar el correo de acceso.
- Envíe un correo de bienvenida al registrar (Microsoft Graph).

No usa Dataverse ni invitaciones de Power Pages. El registro del portal sigue abierto: el usuario crea su cuenta en External ID la primera vez y el acceso real lo da la tabla SQL. El correo avisa y explica cómo crear la cuenta.

## 2. Entrada a la app e identidad (obligatorio)
- La home de Power Pages obtiene un token firmado del usuario conectado (POST /_services/auth/token del portal; con GET responde 404, y no requiere antiforgery) y hace un POST de formulario (navegación de página completa) a:
  POST https://<app>/auth/portal   con el campo de formulario "token"
- /auth/portal:
  1. Valida el token (JWT RS256) con la clave pública del portal: GET https://miragroup-portal-externo.powerappsportals.com/_services/auth/publickey (formato PEM). Cachéala en memoria y recárgala una vez si falla la validación. Valida firma, expiración y emisor (dominio del portal). Audiencia configurable (por defecto sin exigirla).
  2. Toma el correo del claim "email" (si no viene, "preferred_username"). Deja un log DEBUG con los NOMBRES de los claims recibidos (nunca sus valores) para confirmarlo en desarrollo.
  3. Verifica en SQL que ese correo tenga Portal3 = 1 AND Activo = 1. Si no, muestra la página "No tienes permisos de administrador" con un link al portal.
  4. Si es válido, crea una sesión propia de la app: cookie firmada (SESSION_SECRET), HttpOnly, Secure, SameSite=Lax, con expiración por inactividad (SESSION_MAX_AGE_MIN, default 60). Guarda solo el correo.
  5. Responde 303 → "/".
- Si alguien abre la app sin sesión válida, muestra "Ingresa desde el Portal Corporativo" con un botón a https://miragroup-portal-externo.powerappsportals.com
- Cada request a /api/* exige sesión válida y vuelve a verificar en SQL que Portal3 = 1 AND Activo = 1 (si le quitaron el permiso, se corta en el momento). Sin sesión: 401. Sin permiso: 403.
- Protección CSRF: los métodos POST/PUT/DELETE de /api/* exigen Content-Type application/json y el header X-Requested-With: mira-admin.
- Headers de seguridad: Content-Security-Policy restrictiva (default-src 'self'; frame-ancestors 'none'; permitir fonts.googleapis.com y fonts.gstatic.com para la fuente Exo 2), X-Content-Type-Options nosniff y Referrer-Policy no-referrer.
- No registres en logs tokens, cookies ni cuerpos de request.
- Botón "Cerrar sesión" en la app: borra la sesión y redirige al portal.

## 3. Base de datos
Servidor: sqlcopilotprd01.database.windows.net – BD: CopilotKnowledgeDB – usuario y clave por variables de entorno.

Tabla core.UsuariosEntel:
- Id INT IDENTITY (PK)
- Correo (único, case-insensitive)
- Nombre
- Apellido
- Gerencia
- Portal1 BIT
- Portal2 BIT
- Activo BIT (default 1)
- FechaAlta (con default)
- Portal3 BIT NULL
- InvitacionEnviada BIT NULL

- No tienes acceso a la BD. Dame una consulta a INFORMATION_SCHEMA.COLUMNS para que yo te pase los tipos y largos reales antes de escribir db.py.
- Trata los NULL de Portal1/2/3, Activo e InvitacionEnviada como 0.
- Consultas SIEMPRE parametrizadas (pyodbc, ODBC Driver 18).
- Correo siempre en minúsculas y sin espacios.

Gerencia es crítica: el agente MiraStock filtra stock y pedidos comparando la gerencia del usuario contra core.StockLurinERI.Gerencia. Por eso NO es texto libre: es un desplegable con
  SELECT DISTINCT Gerencia FROM core.StockLurinERI WHERE Gerencia IS NOT NULL
  UNION
  SELECT DISTINCT Gerencia FROM core.UsuariosEntel WHERE Gerencia IS NOT NULL
ordenado alfabéticamente.

## 4. API
GET    /health                       → {"status":"ok"} (público)
POST   /auth/portal                  → entrada desde el portal (sección 2)
POST   /auth/logout                  → borra la sesión
GET    /api/me                       → {"correo":"..."}
GET    /api/gerencias                → ["..."]
GET    /api/usuarios                 → lista: Id, Correo, Nombre, Apellido, Gerencia, Portal1, Portal2, Portal3, Activo, InvitacionEnviada, FechaAlta (yyyy-mm-dd); ordenada por FechaAlta desc, Id desc
POST   /api/usuarios                 body {correo, nombre, apellido, gerencia, portal1, portal2, portal3}
         - inserta con Activo=1 e InvitacionEnviada=0, y envía el correo; si el envío es exitoso, marca InvitacionEnviada=1
         - respuesta {usuario, correoEnviado: bool, mensaje}
         - si el correo ya existe: 409 "Ese correo ya está registrado."
         - si el INSERT funciona pero el correo falla, NO revertir: correoEnviado=false con el motivo
PUT    /api/usuarios/{id}            body {nombre, apellido, gerencia, portal1, portal2, portal3} (el correo NO se edita)
DELETE /api/usuarios/{id}
POST   /api/usuarios/{id}/reenviar   → reenvía el correo; si es exitoso, InvitacionEnviada=1

Validaciones (en la API y también en la UI):
- correo: formato válido, obligatorio
- nombre: obligatorio
- apellido: opcional
- gerencia: obligatoria y debe existir en /api/gerencias
- portales: al menos uno de portal1/portal2/portal3 en true, al crear y al editar
- un administrador no puede eliminarse a sí mismo ni quitarse su propio Portal3 (400 con mensaje claro)
Errores en JSON: {"detail":"mensaje en español"}.

## 5. Correo de bienvenida
- Microsoft Graph, flujo client credentials (msal), tenant MIRAGROUP e3112796-84de-4e46-a7d3-3a113c51a3bc.
- POST https://graph.microsoft.com/v1.0/users/{MAIL_SENDER}/sendMail, con saveToSentItems=false.
- Remitente: no-reply@miragroup.cl (buzón compartido; el permiso lo da TI con RBAC para aplicaciones en Exchange).
- MAIL_ENABLED=false: no envía, devuelve correoEnviado=false con el mensaje "Envío de correo deshabilitado" y no marca InvitacionEnviada. Esto permite probar todo antes de que TI habilite el buzón.
- Asunto: "Tu acceso al Portal Corporativo MiraGroup"
- Cuerpo HTML con estilos inline, compatible con Outlook y Gmail (fondo claro, acento #29b8ec, texto #0a1a33), en español neutro:
  - "Hola {Nombre},"
  - Se le dio acceso al Portal Corporativo MiraGroup, con la lista de portales habilitados (Portal de Energía / Portal MiraStock / Administración de usuarios, según lo marcado).
  - Botón "Ingresar al portal" → https://miragroup-portal-externo.powerappsportals.com
  - Pasos: 1) Haz clic en "Iniciar sesión". 2) Si es tu primera vez, elige "¿No tiene una cuenta? Cree una". 3) Regístrate con este mismo correo: {correo}. 4) Ingresa el código que te llegará por correo y define tu contraseña.
  - "Si ya tienes cuenta, solo inicia sesión."
  - Pie: "Este es un mensaje automático, no respondas a este correo."

## 6. Interfaz web (servida por la app)
- Estilo del portal: fondo #030814 / #0a1a33, acento #29b8ec, acento suave #8fdcff, texto #ffffff / #a9bcd4, fuente Exo 2 (Google Fonts) con fallback 'Segoe UI', system-ui. Cards con borde rgba(41,184,236,0.35), radio 18px y botones redondeados (pill). Aspecto sobrio y profesional.
- Encabezado: logo MiraGroup (incluye un placeholder static/logoMG.png que yo reemplazo), título "Administración de usuarios", correo del admin conectado, botón "Volver al portal" (→ URL del portal) y botón "Cerrar sesión".
- Barra: buscador (correo, nombre, apellido, gerencia), filtro por portal (Todos / Energía / MiraStock / Administración) y botón "+ Nuevo usuario".
- Tabla: Correo, Nombre, Apellido, Gerencia, Energía, MiraStock, Admin, Correo enviado, Fecha alta, Acciones. Los portales se muestran como chips sí/no. Acciones: Editar, Reenviar correo, Eliminar.
- Modal de formulario (crear y editar): Correo (solo lectura al editar), Nombre, Apellido, Gerencia (select desde /api/gerencias) y tres casillas (checkbox, NO radio): "Portal de Energía", "Portal MiraStock" y "Administración de usuarios". Se pueden marcar una, dos o las tres; al menos una es obligatoria. Errores junto a cada campo.
- Modal de confirmación para Eliminar, mostrando el correo.
- Toasts de éxito y error. Al crear: "Usuario creado y correo enviado" o "Usuario creado, pero el correo no se pudo enviar: …".
- Estados: carga (botones deshabilitados y spinner), lista vacía, error con "Reintentar". Si la API responde 401 → pantalla "Tu sesión venció, vuelve a ingresar desde el Portal Corporativo".
- Responsive: en móvil la tabla pasa a tarjetas apiladas.
- Accesible: labels, foco visible, modales cerrables con Esc y foco atrapado dentro.

## 7. Variables de entorno
SQL_SERVER, SQL_DATABASE, SQL_USER, SQL_PASSWORD,
PORTAL_BASE_URL=https://miragroup-portal-externo.powerappsportals.com,
TOKEN_AUDIENCE (opcional),
SESSION_SECRET, SESSION_MAX_AGE_MIN=60,
GRAPH_TENANT_ID=e3112796-84de-4e46-a7d3-3a113c51a3bc, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
MAIL_SENDER=no-reply@miragroup.cl, MAIL_ENABLED=false,
LOG_LEVEL=INFO
Incluye .env.example con todas, sin valores reales.

## 8. Estructura del proyecto
mira-admin-app/
  app/main.py        (FastAPI, middlewares de sesión y seguridad, rutas, archivos estáticos)
  app/config.py      (pydantic-settings)
  app/auth.py        (validación del token del portal, sesión, dependencia require_admin)
  app/db.py          (pyodbc y consultas)
  app/mailer.py      (msal + Graph sendMail + plantilla HTML)
  app/schemas.py     (modelos pydantic)
  app/static/        (index.html, styles.css, app.js, logoMG.png placeholder)
  app/templates/     (páginas simples: sin acceso, sin permisos)
  tests/             (pytest: validaciones, autorización, CSRF; mock de BD y Graph)
  requirements.txt
  Dockerfile         (python:3.12-slim + msodbcsql18; uvicorn en el puerto 8000)
  .env.example
  README.md

## 9. Despliegue en Azure Container Apps
- Suscripción CreditosCopilot1 (38b3f030-c7b5-4d38-822b-c533f88cd34a), grupo de recursos RG-COPILOT-DEV, región Central US.
- Si existe un Container Apps Environment reutilizable (hay uno de ca-script-h25-prod en rg-script-h25-prod), reutilízalo; si no, crea uno nuevo.
- Container App: ca-mira-admin, ingress externo HTTPS, puerto 8000, min réplicas 0, max 1, secrets para SQL, Graph y SESSION_SECRET.
- Imagen: Azure Container Registry existente si lo hay; si no, crea uno Basic (o usa az containerapp up --source).
- Firewall de Azure SQL: documenta cómo permitir la conexión desde el Container App.
- En el README, deja los comandos az CLI completos y en orden para que yo los ejecute, cómo ver los logs y la URL final de entrada (POST /auth/portal), que yo usaré en la home.

## 10. Forma de trabajo
- No tienes acceso a la BD ni a Azure: donde haga falta, dame las consultas o comandos para que yo los ejecute y te pase el resultado.
- Español neutro en la UI, los mensajes y los comentarios.
- Antes de escribir código, muéstrame un plan breve (archivos y pasos) y espera mi OK.
- Entrega archivos completos, nunca fragmentos.
- Al final, dame un checklist de pruebas end-to-end: entrada desde el portal, acceso sin sesión, usuario sin Portal3, crear, editar, eliminar, reenviar, regla de "al menos un portal" y protección contra eliminarse a sí mismo.