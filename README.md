# Administración de usuarios – Portal Externo MiraGroup

App web independiente (FastAPI + HTML/CSS/JS sin librerías) para administrar la tabla
`core.UsuariosEntel` de Azure SQL, que controla el acceso al Portal Externo:

| Columna | Portal |
|---|---|
| `Portal1` | Portal de Energía |
| `Portal2` | Portal MiraStock |
| `Portal3` | Administración de usuarios (desde la v12 es solo un dato: el acceso a esta app lo da `core.AdministradoresPortal`) |

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
| `/login` | **Ingreso** (v12): correo y contraseña de administrador. Pública |
| `/cambiar-contrasena` | **Cambiar contraseña** (v12): obligatoria después de entrar con la contraseña por defecto; también voluntaria |
| `/` | **Portal de administración** (inicio): cuatro cards en cuadrícula de 2 × 2 (1 columna en celular), «Estadísticas del Portal Corporativo MiraGroup», «Centro Administración de contactos», «Centro de administración principal» y «Consulta de base de datos» (v19), con íconos 3D (v20) |
| `/contactos` | **Centro Administración de contactos**: la administración de usuarios (hasta la v6 estaba en `/`) |
| `/estadisticas` | **Estadísticas del Portal Corporativo MiraGroup** (v11; desde la v16, inicio con cards): una card «General por portal» y una por portal con el resumen de los últimos 30 días (ver "Estadísticas") |
| `/estadisticas/general` | v16: gráficos y tabla del total por portal, con su propio filtro de fechas |
| `/estadisticas/portal/<slug>` | v16: gráficos y pestañas Usuarios (general/detallado) de un portal (`energia`, `mirastock`…); «Portal no encontrado» si no existe. v17: buscador por correo para las tarjetas y los gráficos |
| `/historial` | **Logs control de ingresos** (historial completo): indicadores, gráfico por día, tabla paginada y exportación a Excel. Sin card en el inicio desde la v11; se llega desde «Historial completo» en `/estadisticas` |
| `/administradores` | **Centro de administración principal** (v12): administradores en cards y edición con la contraseña de cada uno (ver "Administradores") |
| `/consulta-bd` | **Consulta de base de datos** (v19, solo lectura): últimos 500 registros de una lista cerrada de 20 tablas de `core`, con buscador «contiene» (ver "Consulta de base de datos") |

Sin sesión, toda página redirige (303) a `/login?siguiente=<ruta>`. Con `DebeCambiarContrasena = 1`, redirige a
`/cambiar-contrasena`. Comparten `styles.css` y el encabezado (nombre del administrador y «Cerrar sesión»); las páginas
internas tienen el enlace «Inicio».

## Cómo funciona el ingreso (v12)

Portal3 es independiente del Portal Corporativo y tiene **login propio**. Desde la v12 ya no existen `/auth/portal`
(entrada con el token de Power Pages) ni `AUTH_ENABLED`: la autenticación está siempre activa.

**Administradores:** tabla `core.AdministradoresPortal` (la crea y mantiene el usuario, no esta app). Se crean por SQL
con `core.sp_CrearAdministrador` (contraseña por defecto `Admin@123456`, `DebeCambiarContrasena = 1`,
`AlgoritmoHash = 'SHA2_512'`). `core.sp_RestablecerContrasenaAdmin` la vuelve a la por defecto y desbloquea. Altas y
bajas solo por SQL.

1. `/login` envía `POST /api/auth/login` con `{correo, contrasena}`.
2. La app busca al administrador por correo (en minúsculas) y verifica la contraseña según `AlgoritmoHash`:
   - `SHA2_512` (creados o restablecidos por SQL): `SHA-512(sal || contraseña en UTF-16LE)`.
   - `PBKDF2_SHA256` (contraseñas cambiadas en Portal3): PBKDF2-HMAC-SHA256, 600.000 iteraciones, sal de 32 bytes.
   - La comparación es en tiempo constante. Si el correo no existe se calcula igual un PBKDF2, así el tiempo de
     respuesta no revela qué correos son administradores. Desde la v20 toda verificación cuesta un PBKDF2 (también
     `SHA2_512`): el tiempo tampoco delata a los administradores con la contraseña por defecto pendiente.
3. Cualquier fallo (correo desconocido, contraseña mala, `Activo = 0`, bloqueado) responde 401 con el mismo mensaje:
   «Correo o contraseña incorrectos.».
4. **Bloqueo:** 5 intentos fallidos → `BloqueadoHasta` = ahora + 15 min. Mientras está bloqueado no se verifica la
   contraseña ni se suman intentos. Un fallo después de un bloqueo vencido empieza la cuenta de nuevo. Un acierto pone
   `IntentosFallidos = 0`, `BloqueadoHasta = NULL` y `UltimoAcceso` = ahora. El reloj es el de SQL (`SYSUTCDATETIME()`).
5. **Contraseña por defecto:** con `DebeCambiarContrasena = 1` el login entra, pero toda página redirige a
   `/cambiar-contrasena` y toda API (salvo `/api/me`, logout y cambio de contraseña) responde 403
   `{detail, cambioRequerido: true}`. Solo sirve durante **24 h** (v20; antes 72 h) desde `COALESCE(FechaCambioContrasena, FechaAlta)`;
   después hay que restablecerla por SQL (requiere que `sp_RestablecerContrasenaAdmin` actualice
   `FechaCambioContrasena`, ver el ALTER de la v12).
6. **Migración:** un login correcto con `SHA2_512` y `DebeCambiarContrasena = 0` pasa el hash a PBKDF2 (misma contraseña).
7. **Política de contraseña nueva:** mínimo 10 caracteres (máximo 128), con mayúscula, minúscula, número y símbolo;
   distinta de `Admin@123456` y de la actual. Desde la v20 la regla «distinta de la por defecto» la valida solo el
   servidor: la contraseña por defecto no aparece en el JS público.
8. **Límite por IP:** 20 intentos (login + verificación de cards) cada 15 minutos por IP → 429. La IP es la última de
   `X-Forwarded-For` (la agrega el ingress); en memoria, porque la app corre en una sola réplica.

**Sesión:** cookie firmada `mira_admin_sesion` (HttpOnly, Secure, SameSite=Lax) con `{id, h, i}`: el Id del
administrador, una huella HMAC de su hash y (v20) la hora del ingreso. Vence por inactividad (`SESSION_MAX_AGE_MIN`) y
cada request válido la renueva, pero desde la v20 nunca dura más de **12 h desde el ingreso** (renovar o cambiar la
contraseña no reinicia ese tope; las cookies anteriores a la v20 dejaron de valer). En cada
página y en cada `/api/*` se vuelve a leer al administrador en SQL: si lo desactivan, lo eliminan o cambia su
contraseña (en Portal3 o restablecida por SQL), la sesión se corta en ese momento (páginas → `/login`, API → 401).

