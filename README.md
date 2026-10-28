# Administración de usuarios – Portal Externo MiraGroup

App web independiente (FastAPI + HTML/CSS/JS sin librerías) para administrar la tabla
`core.UsuariosEntel` de Azure SQL, que controla el acceso al Portal Externo:

| Columna | Portal |
|---|---|
| `Portal1` | Portal de Energía |
| `Portal2` | Portal MiraStock |
| `Portal3` | Administración de usuarios (esta app) |

El correo de bienvenida (vía Microsoft Graph) **no se envía al crear el usuario**: el administrador lo envía
cuando quiere con el botón «Enviar correo» de cada fila.

La app también crea la **cuenta de acceso** del usuario en Microsoft Entra External ID (tenant "MiraGroup
Externos"), así el usuario entra directo con un código por correo, sin pasar por "Cree una cuenta"
(ver "Cuentas de acceso en External ID").

Desde la v7 incluye además **Logs control de ingresos**: una página de solo lectura sobre la vista
`core.vHistorialAccesos` (ver "Historial de accesos").

## Páginas

| Ruta | Página |
|---|---|
| `/` | **Portal de administración** (inicio): dos cards, «Logs control de ingresos» y «Centro Administración de contactos» |
| `/contactos` | **Centro Administración de contactos**: la administración de usuarios (hasta la v6 estaba en `/`) |
| `/historial` | **Logs control de ingresos**: indicadores, gráfico por día, tabla paginada y exportación a Excel |

Las tres se comportan igual frente a `AUTH_ENABLED`: con `true` exigen sesión válida y `Portal3 = 1 AND Activo = 1`
(si no, muestran "Ingresa desde el Portal Corporativo" o "No tienes permisos"); con `false` se sirven directo.
Comparten `styles.css` y el encabezado; `/contactos` y `/historial` tienen el enlace «Inicio».

## Cómo funciona el ingreso

1. La home de Power Pages obtiene el token del usuario con **`POST /_services/auth/token`** (con GET el portal
   responde 404; no requiere token antiforgery) y hace un
   **POST de formulario** (navegación de página completa) a `https://<fqdn>/auth/portal` con el campo `token`.
2. La app valida el JWT (RS256) con la clave pública del portal, toma el correo (`email` o
   `preferred_username`) y verifica en SQL `Portal3 = 1 AND Activo = 1`.
3. Si es válido, crea una cookie de sesión firmada (solo guarda el correo; expira por inactividad
   según `SESSION_MAX_AGE_MIN`) y redirige a `/` (el inicio).
4. Cada llamada a `/api/*` vuelve a verificar el permiso en SQL: si a alguien le quitan `Portal3`,
   pierde el acceso en ese mismo momento.

Los POST/PUT/DELETE de `/api/*` exigen `Content-Type: application/json` y `X-Requested-With: mira-admin`.

### `AUTH_ENABLED`: desactivar el ingreso (temporal)

`AUTH_ENABLED` (por defecto `true`) activa todo lo anterior. **Hoy está en `false` en Azure de forma temporal**:
la app ya no se abre desde el portal y, por ahora, no tiene inicio de sesión. Con `AUTH_ENABLED=false`:

- `/`, `/contactos` y `/historial` se muestran directamente. No aparece "Ingresa desde el Portal Corporativo" ni se redirige al portal.
- `/api/*` funciona sin sesión: no lee ni renueva la cookie y no consulta `Portal3`/`Activo` de quien entra.
  `GET /api/me` responde `{"correo": null, "authEnabled": false}`.
- La interfaz oculta el correo del admin, «Volver al portal» y «Cerrar sesión».
- No aplican las reglas "no eliminarse a sí mismo" ni "no quitarse su propio Portal3" (no hay usuario identificado).
- Se mantienen la CSP, los headers de seguridad y la protección CSRF de `/api/*`.
- `/auth/portal`, `/auth/logout` y todo el código de autenticación siguen en la app, sin usarse.
- Al arrancar, el log registra un `WARNING` que avisa que la autenticación está desactivada.

> ⚠️ Sin autenticación, cualquiera que llegue a la URL puede crear, editar y borrar usuarios de producción,
> enviar correos desde `MAIL_SENDER` y ver y exportar el historial de accesos (con correos).
> La protección CSRF no lo impide: solo frena a otros sitios web.

Para volver al ingreso desde el portal (no requiere nueva imagen):

```powershell
az containerapp update -n $APP -g $RG --set-env-vars "AUTH_ENABLED=true"
```

## API

| Método y ruta | Qué hace |
|---|---|
| `GET /health` | `{"status":"ok"}` (público) |
| `POST /auth/portal` | Entrada desde el portal (formulario con `token`) |
| `POST /auth/logout` | Cierra la sesión |
| `GET /api/me` | `{"correo": "..."}` del admin conectado (con `AUTH_ENABLED=false`: `{"correo": null, "authEnabled": false}`) |
| `GET /api/gerencias` | Lista para el desplegable de Gerencia |
| `GET /api/usuarios` | Lista de usuarios (FechaAlta desc, Id desc) |
| `POST /api/usuarios` | Inserta (Activo=1, InvitacionEnviada=0) y crea la cuenta de acceso. No envía correo. → 201 `{usuario, mensaje, avisoCuenta}` |
| `PUT /api/usuarios/{id}` | Edita nombre, apellido, gerencia y portales (el correo no se edita). Si cambia el nombre, lo actualiza en la cuenta de acceso. → `{usuario, mensaje, avisoCuenta}` |
| `DELETE /api/usuarios/{id}` | Elimina en SQL y luego la cuenta de acceso (un admin no puede eliminarse a sí mismo). → `{mensaje, avisoCuenta}` |
| `POST /api/usuarios/{id}/enviar-correo` | Asegura la cuenta de acceso y envía o reenvía el correo de bienvenida (ver abajo) |
| `GET /api/historial` | Historial de accesos, 50 por página (Fecha desc). Filtros más `pagina`. → `{filas, total, pagina, tamano, paginas}` |
| `GET /api/historial/resumen` | Indicadores con los mismos filtros más `tz_offset_min`. → `{total, usuariosUnicos, porPortal, denegados, porDia}` |
| `GET /api/historial/csv` | CSV con los mismos filtros, sin paginar (tope 50.000 filas) |

Los errores siempre vienen como `{"detail": "mensaje en español"}`. `avisoCuenta: true` indica que la operación en
SQL salió bien pero falló la cuenta de acceso; el `mensaje` trae el motivo y la interfaz lo muestra como aviso.

## Historial de accesos

Solo lectura sobre la vista `core.vHistorialAccesos` (base CopilotKnowledgeDB). La vista une
`core.HistorialAccesos` (ingresos a Energía) con `core.SesionesAgente` (ingresos a MiraStock) y toma el nombre de
`core.UsuariosEntel`. La tabla, la vista y los flujos de Power Automate que la alimentan **no son parte de esta
app**: los administra el usuario.

| Columna | Contenido |
|---|---|
| `Fecha` | `DATETIME2(0)` en UTC |
| `Correo` | En minúsculas |
| `Usuario` | Nombre + Apellido; vacío si el correo no está en `UsuariosEntel` (la tabla muestra «—») |
| `Portal` | `Energía` o `MiraStock` |
| `Resultado` | `OK` o `Denegado` |

**Filtros** (todos opcionales, los mismos en los tres endpoints):

| Parámetro | Regla |
|---|---|
| `correo` | Contiene, sin distinguir mayúsculas (máx. 256). `%`, `_` y `[` se buscan como texto |
| `portal` | `Energía` o `MiraStock` (sin distinguir mayúsculas) |
| `resultado` | `OK` o `Denegado` (sin distinguir mayúsculas) |
| `desde` / `hasta` | ISO 8601. Con zona se convierte a UTC; sin zona se toma como UTC. `desde` inclusivo, `hasta` exclusivo, `desde < hasta` |
| `pagina` | Solo `/api/historial`. Entero ≥ 1 (por defecto 1) |
| `tz_offset_min` | Solo `/resumen`. Minutos a sumar a UTC para agrupar por día local (−840 a 840; Chile = −180 o −240) |

Un valor inválido responde **422** `{"detail", "errores": {campo: mensaje}}` con todos los campos con error. Las
fechas de la respuesta vienen en ISO 8601 UTC con `Z` (`2026-10-28T14:05:00Z`).

La página `/historial` convierte los días locales del navegador a UTC: «Desde» es ese día a las 00:00 locales y
«Hasta» es el **día siguiente** a las 00:00 locales (así incluye el día completo). Envía
`tz_offset_min = -new Date().getTimezoneOffset()`. Por defecto muestra los últimos 7 días. Si el rango cruza un
cambio de horario, la agrupación por día usa un solo desfase (puede correrse 1 h en ese día).

**CSV** («Exportar a Excel»): UTF-8 con BOM, separador `;`, fin de línea CRLF. Columnas `Fecha (UTC)`
(`AAAA-MM-DD hh:mm:ss`), Usuario, Correo, Portal y Resultado. Una celda que empieza con `=`, `+`, `-`, `@`, tabulador
o retorno de carro lleva una `'` adelante (para que Excel no la ejecute como fórmula). El archivo se llama
`historial_accesos_AAAAMMDD.csv` (fecha UTC). Si hay más de 50.000 filas, trae las más recientes y el header
`X-Historial-Truncado: 50000`; la interfaz lo avisa.

## Cuentas de acceso en External ID

El usuario ingresa al portal con Microsoft Entra External ID (tenant "MiraGroup Externos",
`cb938793-21a7-440f-9787-2d3924b3fd67`), cuyo flujo de usuario usa **código de un solo uso por correo**, sin
contraseña. La app crea la cuenta con anticipación para que el usuario no tenga que registrarse.

`app/externalid.py` usa Graph con msal (client credentials, authority
`https://login.microsoftonline.com/<EXTID_TENANT_ID>`) y la app registration `35d28c4c-144c-4e3c-9b37-0f0ae4970625`,
que tiene el permiso de aplicación `User.ReadWrite.All` con consentimiento concedido.

**Formato de la cuenta.** Para que el usuario entre **solo con código**, la cuenta debe tener la misma identidad que
deja el autoregistro con código:

```json
{"signInType": "federated", "issuer": "mail", "issuerAssignedId": "<correo>"}
```

sin `passwordProfile` ni `passwordPolicies`. Una identidad `emailAddress` del dominio del tenant es una cuenta local
**con contraseña**, y el portal le pide contraseña aunque el flujo de usuario sea de código (las versiones v4 y v5 de
la app creaban ese formato antiguo). Verificado el 2026-10-23: una cuenta creada por Graph con `federated`/`mail`
entra al portal solo con código.

| Función | Qué hace en Graph |
|---|---|
| `buscar_por_correo` | `GET /users?$filter=identities/any(c:c/issuerAssignedId eq '<correo>' and c/issuer eq 'mail')`; si no hay resultado, repite con `c/issuer eq '<EXTID_DOMAIN>'` para detectar cuentas antiguas con contraseña. Las `'` se duplican. Clasifica la cuenta por las identidades que trae (Graph ignora el issuer al filtrar identidades `emailAddress`) y devuelve `Cuenta(id, tipo)` con tipo `codigo` o `contrasena` (si hay ambas, gana la de código), o `None` |
| `crear` | `POST /users` con `accountEnabled`, `displayName`, `givenName`, `surname` (se omite si está vacío), `mail` e `identities` `federated`/`mail`. **Sin contraseña y sin reintentos**: si Graph rechaza, lanza el error y deja en el log ERROR la respuesta completa de Graph |
| `asegurar` | Busca y, si no existe ninguna cuenta, crea. Devuelve `(id, estado)` con estado `creada`, `existe_codigo` o `existe_contrasena`. Con una cuenta antigua con contraseña **no crea otra**: lo registra como WARNING. Deshabilitado: `(None, None)` |
| `actualizar_nombre` | `PATCH /users/{id}` con `displayName`, `givenName` y `surname`, si la cuenta existe (de código o antigua) |
| `eliminar` | `DELETE /users/{id}`, si la cuenta existe (de código o antigua) |

Para que una cuenta antigua con contraseña pase a entrar con código hay que eliminarla (también de la papelera) y
volver a crearla: con «Enviar correo» desde la app o con la sincronización. Mientras exista, «Enviar correo»
responde 409 y no envía nada (el correo diría que no necesita contraseña).

Con `EXTID_ENABLED=false` ninguna función llama a Graph (solo lo registran en DEBUG) y la app funciona como antes.

| Operación | Si falla la cuenta de acceso |
|---|---|
| Crear usuario | **No se revierte el INSERT**: 201 con "Usuario creado, pero no se pudo crear su cuenta de acceso: <motivo>. Se reintentará al enviar el correo." |
| Enviar correo | **502** "No se pudo crear la cuenta de acceso: <motivo>" y **no se envía** el correo |
| Enviar correo con cuenta antigua (con contraseña) | **409** "La cuenta de acceso es antigua (con contraseña): elimínala y vuelve a intentar". No se envía el correo ni se marca `InvitacionEnviada`; la interfaz muestra el mensaje |
| Editar (cambia nombre o apellido) | Se guarda igual en SQL y el mensaje agrega el aviso |
| Eliminar | Se elimina igual en SQL y el mensaje agrega el aviso. El modal de confirmación dice "También se eliminará su cuenta de acceso al portal." |

Las cuentas eliminadas quedan 30 días en la papelera de Entra. Si se vuelve a crear un usuario con el mismo correo
en ese plazo, Graph podría rechazar la cuenta nueva; en ese caso, restaura o elimina definitivamente la anterior
en el centro de administración de Entra.

### Sincronización inicial (una sola vez, en local)

Crea las cuentas que faltan para los usuarios que ya están en la tabla (`Activo=1` y al menos un portal).
Usa el `.env` local (con `EXTID_ENABLED=true` y `EXTID_CLIENT_SECRET`) y no imprime secretos.

```powershell
.\.venv\Scripts\python.exe -m app.tools.sync_externalid           # modo prueba: no crea nada
.\.venv\Scripts\python.exe -m app.tools.sync_externalid --apply   # crea las que faltan
```

| Modo | Columnas | Estados |
|---|---|---|
| Prueba | Correo, Nombre, Estado | Ya existe (código) / Ya existe (contraseña, antigua) / Se crearía / Error: motivo |
| `--apply` | Correo, Resultado | Ya existía (código) / Ya existía (contraseña, antigua) / Creada / Error: motivo |

Las cuentas antiguas con contraseña nunca se duplican ni se modifican: se informan aparte para eliminarlas a mano
y volver a ejecutar. Termina con un resumen de totales. Código de salida: 0 sin errores, 1 si hubo errores y 2 si External ID está
deshabilitado o le faltan credenciales (en ese caso no consulta nada).

## Correo de bienvenida

Se envía solo con `POST /api/usuarios/{id}/enviar-correo`, que sirve para el primer envío y para los reenvíos.
En la tabla, el botón dice **«Enviar correo»** si `InvitacionEnviada = 0` y **«Reenviar correo»** si ya es 1.

| Resultado | Respuesta | `InvitacionEnviada` |
|---|---|---|
| Enviado | 200 `{"correoEnviado": true, "mensaje": "Correo enviado a <correo>."}` | pasa a 1 |
| Graph falla (permiso, red, etc.) | **502** `{"detail": "No se pudo enviar el correo: <motivo>"}` | no cambia |
| `MAIL_ENABLED=false` o faltan credenciales de Graph | **503** `{"detail": "No se pudo enviar el correo: <motivo>"}` | no cambia |

Antes de enviar, la app asegura la cuenta de acceso en External ID; si eso falla, responde 502 y no envía.

La plantilla incluye el saludo, los portales habilitados, el botón «Ingresar al portal»
(https://miragroup-portal-externo.powerappsportals.com), los pasos para ingresar con código (sin contraseña ni
registro) y el pie.

El correo **no lleva adjuntos** (desde la v5). La guía en PDF de `app/docs/` ya no se envía.

## Estructura

```
app/main.py       FastAPI: middlewares (sesión, CSRF, headers de seguridad), rutas y estáticos
app/config.py     Configuración (pydantic-settings)
app/auth.py       Token del portal, cookie de sesión, dependencia require_admin
app/db.py         Consultas parametrizadas (pyodbc + ODBC Driver 18)
app/mailer.py     msal + Graph sendMail + plantilla HTML del correo
app/externalid.py Cuentas de acceso en External ID (msal + Graph /users)
app/tools/        sync_externalid.py: sincronización inicial de cuentas (se ejecuta en local)
app/docs/         Guía de ingreso en PDF (ya no se adjunta al correo)
app/schemas.py    Validaciones de entrada
app/static/       inicio.html (/), contactos.html + app.js (/contactos), historial.html + historial.js (/historial),
                  comun.js (API, avisos y encabezado de inicio e historial), styles.css, logoMG.png
app/templates/    Páginas "Ingresa desde el Portal Corporativo" y "No tienes permisos"
tests/            pytest (BD, Graph y External ID simulados)
```

---

## Desarrollo local

Requisitos: Python 3.12 y [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
Tu IP debe estar permitida en el firewall de Azure SQL.

```powershell
cd Portal3
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env      # y completa los valores
uvicorn app.main:app --reload --port 8000
```

- `http://localhost:8000/health` → `{"status":"ok"}`
- `http://localhost:8000/` sin sesión → "Ingresa desde el Portal Corporativo".

### Probar el ingreso real en local

La app solo acepta tokens firmados por el portal. Para probar en local, inicia sesión en el portal
con un usuario que tenga `Portal3 = 1`, abre la consola del navegador (F12) **en la página del portal** y ejecuta:

```js
const t = await (await fetch('/_services/auth/token', { method: 'POST' })).text();
const f = Object.assign(document.createElement('form'), { method: 'POST', action: 'http://localhost:8000/auth/portal' });
f.append(Object.assign(document.createElement('input'), { type: 'hidden', name: 'token', value: t }));
document.body.append(f); f.submit();
```

Chrome, Edge y Firefox aceptan la cookie `Secure` en `http://localhost`. Con `LOG_LEVEL=DEBUG`
verás en la consola los **nombres** de los claims del token (nunca sus valores), para confirmar
que trae `email`.

### Tests

```powershell
pytest                                              # todos
pytest tests/test_usuarios.py                       # un archivo
pytest tests/test_auth.py::test_permiso_revocado_corta_en_el_momento   # un test
```

Los tests no usan la BD ni Graph reales: definen su propia configuración y simulan ambos.

---

## Base de datos: usuario dedicado (recomendado)

En vez de usar el administrador del servidor, crea un usuario con permisos mínimos.
Ejecútalo conectado a **CopilotKnowledgeDB** (no a `master`):

```sql
CREATE USER mira_admin_app WITH PASSWORD = '<clave segura>';
GRANT SELECT, INSERT, UPDATE, DELETE ON core.UsuariosEntel TO mira_admin_app;
GRANT SELECT ON core.StockLurinERI TO mira_admin_app;
```

Luego usa `SQL_USER=mira_admin_app` y esa clave en el Container App.

---

## Despliegue en Azure Container Apps

### Despliegue actual

| | |
|---|---|
| **URL pública** | https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io |
| **URL de entrada (la usa la home)** | `POST https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io/auth/portal` (formulario, campo `token`). Sin uso mientras `AUTH_ENABLED=false` |
| **Autenticación** | `AUTH_ENABLED=false` (temporal desde la v3, ver "`AUTH_ENABLED`: desactivar el ingreso") |
| Health | `GET https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io/health` → `{"status":"ok"}` |
| Suscripción | CreditosCopilot1 (`38b3f030-c7b5-4d38-822b-c533f88cd34a`) |
| Container App | `ca-mira-admin` en `RG-COPILOT-DEV`, East US |
| Environment (reutilizado) | `managedEnvironment-rgscripth25prod-818f` (`rg-script-h25-prod`, East US) |
| Registro (reutilizado) | `acrscripth25prod.azurecr.io`, imagen `mira-admin-app:v7` (revisión `ca-mira-admin--0000009`, 2026-10-28) |
| Recursos | 0.25 vCPU, 0.5 GiB, réplicas mín. 0 / máx. 1, ingress externo solo HTTPS (HTTP redirige) |
| Pull de la imagen | Usuario admin del ACR (guardado como secret del Container App). Con rol Contributor no se puede asignar `AcrPull` a una identidad administrada |
| Secrets | `sql-password`, `session-secret`, `graph-client-secret` (secreto de la app "Portal Externo - Envio de correos"), `extid-client-secret` (secreto de la app de External ID) |
| Correo | `MAIL_ENABLED=true`, `MAIL_SENDER=no-reply@miragroup.cl`, `GRAPH_CLIENT_ID=e722c6e6-d604-4c2d-88ad-01c62a2c9235` (activado el 2026-10-20) |
| Firewall SQL | Regla existente `AllowAllWindowsAzureIps` (0.0.0.0) en `sqlcopilotprd01` |

La home de Power Pages hace `POST /_services/auth/token` en el portal y luego un POST de formulario
(navegación completa) a la URL de entrada con el campo `token`.

Con réplicas mínimas 0, la primera visita después de un rato sin uso puede tardar unos segundos (arranque en frío).

Todos los comandos son para **PowerShell**, desde la raíz del proyecto (`Portal3`, donde está el `Dockerfile`).
`.dockerignore` deja fuera `.env`, `.venv/`, `.claude/`, `brief.md`, `CLAUDE.md` y los tests: nada de eso se sube ni entra en la imagen.

```powershell
$RG  = "RG-COPILOT-DEV"
$APP = "ca-mira-admin"
$ACR = "acrscripth25prod"
az account set --subscription 38b3f030-c7b5-4d38-822b-c533f88cd34a
```

### Publicar una nueva versión (v2, v3…)

Usa un tag nuevo en cada versión (no reutilices `v1`) para poder volver atrás.

```powershell
.\.venv\Scripts\python.exe -m pytest                      # primero, los tests
az acr build --registry $ACR --image mira-admin-app:v2 .
az containerapp update -n $APP -g $RG --image "$ACR.azurecr.io/mira-admin-app:v2"
Invoke-RestMethod "https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io/health"
```

Volver a la versión anterior:

```powershell
az containerapp update -n $APP -g $RG --image "$ACR.azurecr.io/mira-admin-app:v1"
```

### Logs

```powershell
az containerapp logs show -n $APP -g $RG --type console --tail 100 --format text   # logs de la app
az containerapp logs show -n $APP -g $RG --type console --follow                   # en vivo
az containerapp logs show -n $APP -g $RG --type system --tail 50                   # arranque, imagen, réplicas
az containerapp revision list -n $APP -g $RG -o table
```

Si la réplica está apagada (escala a 0), `logs show` puede no tener contenedor al que conectarse.
Abre `/health` primero o revisa el historial en Log Analytics del environment.

### Activar el correo (cuando TI habilite el buzón)

TI debe dar a la app de Entra el permiso de aplicación `Mail.Send`, limitado al buzón
`no-reply@miragroup.cl` con **RBAC para aplicaciones en Exchange Online**. Luego (el secreto se pide por consola):

```powershell
function Leer-Secreto([string]$texto) {
  $s = Read-Host $texto -AsSecureString
  [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
$GRAPH_SECRET = Leer-Secreto "Secreto de la app de Graph"
az containerapp secret set -n $APP -g $RG --secrets "graph-client-secret=$GRAPH_SECRET"
Remove-Variable GRAPH_SECRET
# update crea una revisión nueva, que toma también el secret actualizado
az containerapp update -n $APP -g $RG --set-env-vars "GRAPH_CLIENT_ID=<client id de la app de Entra>" "MAIL_ENABLED=true"
```

Para probarlo, usa «Enviar correo» sobre un usuario de prueba. Si falla, la API responde 502 y el toast muestra
el código de Graph (por ejemplo `ErrorAccessDenied` si falta el permiso en Exchange); el log también lo registra.

Mientras `MAIL_ENABLED=false`, crear usuarios funciona normalmente y «Enviar correo» responde
503 "No se pudo enviar el correo: Envío de correo deshabilitado", sin marcar `InvitacionEnviada`.

### Activar External ID

1. Cargar el secreto con el script de PowerShell que lo pide sin mostrarlo. Lo guarda en el secret
   `extid-client-secret` del Container App y en `EXTID_CLIENT_SECRET` del `.env` local, y solo informa si funcionó.
2. Publicar la imagen nueva y configurar las variables:

```powershell
az containerapp update -n $APP -g $RG --image "$ACR.azurecr.io/mira-admin-app:vN" `
  --set-env-vars "EXTID_TENANT_ID=cb938793-21a7-440f-9787-2d3924b3fd67" `
                 "EXTID_CLIENT_ID=35d28c4c-144c-4e3c-9b37-0f0ae4970625" `
                 "EXTID_DOMAIN=miragroupexternos.onmicrosoft.com" `
                 "EXTID_CLIENT_SECRET=secretref:extid-client-secret" `
                 "EXTID_ENABLED=true"
```

3. Probar con un correo que no tenga cuenta: crearlo desde la app y entrar al portal. Debe pedir **solo el código**,
   sin contraseña ni nombre ni apellido. Recién entonces, ejecutar la sincronización inicial (primero en modo prueba).

Para apagarlo sin imagen nueva: `az containerapp update -n $APP -g $RG --set-env-vars "EXTID_ENABLED=false"`.

### Cambiar otros secretos o variables

```powershell
az containerapp secret set -n $APP -g $RG --secrets "sql-password=<nueva clave>"
az containerapp update -n $APP -g $RG --set-env-vars "SQL_USER=mira_admin_app"
```

Después de `secret set`, el cambio se aplica en la siguiente revisión (cualquier `update`) o al reiniciar:
`az containerapp revision restart -n $APP -g $RG --revision <nombre de la revisión activa>`.

### Costo mensual estimado

No se crearon recursos con costo fijo nuevo: el environment, el registro, el servidor SQL y Log Analytics ya existían.

| Recurso | Costo adicional estimado |
|---|---|
| Container App `ca-mira-admin` (consumo, 0.25 vCPU / 0.5 GiB, mín. 0 réplicas) | **US$0–3/mes**. Solo cobra mientras hay una réplica activa. Ejemplo: 100 h activas al mes ≈ 90.000 vCPU·s + 180.000 GiB·s, dentro de la cuota gratuita mensual de la suscripción (180.000 vCPU·s, 360.000 GiB·s y 2 millones de requests). Esa cuota la comparten todos los Container Apps de la suscripción; sin ella serían ≈ US$2,70 |
| Environment `managedEnvironment-rgscripth25prod-818f` | US$0 adicional (ya existía) |
| ACR `acrscripth25prod` (Basic) | US$0 adicional. Ya se paga (≈ US$5/mes); la imagen ocupa una parte mínima de los 10 GB incluidos. Cada `az acr build` cuesta centavos |
| Logs (Log Analytics del environment) | ≈ US$0. Pocos MB al mes con `LOG_LEVEL=INFO` |
| Azure SQL `sqlcopilotprd01` | US$0 adicional (base existente, consultas livianas) |

Son precios de lista aproximados para East US. Confírmalos en la calculadora de precios de Azure o en Cost Management.

### Pendientes de seguridad recomendados

- **Volver a exigir autenticación** (`AUTH_ENABLED=true` o un login propio). Mientras esté en `false`, la app y el
  envío de correo quedan abiertos a cualquiera que tenga la URL.
- Usar el usuario dedicado `mira_admin_app` (ver "Base de datos: usuario dedicado") en vez de `sqladmin`, y cambiar la clave de `sqladmin`.
- Usar en Azure un `SESSION_SECRET` distinto del local.
- La regla `AllowAllWindowsAzureIps` permite conexiones desde cualquier recurso de Azure, también de otros clientes.
  La opción más cerrada es un environment con VNet y un private endpoint al SQL (tiene costo: pedir OK antes).
- Si más adelante se obtiene un rol con permiso para asignar roles (Owner o User Access Administrator), se puede
  pasar de la clave admin del ACR a identidad administrada con `AcrPull`.