Los POST/PUT/DELETE de `/api/*` exigen `Content-Type: application/json` y `X-Requested-With: mira-admin` (también el
login). Única excepción: `/api/latido`.

**Cabeceras y límites (v20):** todas las respuestas llevan CSP estricta, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer` y `Strict-Transport-Security: max-age=31536000`; las que no son estáticas, además
`Cache-Control: no-store`. Los POST/PUT/PATCH/DELETE de `/api/*` con más de 64 KB responden 413, y sin
`Content-Length` (envío por partes) 411, salvo `/api/latido`, que tiene su propio tope de 8 KB.

## API

| Método y ruta | Qué hace |
|---|---|
| `GET /health` | `{"status":"ok"}` (público) |
| `POST /api/auth/login` | **Público.** `{correo, contrasena}` → 200 `{redirect, debeCambiarContrasena}` + cookie (vale hasta 12 h desde el ingreso, v20); 401 genérico; 429 por IP. Acepta `?siguiente=` (solo rutas internas) |
| `POST /api/auth/logout` | Cierra la sesión → `{redirect: "/login"}` |
| `POST /api/auth/cambiar-contrasena` | `{actual, nueva, confirmacion}` → `{mensaje, redirect}` y cookie nueva. Funciona aunque deba cambiarla |
| `GET /api/me` | `{id, nombre, correo, debeCambiarContrasena}` del administrador conectado |
| `GET /api/administradores` | Todos los administradores: `[{id, nombre, correo, ultimoAcceso, estado, bloqueadoHasta, esYo}]` (`estado`: `activo`, `bloqueado` o `inactivo`). Nunca el hash |
| `POST /api/administradores/{id}/verificar` | `{contrasena}` de ESE administrador → `{permiso, expiraEnSeg: 300, administrador}`. 422 si es incorrecta (suma a su bloqueo), 423 bloqueado, 403 inactivo, 429 por IP |
| `PUT /api/administradores/{id}` | `{permiso, nombre, correo, nuevaContrasena?, confirmacion?}` → `{administrador, mensaje}`. Sin permiso válido: 403 `{detail, permisoVencido: true}`; correo repetido: 409 |
| `GET /api/gerencias` | Lista para el desplegable de Gerencia |
| `GET /api/usuarios` | Lista de usuarios (FechaAlta desc, Id desc) |
| `POST /api/usuarios` | Inserta (Activo=1, InvitacionEnviada=0) y crea la cuenta de acceso. No envía correo. → 201 `{usuario, mensaje, avisoCuenta}` |
| `PUT /api/usuarios/{id}` | Edita nombre, apellido, gerencia, cliente y portales (el correo no se edita). Si cambia el nombre, lo actualiza en la cuenta de acceso. → `{usuario, mensaje, avisoCuenta}` |
| `DELETE /api/usuarios/{id}` | Elimina en SQL y luego la cuenta de acceso. → `{mensaje, avisoCuenta}` |
| `POST /api/usuarios/{id}/enviar-correo` | Asegura la cuenta de acceso y envía o reenvía el correo de bienvenida (ver abajo) |
| `GET /api/historial` | Historial de accesos, 50 por página (Fecha desc). Filtros más `pagina`. → `{filas, total, pagina, tamano, paginas}` |
| `GET /api/historial/resumen` | Indicadores con los mismos filtros más `tz_offset_min`. → `{total, usuariosUnicos, porPortal, denegados, tiempoPromedioSeg, tiempoTotalSeg, enCurso, cerradasBoton, porDia}` |
| `POST /api/latido` | **Público** (CORS para `LATIDO_ORIGINS`). Latido de sesión de Energía o MiraStock (ver "Latidos de sesión"). → 204; 429 con más de 60 por minuto desde la misma IP (v20) |
| `GET /api/historial/csv` | CSV con los mismos filtros más `tz_offset_min`, sin paginar (tope 50.000 filas) |
| `GET /api/estadisticas/portales` | Totales por portal y total general (`desde`/`hasta`). → `{portales: [...], total}`; desde la v16 cada portal trae `slug` (ver "Estadísticas") |
| `GET /api/estadisticas/portales/csv` | El mismo cuadro en CSV, con fila «Total Portal Corporativo» (`tz_offset_min`) |
| `GET /api/estadisticas/usuarios` | Una fila por usuario de un portal (`portal` obligatorio, `desde`/`hasta`, `correo` opcional: contiene, v13). → `{portal, correo, filas, total, totalSinFiltro, truncado}` |
| `GET /api/estadisticas/usuarios/csv` | La misma lista en CSV (`tz_offset_min`, `correo`; tope 5.000 usuarios) |
| `GET /api/estadisticas/resumen` | v17: tarjetas de un portal (`portal` obligatorio, `desde`/`hasta`, `correo` opcional: contiene). → `{portal, correo, usuariosUnicos, sesiones, segundosTotales, promedioSeg, sesionesMedidas, ultimaConexion, sinActividad}` |
| `GET /api/estadisticas/series` | v16: sesiones, segundos y usuarios por día local, por portal y en total (`portal` opcional, `desde`/`hasta`, `tz_offset_min`; v17: `correo` opcional, solo con `portal`; ver "Gráficos") |
| `GET /api/estadisticas/distribucion` | v16: tipos de cierre, rangos de duración y matriz día × hora de un portal (`portal` obligatorio, `desde`/`hasta`, `tz_offset_min`; v17: `correo` opcional) |
| `GET /api/consulta-bd/tablas` | v19: la lista cerrada de tablas (sale del código, no consulta la base). → `{tope, tablas: [{clave, nombre, camposBusqueda}]}` |
| `GET /api/consulta-bd/filas` | v19: `tabla` (clave exacta, obligatoria) y `q` opcional (contiene, ≤ 100). → `{tabla, clave, columnas: [{nombre, tipo}], camposBusqueda, busqueda, tope, mostrando, total, totalTabla, filas}`. 422 si la tabla no existe, si `q` es largo o si la tabla no tiene buscador; 503 si falla la base |

Los errores siempre vienen como `{"detail": "mensaje en español"}`. `avisoCuenta: true` indica que la operación en
SQL salió bien pero falló la cuenta de acceso; el `mensaje` trae el motivo y la interfaz lo muestra como aviso.

Sin sesión, toda `/api/*` responde 401 (salvo `/health`, `/api/latido` y `/api/auth/login`/`logout`). La sesión se
revisa antes que los datos: sin sesión es 401 aunque el body o los filtros sean inválidos.

**Cliente (v12):** `POST`/`PUT /api/usuarios` exigen `cliente` (`Entel`, `MiraGroup` u `Otro`; sin distinguir
mayúsculas, se guarda con esa escritura) en la columna `core.UsuariosEntel.Cliente`. Al crear, la interfaz lo sugiere por
el dominio del correo (`entel.pe` → Entel, `miragroup.cl` → MiraGroup, otro → Otro) hasta que se elige a mano. La tabla
tiene la columna «Cliente» y un filtro por cliente. Desde la v12 ya no existen las reglas «no puedes eliminarte» ni
«no puedes quitarte Portal3»: el contacto y el administrador son registros distintos.

**Gerencias:** `GET /api/gerencias` es la `UNION` de los `Gerencia` distintos (no vacíos) de `core.StockLurinERI` (contra
la que compara el agente MiraStock) y de `core.UsuariosEntel`. Un valor que aparece solo en contactos se quita
corrigiendo esos contactos en SQL (así se quitó «CONSTRUCCION E INFRAESTRUCTURA DE RED» en la v12).

## Administradores

`/administradores` («Centro de administración principal») muestra a todos los administradores en cards: nombre,
correo, último acceso y estado. Los inactivos y los bloqueados no se pueden abrir.

1. Al elegir una card se pide la contraseña **de ese administrador** (`POST /api/administradores/{id}/verificar`).
   Los fallos cuentan para el bloqueo de ese administrador (el mismo del login).
2. Si es correcta, la API entrega un **permiso de edición** firmado (itsdangerous, sal propia) que dura 5 minutos y
   está atado al Id del administrador, a la sesión de quien lo pidió y a la huella del hash de su contraseña.
   La interfaz lo guarda solo en memoria y lo descarta al cerrar la ficha.
3. La ficha permite cambiar nombre, correo y (opcional) la contraseña, con la misma política del cambio obligatorio.
   Una contraseña nueva cierra las demás sesiones de ese administrador; si es la propia, quien edita sigue conectado.
4. Altas, bajas y restablecimientos: solo por SQL (`sp_CrearAdministrador`, `sp_RestablecerContrasenaAdmin`).


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
| `Portal` | Hoy `Energía` o `MiraStock`; la app no fija la lista (un portal nuevo en la vista aparece solo) |
| `Resultado` | `OK` o `Denegado` |
| `FinalSesion` | `DATETIME2(0)` UTC del último latido; NULL si la sesión no envió latidos |
| `TiempoSesionSeg` | `FinalSesion − Fecha` en segundos; NULL sin latidos |
| `EnCurso` | `BIT`: 1 si el último latido tiene menos de 5 minutos (0 si la sesión se cerró con botón) |
| `CierreExplicito` | `BIT`: 1 si la sesión se cerró con «Atrás» o «Cerrar sesión» |
| `Medible` | `BIT` (v14): 1 si la sesión podía medirse (Energía: tiene llave; MiraStock: creada desde el primer latido registrado). NULL cuenta como 0 |
| `SinActividad` | `BIT` (v14): 1 si era medible, nunca llegó un latido y pasaron más de 5 min. En ese caso `TiempoSesionSeg = 0`; en los primeros 5 min `EnCurso = 1` |

**Filtros** (todos opcionales, los mismos en los tres endpoints):

| Parámetro | Regla |
|---|---|
| `correo` | Contiene, sin distinguir mayúsculas (máx. 256). `%`, `_` y `[` se buscan como texto |
| `portal` | Cualquier nombre de hasta 50 caracteres (desde la v11). `energía`/`mirastock` se normalizan a `Energía`/`MiraStock`; un portal que no existe devuelve 0 filas |
| `resultado` | `OK` o `Denegado` (sin distinguir mayúsculas) |
| `desde` / `hasta` | ISO 8601. Con zona se convierte a UTC; sin zona se toma como UTC. `desde` inclusivo, `hasta` exclusivo, `desde < hasta` |
| `pagina` | Solo `/api/historial`. Entero ≥ 1 (por defecto 1) |
| `tz_offset_min` | Solo `/resumen` y `/csv`. Minutos a sumar a UTC para agrupar por día local o escribir las fechas del CSV en hora local (−840 a 840; Chile = −180 o −240; por defecto 0 = UTC) |

Un valor inválido responde **422** `{"detail", "errores": {campo: mensaje}}` con todos los campos con error. Las
fechas de la respuesta vienen en ISO 8601 UTC con `Z` (`2026-10-28T14:05:00Z`).

Cada fila de `/api/historial` trae además `FinalSesion` (ISO UTC o `null`), `TiempoSesionSeg` (entero o `null`),
`EnCurso` (bool), `CierreExplicito` (bool) y, desde la v14, `Medible` y `SinActividad` (bool). El resumen agrega `tiempoPromedioSeg` (promedio de las filas con tiempo; `null` si no hay
ninguna), `tiempoTotalSeg: {"Energía", "MiraStock"}` (suma en segundos de las filas con tiempo) `enCurso`
(cantidad de filas con `EnCurso = 1`) y `cerradasBoton` (cantidad de filas con `CierreExplicito = 1`).

La tabla de `/historial` (y la pestaña «Usuarios (detallado)» de `/estadisticas`) muestra, con los mismos textos que
el CSV (`comun.js` `textoCierre`/`textoTiempo`/`textoFinal` y `main._texto_cierre`/`_tiempo_csv`/`_final_sesion`):

- **Cierre**, en este orden: «Botón» si `CierreExplicito = 1` → «En curso» si `EnCurso = 1` → «Inactividad» si hay
  `FinalSesion` → «Sin actividad» si `SinActividad = 1` → «No medida» si `Medible = 0` → «—».
- **Tiempo de sesión:** «0 min» si `SinActividad = 1`; si no, «< 1 min», «44 min», «1 h 05 min» (truncado) o «—»
  (sin medir).
- **Final de sesión:** hora local `dd/mm/aaaa hh:mm`, la etiqueta «En curso», la **hora de ingreso** si
  `SinActividad = 1`, o «—» (no medida).
- Las filas **Denegado** muestran «—» en las tres (no fueron sesiones).

La página `/historial` convierte los días locales del navegador a UTC: «Desde» es ese día a las 00:00 locales y
«Hasta» es el **día siguiente** a las 00:00 locales (así incluye el día completo). Envía
`tz_offset_min = -new Date().getTimezoneOffset()`. Por defecto muestra los últimos 7 días. Si el rango cruza un
cambio de horario, la agrupación por día usa un solo desfase (puede correrse 1 h en ese día).

**CSV** («Exportar a Excel»): UTF-8 con BOM, separador `;`, fin de línea CRLF. Columnas `Fecha (<zona>)`
(`AAAA-MM-DD hh:mm:ss`), Usuario, Correo, Portal, Resultado, `Final de sesión (<zona>)` (`AAAA-MM-DD hh:mm:ss`) y
`Tiempo de sesión (min)` (minutos enteros truncados; `0` sin actividad; vacío si no se midió) y `Cierre` (los
mismos textos que la tabla; en las tres columnas, vacío en lugar de «—»). Desde la v11 las fechas van en hora local según `tz_offset_min` (la interfaz lo envía) y el
encabezado lo indica: `Fecha (hora local, UTC-03:00)`; con `tz_offset_min=0` u omitido queda `Fecha (UTC)`.
Una celda que empieza con `=`, `+`, `-`, `@`, tabulador
o retorno de carro lleva una `'` adelante (para que Excel no la ejecute como fórmula). El archivo se llama
`historial_accesos_AAAAMMDD.csv` (fecha UTC). Si hay más de 50.000 filas, trae las más recientes y el header
`X-Historial-Truncado: 50000`; la interfaz lo avisa.

## Estadísticas

Solo lectura sobre la misma vista. **Sesión = fila con `Resultado = 'OK'`**; los denegados no cuentan como sesión
ni como usuario.

**Estructura (v16; antes, un acordeón en una sola página):**

- **`/estadisticas`** es un inicio con cards (estilo del inicio de Portal3; 3 columnas en escritorio, 2 en tablet
  y 1 en celular): «General por portal» y una por cada portal de la vista, generadas desde
  `/api/estadisticas/portales` (sin código por portal). Cada card muestra el resumen de los últimos 30 días
  («85 sesiones · 61 h 46 min» y los usuarios) y una franja con el color del portal. Mantiene «Historial completo».
- Cada card abre su vista, con URL propia (Atrás del navegador y marcadores funcionan):
  `/estadisticas/general` y `/estadisticas/portal/<slug>`. Mismas reglas de login que el resto (sin sesión →
  `/login?siguiente=<ruta>`).
- **Slug:** `/api/estadisticas/portales` trae `slug` en cada portal (`main._slug_portal`): ASCII en minúsculas,
  sin tildes, y todo lo que no es letra o número pasa a `-` («Energía» → `energia`, «Bodega Norte» →
  `bodega-norte`). Si dos portales dan el mismo slug, en orden alfabético el segundo lleva `-2`, el tercero `-3`…
  La página busca el portal por su slug en esa respuesta: si no existe, muestra «Portal no encontrado» con un
  enlace a `/estadisticas`. Un slug con otro formato (`[a-z0-9]+(-[a-z0-9]+)*`, hasta 64 caracteres) responde 404
  con el mismo mensaje.
- **Cada vista es independiente:** encabezado con «← Estadísticas» y el título de la sección; su propio filtro
  Desde / Hasta con «Aplicar» (por defecto los últimos 30 días) y «Historial completo». Las fechas se recuerdan
  durante la sesión del navegador (`sessionStorage`, claves `mira.estadisticas.rango.general` y
  `mira.estadisticas.rango.portal.<slug>`); si el almacenamiento no está disponible, se usan los 30 días.
- El contenido de cada vista va desplegado (gráficos arriba, ver "Gráficos de estadísticas"):

1. **General por portal:** una fila por portal (el nombre enlaza a su vista) y la fila «Total Portal Corporativo». Columnas: Portal ·
   Usuarios únicos · Sesiones · Horas totales · Promedio por sesión · Última conexión.
   - Horas totales = suma de `TiempoSesionSeg`; el promedio considera solo las sesiones con tiempo medido. Si hay
     sesiones sin latidos, la celda agrega «medidas: N de M».
   - v14: si hay sesiones sin actividad, la celda agrega también «sin actividad: K». Esas sesiones valen 0 s, así
     que cuentan como medidas y bajan el promedio.
   - En el total, los usuarios únicos se cuentan **sin repetir entre portales** (`GROUPING SETS`); sesiones y horas suman.
   - Aparecen todos los portales de la vista (`SELECT DISTINCT Portal`), aunque no tengan sesiones en el rango.
2. **Cada portal** (sin código por portal), con pestañas:
   - **Usuarios (general):** Usuario · Correo · Sesiones · Sin actividad (v14) · Horas totales · Promedio · Última conexión, de más a
     menos horas (luego más sesiones, luego correo).
     - v13: buscador «Correo» (contiene, sin distinguir mayúsculas) con «Buscar» o Enter, igual que en
       «detallado». Contador «7 usuarios» o «2 de 7 usuarios»; sin coincidencias, «Sin usuarios que coincidan con
       la búsqueda». «Exportar a Excel» exporta lo filtrado. El texto buscado se mantiene al cambiar las fechas.
       Cada pestaña tiene su propio filtro, y el resumen del encabezado del portal no se filtra.
   - **Usuarios (detallado):** la tabla de `/historial` filtrada al portal, con correo, resultado, páginas y CSV.
   - La pestaña «Usuarios (detallado)» carga sus datos recién al elegirla.
3. Los niveles 3 y 4 (funcionalidades y subfuncionalidades) se agregarán como otra entrada de `SUBVISTAS` en
   `estadisticas.js`, con su propio endpoint.

Respuestas (fechas ISO UTC con `Z`; segundos enteros o `null` si no hay tiempo medido):

```json
GET /api/estadisticas/portales
{"portales": [{"portal": "Energía", "slug": "energia", "usuariosUnicos": 6, "sesiones": 29, "segundosTotales": 3589,
               "promedioSeg": 897, "sesionesMedidas": 4, "ultimaConexion": "2026-10-29T22:39:40Z",
               "sinActividad": 0}, ...],
 "total": {"usuariosUnicos": 10, "sesiones": 48, ...}}

GET /api/estadisticas/usuarios?portal=Energía
{"portal": "Energía", "correo": null, "filas": [{"usuario": "Ana Pérez", "correo": "ana@...", "sesiones": 4, ...}],
 "total": 6, "totalSinFiltro": 6, "truncado": false}

GET /api/estadisticas/usuarios?portal=Energía&correo=entel
{"portal": "Energía", "correo": "entel", "filas": [...], "total": 2, "totalSinFiltro": 6, "truncado": false}
```

Validación igual que el historial (422 `{detail, errores}`); en `/usuarios` falta `portal` → «Indica el portal.».
`correo` (v13) usa el mismo `LIKE ? ESCAPE '\'` que `/api/historial` (`%`, `_`, `[` y `\` se buscan literales) y
el mismo límite de 256 caracteres. `totalSinFiltro` = usuarios distintos del portal en el rango sin el filtro de
correo (sin filtro ni truncado es igual a `total` y no hace otra consulta). `/portales` no acepta `correo`.

**CSV de estadísticas:** mismo formato que el del historial. Columnas: Portal (o Usuario y Correo) · Usuarios
únicos (solo portales) · Sesiones · Sesiones medidas · Sin actividad (v14) · Horas totales (texto «52 h 10 min») · Minutos totales
(número entero) · Promedio por sesión (texto) · `Última conexión (hora local, UTC-03:00)`. Archivos
`estadisticas_portales_AAAAMMDD.csv` y `estadisticas_<portal>_usuarios_AAAAMMDD.csv` (`<portal>` en minúsculas sin
tildes, p. ej. `energia`). Más de 5.000 usuarios → `X-Historial-Truncado: 5000`.

La hora local de los CSV usa el desfase del navegador de hoy: en un rango que cruza un cambio de horario, la
«Última conexión» puede correrse 1 h. En pantalla no pasa (convierte el navegador).

## Gráficos de estadísticas (v16)

`/estadisticas` muestra gráficos arriba de las tablas (que no cambian). Todo sale de `core.vHistorialAccesos`
(solo lectura; sesión = fila `Resultado = 'OK'`), sin cambios en la base, los flujos ni Power Pages.

- **General por portal:** tarjetas del «Total Portal Corporativo» (usuarios únicos, sesiones, horas totales y
  promedio), dona del reparto por portal con selector Sesiones / Horas, uso por día (barras apiladas, una serie por
  portal) y horas por portal (barras horizontales).
- **Cada portal** (genérico, sin código por portal): tarjetas del portal, sesiones (barras) y horas (línea) por
  día con dos ejes, top 10 usuarios por horas, cómo terminan las sesiones (dona con la misma prioridad que la columna
  «Cierre»), duración por rangos (`< 5 min`, `5–15`, `15–30`, `30–60`, `> 1 h`; solo sesiones con tiempo, y aparte
  «Sin actividad» y «Sin medir») y mapa de calor día de la semana × hora local.
- **Carga:** cada vista pide y dibuja sus propios gráficos al abrirse (el inicio no carga Chart.js) y los
  recarga al aplicar otras fechas. Cada gráfico se destruye (`chart.destroy()`) antes de redibujarse.
- **Colores:** Energía `#d9a441`, MiraStock `#29b8ec` (único mapa por nombre, en `graficos.js`) y una paleta de 6
  colores elegida por un hash del nombre para portales futuros.
- **Accesibilidad:** cada gráfico tiene un título visible y un `aria-label` con un resumen. El mapa de calor es una
  grilla CSS con la cantidad en el `title` de cada celda.

**Chart.js 4.4.7** va alojado en `app/static/vendor/chart.umd.4.4.7.min.js` (UMD de `chart.js@4.4.7` de
registry.npmjs.org, sha512 verificado contra el registro) con su licencia MIT (`chart.js-LICENSE.md`). Nada se carga
desde un CDN. Funciona con la CSP estricta sin aflojarla: Chart.js 4 no usa `eval` ni `<style>` en línea y fija
los tamaños por CSSOM (`element.style`), que la CSP permite; el mapa de calor usa lo mismo para la intensidad.

```json
GET /api/estadisticas/series?desde&hasta&tz_offset_min[&portal]
{"dias": ["2026-11-01", "2026-11-02", ...],
 "portales": [{"portal": "Energía", "sesiones": [0, 3, ...], "segundos": [0, 5400, ...], "usuarios": [0, 2, ...]}, ...],
 "total": {"sesiones": [...], "segundos": [...], "usuarios": [...]}}

GET /api/estadisticas/distribucion?portal=Energía&desde&hasta&tz_offset_min
{"portal": "Energía",
 "cierres": {"Botón": 4, "Inactividad": 11, "Sin actividad": 1, "En curso": 0, "No medida": 25, "Otro": 0},
 "duracion": {"rangos": [{"etiqueta": "< 5 min", "sesiones": 5}, ...], "sinActividad": 1, "sinMedir": 25},
 "calor": [[...24 valores...], ...7 filas, lunes = 0]}
```

- `/series`: días locales (`DATEADD(minute, tz_offset_min, Fecha)`), rellenos con 0 desde el día de `desde` hasta
  el de `hasta` (exclusivo). Sin alguna fecha, el relleno va del primer al último día con datos. Más de 731 días →
  422 en `hasta`. Sin `portal`, trae todos los portales conocidos (aunque estén en 0) y `total` cuenta los usuarios
  sin repetir entre portales (`GROUPING SETS`); con `portal`, solo ese.
- `/distribucion`: `portal` obligatorio. Rangos en segundos `[0, 300)`, `[300, 900)`, `[900, 1800)`,
  `[1800, 3600)` y `≥ 3600` (exactamente 1 h cae en «> 1 h»). Día de la semana sin depender de `@@DATEFIRST`:
  `DATEDIFF(day, '19000101', día) % 7` (el 1900-01-01 fue lunes → lunes = 0).
- Los dos validan igual que el resto de las estadísticas (422 `{detail, errores}`; 401 sin sesión, antes de validar).
- Validado contra producción el 2026-11-03 (solo lectura): los totales de los dos SQL coinciden con `/portales`.

### Logo y cards del menú (v18)

- **Logo:** `app/static/img/logo-miragroup.png` (240 px) y `logo-miragroup@2x.png` (480 px), PNG transparentes
  generados desde `app/media/logo2.jpg` (el fondo blanco y la sombra pasan a transparencia; el logo conserva sus
  colores). Va en el encabezado de todas las páginas, en el ingreso y en «Tu sesión venció», con `srcset` para
  pantallas de alta densidad y un halo claro (`drop-shadow`) para que la parte azul marino se lea sobre el fondo
  oscuro. Alternativa preparada: la clase `logo-placa` (placa clara redondeada). `app/media/` no se sirve ni se sube
  al repo.
- **Cards del menú de inicio** (`card-menu`, solo las de `/`; 4 desde la v19): gris metálico tipo acero cepillado con
  brillo en el borde superior; el hover sigue igual (sube, brillo cian y sombra).
- **Íconos 3D (v20):** `app/static/img/icono-{estadisticas,contactos,administradores,consulta-bd}.png` (96 px) y
  `@2x` (176 px), PNG con fondo transparente, decorativos (`alt=""`). Se ven a 88 px (72 px en celular), sin recuadro;
  en hover suben, crecen un 6 % y brillan en cian.

### Buscador por correo de los gráficos (v17)

Solo en la vista de cada portal (`/estadisticas/portal/<slug>`); la vista general no cambia.

- **Interfaz:** entre el filtro de fechas y las tarjetas, un campo «Correo» («Contiene…») con «Buscar» (o Enter).
  Con un filtro activo, arriba de los gráficos aparece «Filtrado por: <texto>» con una × que lo quita. El texto
  aplicado se guarda en `sessionStorage` (`mira.estadisticas.correo.portal.<slug>`, una clave por portal, como las
  fechas) y se vuelve a aplicar al cambiar las fechas. Sin coincidencias: tarjetas en 0 y «Sin sesiones que
  coincidan con la búsqueda» en cada gráfico.
- **Qué filtra:** las tarjetas (`/resumen`), sesiones y horas por día (`/series` con `portal`), el top 10
  (`/usuarios`) y cierres, duración y mapa de calor (`/distribucion`). Las pestañas «Usuarios (general)» y
  «Usuarios (detallado)» siguen con sus propios buscadores, independientes.
- **Criterio:** el mismo que `/api/historial`: «contiene», sin distinguir mayúsculas, `%`, `_`, `[` y `\` literales
  (`LIKE ... ESCAPE '\'`), hasta 256 caracteres (más → 422 en `correo`).
- **Tarjetas:** sin filtro siguen saliendo de `/portales`; con filtro, de `GET /api/estadisticas/resumen`, que cuenta
  los usuarios únicos con un `COUNT(DISTINCT Correo)` sobre todo el rango (no sumando días). `/portales` no se tocó.
- `/series` con `correo` y sin `portal` → 422 «Indica el portal para buscar por correo.». Sin `correo`, todos los
  endpoints responden igual que en la v16.

## Consulta de base de datos (v19)

Página `/consulta-bd` (card «Consulta de base de datos» del inicio). **Solo lectura**: no permite crear, editar ni borrar.

- **Lista cerrada de 20 tablas** de `core` (`app/consulta_bd.py`, `TABLAS`): AdministradoresPortal, ColaRecepcion,
  ColaTicketsControl, Contrapropuesta, ContrataDireccion, Descargas, HistorialAccesos, Incidencias, LogConsulta,
  Observados, Propuesta, Registros_SkuComprometido, ReglaClasificacion, ReservasPedido, SesionesAgente,
  SKUComprometido, SolicitudDetalle, Solicitudes, StockLurinERI y UsuariosEntel. Las columnas de cada tabla están
  escritas en el código: una columna nueva en la base no aparece hasta agregarla ahí.
- **Columnas que nunca se piden a la base:** `ContrasenaHash`, `ContrasenaSal`, `AlgoritmoHash`, `IntentosFallidos` y
  `BloqueadoHasta` de AdministradoresPortal (las tres últimas desde la v20), y `Token` de HistorialAccesos,
  SesionesAgente y Descargas.
- **Qué muestra:** los últimos 500 registros según el orden fijo de cada tabla (Id o fecha descendente;
  StockLurinERI por `FechaCarga DESC, Llave`; ContrataDireccion alfabético) y el contador «Mostrando N de TOTAL».
- **Buscador:** un campo que busca «contiene» en **toda la tabla** (hasta 500 coincidencias) en sus columnas de SKU,
  correo y ticket JIRA (y `Solicitante`, `Usuario` o `Referencia` donde existen); la etiqueta nombra las columnas. Si la
  tabla no tiene ninguna, el buscador no aparece. Mismo escape de `LIKE` que el resto de la app.
- **SQL:** se arma al iniciar la app solo con el catálogo; lo único que llega del usuario es la clave de la tabla (se
  busca en la lista) y el texto, que va siempre como parámetro. Textos largos cortados a 300 caracteres + «…»;
  tiempo máximo de 20 s por consulta. Usa la misma conexión de la app (decisión del usuario en la v19).
- **Tipos:** fechas en hora local del navegador (en la base se tratan como UTC), decimales sin ceros de relleno,
  bits «Sí»/«No», NULL «—». La tabla tiene encabezado fijo y scroll horizontal.
- **Log:** la tabla, la cantidad de filas y (v20) el Id del administrador que consultó; nunca el texto buscado.

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

## Latidos de sesión

`POST /api/latido` lo llaman los JS de Power Pages de Energía y MiraStock (cada 2 minutos y al cerrar la pestaña)
para medir cuánto dura cada sesión. Es **público**: no usa `require_admin` ni cookies, y no exige el header
`X-Requested-With` (la autorización va en el body). Esos JS, los flujos, las tablas y la vista los administra el
usuario, no esta app.

- **Body:** JSON de hasta 8 KB, con `Content-Type: application/json` o `text/plain` (para `navigator.sendBeacon`).
- **Límite (v20):** 60 latidos por minuto por IP (la última de `X-Forwarded-For`); el resto responde 429 sin leer el
  body ni tocar la base. Cada usuario late cada 2 min, así que alcanza para unos 120 usuarios detrás de una misma IP.
  - MiraStock: `{"tipo": "mirastock", "t": "<guid de core.SesionesAgente.Token>"}`
  - Energía (desde v10): `{"tipo": "energia", "t": "<guid de core.HistorialAccesos.Token>"}`
  - Energía (modo anterior, sigue aceptado): `{"tipo": "energia", "token": "<token de /_services/auth/token del sitio
    Energía>"}`. Hay que mandar `t` o `token`: los dos juntos, o ninguno, → 400.
  - Campo opcional `"cierre": true` en los dos: el usuario cerró con «Atrás» o «Cerrar sesión» (MiraStock lo manda
    con `sendBeacon`). Si falta o es `false`, es un latido normal; cualquier otro valor (`null`, `"true"`, `1`…) → 400.
- **Sesión viva (v15):** un latido o un cierre solo cuentan si la última actividad registrada fue hace 10 minutos o
  menos: `COALESCE(FinalSesion, CreadoEn)` en MiraStock y `COALESCE(FinalSesion, Fecha)` en Energía por llave
  (`>= DATEADD(MINUTE, -10, SYSUTCDATETIME())`, límite inclusivo). Si pasó más, la sesión ya terminó por inactividad y
  el latido o cierre tardío (PC que despertó, pestaña vieja, JS en caché) se ignora: no mueve `FinalSesion`, no marca
  «Botón» y no renueva la llave. La respuesta sigue siendo 204. Los JS de los portales ya cierran la sesión a los
  30 min sin actividad; esto es la protección del lado del servidor. El modo token de Energía no cambia.
- **MiraStock:** `UPDATE core.SesionesAgente SET FinalSesion = SYSUTCDATETIME()` de esa llave si se creó hace menos
  de 12 h, no está cerrada (`COALESCE(CierreExplicito, 0) = 0`) y sigue viva. Se acepta aunque ya pasó su `ExpiraEn`.
  En el mismo UPDATE (v15) **renueva la llave**: `ExpiraEn` pasa a ahora + 30 min, sin acortarla nunca si ya vencía
  después. El flujo `GenerarAccesoMiraStock` crea las llaves con 30 min. Un latido ignorado por la regla de 60 s
  tampoco renueva. Desde la v20 la renovación tiene tope: nunca pasa de `CreadoEn` + 4 h y una llave que ya venció no
  se renueva (el latido igual registra `FinalSesion`). Así una llave filtrada no se puede mantener viva con latidos.
- **MiraStock con cierre:** sin la regla de 60 s, pone `FinalSesion = SYSUTCDATETIME()`, `CierreExplicito = 1` y
  adelanta `ExpiraEn` a ahora si estaba en el futuro: la llave queda anulada y el agente ya no la acepta. Una sesión ya
  cerrada, o que ya no está viva (v15), no se toca.
- **Energía por llave (`t`, v10):** el flujo `ConsultarAccesoPortal` guarda en `Token` la llave que genera la card
  de Energía, en el mismo INSERT de la fila. El latido hace `UPDATE core.HistorialAccesos SET FinalSesion =
  SYSUTCDATETIME()` de la fila con esa llave, `Portal = 'Energía'`, `Resultado = 'OK'`, `Fecha` de las últimas 12 h
  no cerrada y viva (v15), con la regla de 60 s. El cierre pone además `CierreExplicito = 1`, sin la regla de 60 s,
  y también exige que la sesión siga viva. Con `t` nunca se insertan filas: si no hay fila con esa llave, no hace nada.
- **Energía por token:** el token se valida (RS256, `exp`, emisor) con la clave pública de
  `ENERGIA_PORTAL_URL` (cacheada en memoria), sin exigir audiencia. Con el correo del token, en una sola transacción
  con `UPDLOCK, HOLDLOCK`:
  - toma la fila **más reciente** de `core.HistorialAccesos` de ese correo, `Portal = 'Energía'`,
    `Resultado = 'OK'` y `COALESCE(FinalSesion, Fecha)` de los últimos 30 minutos, esté abierta o cerrada;
  - si está abierta, actualiza su `FinalSesion`;
  - si está cerrada con botón hace 60 s o más, o no hay fila (entró directo por URL o volvió después de 30
    minutos), inserta una fila `OK` con `Fecha = FinalSesion = SYSUTCDATETIME()`;
  - si se cerró hace menos de 60 s, ignora el latido (uno que venía en camino al momento del cierre).
- **Energía por token con cierre:** si esa fila más reciente está abierta, pone `FinalSesion = SYSUTCDATETIME()` y
  `CierreExplicito = 1`. Si ya estaba cerrada o no hay fila, no hace nada (nunca inserta).
- **Regla de 60 s:** si el latido anterior llegó hace menos de 60 segundos, `FinalSesion` no se reescribe (no aplica
  al cierre).
- **Respuestas:** 204 si el latido es válido, aunque no actualice nada (así no revela si una llave existe); 400 si
  el body es inválido; 401 si el token de Energía no valida; 503 si falla la BD o no se puede descargar la clave
  pública de Energía.
- **CORS** (solo en esta ruta): orígenes de `LATIDO_ORIGINS`, solo `POST`, header `Content-Type`, sin credenciales,
  preflight cacheado 10 min. Un preflight o un POST con un `Origin` no permitido responde 403. El resto de la API
  sigue sin CORS.
- **Logs:** la llave y el token nunca se registran, y `/api/latido` no aparece en el access log de uvicorn.

| Variable | Por defecto |
|---|---|
| `ENERGIA_PORTAL_URL` | `https://portalenergia.powerappsportals.com` |
| `LATIDO_ORIGINS` | `https://portalenergia.powerappsportals.com,https://site-oaciopruebas2.powerappsportals.com` |

Mientras alguien tenga abierto Energía o MiraStock, los latidos mantienen activa una réplica del Container App (ver
"Costo mensual estimado").

## Estructura

```
app/main.py       FastAPI: middlewares (sesión, CSRF, headers de seguridad), rutas y estáticos
app/config.py     Configuración (pydantic-settings)
app/auth.py       Login, cookie de sesión, permisos de edición, límite por IP, require_admin y tokens de Energía
app/claves.py     Hash de contraseñas (SHA2_512 y PBKDF2_SHA256) y política
app/db.py         Consultas parametrizadas (pyodbc + ODBC Driver 18)
app/consulta_bd.py Consulta de base de datos de solo lectura (v19): catálogo cerrado de 20 tablas y su SQL fijo
app/mailer.py     msal + Graph sendMail + plantilla HTML del correo
app/externalid.py Cuentas de acceso en External ID (msal + Graph /users)
app/tools/        sync_externalid.py: sincronización inicial de cuentas (se ejecuta en local)
app/docs/         Guía de ingreso en PDF (ya no se adjunta al correo)
app/schemas.py    Validaciones de entrada
app/static/       inicio.html (/), contactos.html + app.js (/contactos), historial.html + historial.js (/historial),
                  estadisticas.html + estadisticas.js (/estadisticas), administradores.html + administradores.js,
                  login.html + login.js, cambiar-contrasena.html + cambiar.js, consulta-bd.html + consulta-bd.js (v19),
                  comun.js (API, avisos, modales, encabezado, política de contraseñas, formatos y descarga de CSV),
                  styles.css, img/logo-miragroup.png + @2x (logo, v18), img/icono-*.png + @2x (íconos del inicio, v20)
app/templates/    error.html (página de error, p. ej. 503 si la BD no responde)
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
- `http://localhost:8000/` sin sesión → redirige a `/login`.

### Probar el ingreso en local

Ingresa en `http://localhost:8000/login` con un administrador de `core.AdministradoresPortal`. El `.env` local apunta
a la base de producción: los intentos fallidos suman al bloqueo real y `UltimoAcceso` se actualiza.

Chrome, Edge y Firefox aceptan la cookie `Secure` en `http://localhost`.

### Tests

```powershell
pytest                                              # todos
pytest tests/test_usuarios.py                       # un archivo
pytest tests/test_login.py::test_cinco_fallos_bloquean_15_minutos   # un test
```

Los tests no usan la BD ni Graph reales: definen su propia configuración y simulan ambos. Bajan las iteraciones de
PBKDF2 para ir rápido (`test_claves.py` comprueba que el código usa 600.000).

---

## Base de datos: usuario dedicado (recomendado)

En vez de usar el administrador del servidor, crea un usuario con permisos mínimos.
Ejecútalo conectado a **CopilotKnowledgeDB** (no a `master`):

```sql
CREATE USER mira_admin_app WITH PASSWORD = '<clave segura>';
GRANT SELECT, INSERT, UPDATE, DELETE ON core.UsuariosEntel TO mira_admin_app;
GRANT SELECT ON core.StockLurinERI TO mira_admin_app;
GRANT SELECT, UPDATE ON core.AdministradoresPortal TO mira_admin_app;   -- v12: login y /administradores
GRANT SELECT ON core.vHistorialAccesos TO mira_admin_app;
GRANT SELECT, INSERT, UPDATE ON core.HistorialAccesos TO mira_admin_app;  -- latidos de Energía (INSERT: modo token)
GRANT SELECT, UPDATE ON core.SesionesAgente TO mira_admin_app;           -- latidos de MiraStock
```

Luego usa `SQL_USER=mira_admin_app` y esa clave en el Container App.

---

## Despliegue en Azure Container Apps

### Despliegue actual

| | |
|---|---|
| **URL pública** | https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io |
| **Ingreso** | `https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io/login` (login propio desde la v12; ver "Cómo funciona el ingreso") |
| Health | `GET https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io/health` → `{"status":"ok"}` |
| Suscripción | CreditosCopilot1 (`38b3f030-c7b5-4d38-822b-c533f88cd34a`) |
| Container App | `ca-mira-admin` en `RG-COPILOT-DEV`, East US |
| Environment (reutilizado) | `managedEnvironment-rgscripth25prod-818f` (`rg-script-h25-prod`, East US) |
| Registro (reutilizado) | `acrscripth25prod.azurecr.io`, imagen `mira-admin-app:v20` (revisión `ca-mira-admin--0000021`, 2026-11-09: correcciones de seguridad e íconos 3D del inicio, `?v=20`). Antes, el mismo día, la v19 (`--0000020`: consulta de base de datos). La v13 no tiene imagen propia: salió dentro de la v14. El próximo tag es `v21` |
| Recursos | 0.25 vCPU, 0.5 GiB, réplicas mín. 0 / máx. 1, ingress externo solo HTTPS (HTTP redirige) |
| Pull de la imagen | Usuario admin del ACR (guardado como secret del Container App). Con rol Contributor no se puede asignar `AcrPull` a una identidad administrada |
| Secrets | `sql-password`, `session-secret`, `graph-client-secret` (secreto de la app "Portal Externo - Envio de correos"), `extid-client-secret` (secreto de la app de External ID) y el del pull del ACR. La v19 y la v20 no agregaron secrets ni variables |
| Correo | `MAIL_ENABLED=true`, `MAIL_SENDER=no-reply@miragroup.cl`, `GRAPH_CLIENT_ID=e722c6e6-d604-4c2d-88ad-01c62a2c9235` (activado el 2026-10-20) |
| Firewall SQL | Regla existente `AllowAllWindowsAzureIps` (0.0.0.0) en `sqlcopilotprd01`, más 10 reglas por IP (revisadas el 2026-11-09; ver "Pendientes de seguridad recomendados") |

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
| Container App `ca-mira-admin` (consumo, 0.25 vCPU / 0.5 GiB, mín. 0 réplicas) | **US$0–3/mes**. Solo cobra mientras hay una réplica activa. Ejemplo: 100 h activas al mes ≈ 90.000 vCPU·s + 180.000 GiB·s, dentro de la cuota gratuita mensual de la suscripción (180.000 vCPU·s, 360.000 GiB·s y 2 millones de requests). Esa cuota la comparten todos los Container Apps de la suscripción; sin ella serían ≈ US$2,70. Desde la v8, los latidos de Energía y MiraStock mantienen la réplica activa mientras alguien use esos portales, así que las horas activas crecen |
| Environment `managedEnvironment-rgscripth25prod-818f` | US$0 adicional (ya existía) |
| ACR `acrscripth25prod` (Basic) | US$0 adicional. Ya se paga (≈ US$5/mes); la imagen ocupa una parte mínima de los 10 GB incluidos. Cada `az acr build` cuesta centavos |
| Logs (Log Analytics del environment) | ≈ US$0. Pocos MB al mes con `LOG_LEVEL=INFO` |
| Azure SQL `sqlcopilotprd01` | US$0 adicional (base existente, consultas livianas) |

Son precios de lista aproximados para East US. Confírmalos en la calculadora de precios de Azure o en Cost Management.

### Pendientes de seguridad recomendados

Revisión de seguridad del 2026-11-09. La v20 corrigió R1, R3, R4, R5, R6, R7, R10, R11 y R16. Siguen abiertos:

- **Prioridad alta:** cambiar la clave de `sqladmin` (se expuso en un chat) y actualizar el secret `sql-password`;
  borrar las reglas de firewall por IP que ya no se usen (incluye dos `QueryEditorClientIPAddress_*`).
- Activar la auditoría de SQL y evaluar Microsoft Defender for SQL (hoy están desactivados; tienen costo).
- Restringir el ingress por IP o poner autenticación de Entra con MFA delante del panel (hoy es externo y sin MFA).
- Fuera del repo (Power Pages / Power Automate, a cargo del usuario): las URL con `sig=` de 3 flujos HTTP están en el
  JS público del chat de MiraStock (regenerarlas y llamarlas desde el servidor); `ConsultarAccesoPortal` toma el
  correo del navegador; los candados de Energía y MiraStock se validan en el navegador; la llave de MiraStock viaja en
  la URL (`?t=`).
- Menores: bloqueo de cuentas usable para negar el servicio, límite por IP en memoria, IP falsificable en el access
  log de uvicorn, imagen base sin digest, `public` con SELECT sobre `core.fn_DiagnosticoStock`.
- Usar el usuario dedicado `mira_admin_app` (ver "Base de datos: usuario dedicado") en vez de `sqladmin`, y cambiar la clave de `sqladmin`.
- La regla `AllowAllWindowsAzureIps` permite conexiones desde cualquier recurso de Azure, también de otros clientes.
  La opción más cerrada es un environment con VNet y un private endpoint al SQL (tiene costo: pedir OK antes).
- Si más adelante se obtiene un rol con permiso para asignar roles (Owner o User Access Administrator), se puede
  pasar de la clave admin del ACR a identidad administrada con `AcrPull`.
