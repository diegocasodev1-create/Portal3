# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Portal3" is a standalone FastAPI app (Python 3.12) serving a vanilla HTML/CSS/JS admin UI. Admins use it to manage rows in the Azure SQL table `core.UsuariosEntel`, which controls access to the MiraGroup Power Pages external portal (Portal1 = Energía, Portal2 = MiraStock, Portal3 = this app). It sends welcome emails through Microsoft Graph.

`brief.md` is the original spec (in Spanish). Some later decisions override it, and they are noted below. `README.md` covers local setup, the API table, the email flow, deployment, logs, mail activation and costs.

## Current status (as of 2026-11-05; v17 and v18 deployed that day)

### v18 (2026-11-05): MiraGroup logo, white sticky header, steel login + metallic menu cards — DEPLOYED
- Asked for by the user. **938 tests pass** (new `tests/test_logo.py`). Static `?v=18` (images too).
- **Logo:** the user put two originals in `app/media/` (`logo1.jpg`, `logo2.jpg`, 2752×1536). Neither is really transparent: `logo1` has a checkerboard painted into the JPG, `logo2` a plain white background. User's choice: `logo2.jpg`.
  - Converted with Pillow (installed only in the scratchpad, not in `requirements`): logo pixels (colour or dark outline) stay opaque with their original colours; only the white background and the grey shadow become transparent (a plain «colour to alpha» washed out the light cyan). Cropped to the content and saved as `app/static/img/logo-miragroup.png` (240×73, ~22 KB) and `logo-miragroup@2x.png` (480×146, ~73 KB), RGBA.
  - `app/media/` is not served (only `/static` is mounted) and is in `.gitignore` and `.dockerignore`. `app/static/logoMG.png` (the old «MG» block) was deleted.
  - Every page (all `app/static/*.html` + `templates/error.html`): `<img src="/static/img/logo-miragroup.png?v=18" srcset="... 1x, ...@2x.png?v=18 2x" width="240" height="73" alt="MiraGroup" class="logo">` in the header, the «Tu sesión venció» card and the login (above «Portal de administración»).
  - CSS: `.logo` height 40 px (32 px in the header at ≤ 480 px), login 64 px (52 px at ≤ 480 px), session card 52 px. Light halo `filter: drop-shadow(...)` (user's choice) so the navy «Mira», ring and «M» stand out from the dark background.
  - **Alternative ready:** `.logo.logo-placa` = light rounded plate, no halo. To switch every page: replace `class="logo">` with `class="logo logo-placa">` in `app/static/*.html` and `app/templates/error.html`, and update `LOGO` in `tests/test_logo.py`.
- **Menu cards:** only the 3 cards of `inicio.html` get `card-menu`: brushed steel (fine `repeating-linear-gradient` lines + grey gradient `#4b5361` → `#1f242c`), top highlight (`inset 0 1px 0`), text `#d0d7e1` (≈ 5.3:1 at the lightest corner), «Entrar →» `#a8e6ff`, icon `#6fd3ff`. Hover/focus keep the v17 behaviour (rise, glow `#9fe3ff`, bigger shadow). The statistics and admin cards are unchanged.
- **Adjustment after the local review (same v18, 2026-11-05):** **940 tests pass** (2 more in `tests/test_logo.py`).
  - **Header (every page with `.encabezado`):** white, `position: sticky; top: 0; z-index: 40` (above content and charts, below `.modal-fondo` 50, `.bloqueo` 80 and `.toasts` 90). Soft shadow underneath that grows over the first 120 px of scroll via a CSS scroll-driven animation (`animation-timeline: scroll(root)` inside `@supports`; other browsers keep the soft shadow). Logo without halo (`.encabezado .logo { filter: none; }`). Title `--claro-titulo` `#0b2545`, admin name `--claro-texto` `#374151`, `btn-fantasma` with dark text and border `--claro-borde` and a cyan glow on hover/focus; focus outline `--claro-foco` `#0b7fae`. At ≤ 480 px it stays sticky but more compact (smaller padding, title 1.05 rem, smaller buttons).
  - **Login:** `<main class="card card-aviso card-ingreso card-plata">`: silver/aluminium gradient (`#f5f7fa` → `#c9d0d9`) with fine brushed lines and a top highlight; the page background stays dark. Logo without halo; title navy, text dark grey, labels `#1f2937`, inputs white with grey border and dark text, eye button dark grey, «¿Olvidaste tu contraseña?» note `--claro-enlace` `#12386b`, error box dark red. «Ingresar» stays cyan. Only the login uses `card-plata`.
  - Contrast of every new text pair is ≥ 4.5:1 (lowest: the focus outline `#0b7fae` on white, 4.5:1; placeholder 5.9:1; error 5.6:1).
- **Second adjustment (same v18, 2026-11-05):**
  - **Login = polished steel bar:** vertical gradient `#8e939a` (top edge) → `#f4f6f8` specular band at ~17 % → `#d9dde2` → `#b8bec6` → `#a3aab3` → `#8b929b` (bottom edge), subtle brushed lines, border `#7d838b`, inner top highlight and inner/outer shadows below for volume. Texts darkened so every one is ≥ 4.5:1 against every stop, including `#8b929b`: title `--plata-titulo` `#081a33` (5.5:1 minimum), text `--plata-texto` `#151c27` (5.4:1), labels `--plata-label` `#0f1520` (5.8:1), note `--plata-enlace` `#0a1f45` (5.2:1); the error box has a solid `#fde8ea` background with `#8f1424` text (7.8:1). Inputs stay white with dark text.
  - **Header buttons** (`.encabezado .btn-fantasma`: «← Inicio», «← Estadísticas», «Cerrar sesión»): blue `#0b5cd6` background and border, bold white text (5.97:1), `min-width: 160px`, padding 8 × 28 px. Hover/focus: `#1767de` (5.2:1) with a cyan border glow and a soft shadow; focus outline `#083f94` (9.8:1 on white), 3 px offset. At ≤ 480 px: `min-width: 120px`, padding 4 × 16 px.
- The halo now only applies where the logo sits on the dark background (the «Tu sesión venció» card and `error.html`); the `logo-placa` alternative is still available.
- The user reviewed all of v18 locally (logo, white sticky header with blue buttons, steel login, menu cards) and approved it on 2026-11-05.
- Commit `67307d8`. Deployed on 2026-11-05 (~13:46 UTC) as image `mira-admin-app:v18`, revision `--0000019`.
  - Checks: `/health` 200; `/login` 200 (serves `card-plata`, `styles.css?v=18` and the logo `srcset`); `/static/img/logo-miragroup.png?v=18` 200 (`image/png`, 22,400 bytes); `@2x` 200; `/static/logoMG.png` 404; startup clean. `--0000019` has 100% of the traffic; `--0000018` (v17) was deprovisioning.
  - Not done by Claude in Azure: a real login and looking at the pages behind it (needs the user's password).


### v17 (2026-11-05): email search for the charts of each portal + visual refresh — DEPLOYED
- Asked for by the user. Only `/estadisticas/portal/<slug>`; the general view and the tabs «Usuarios (general)» / «Usuarios (detallado)» are unchanged (they keep their own searches). No DB, flow or Power Pages changes.
- **919 tests pass** (new `tests/test_buscador_graficos.py`; `test_graficos.test_distribucion_no_acepta_filtro_de_correo` became `..._pasa_el_filtro_de_correo`; the «Contiene…» placeholder count in `test_estadisticas.py` went from 2 to 3). JS checked with esprima. Static `?v=17`.
- User decisions (2026-11-05): a new endpoint `GET /api/estadisticas/resumen` for the filtered cards (`/portales` untouched); `/series` with `correo` and no `portal` → 422 «Indica el portal para buscar por correo.».
- Backend: `db.estadisticas_resumen_portal(portal, desde, hasta, correo)` (one `SELECT COUNT(DISTINCT Correo), {_AGREGADOS_SESIONES}`); `estadisticas_series` / `estadisticas_distribucion` take `correo=None` → `_where_sesiones`. `main._filtros_series` takes `correo`; `_filtros_distribucion` passes it through (v16 forced None). `/distribucion` now returns `correo`.
- Frontend: details under "Charts" in Architecture.
- The user reviewed the search locally and approved it on 2026-11-05, keeping «—» in «Horas totales» / «Promedio» when nothing matches.
- **Visual refresh (same v17, asked for on 2026-11-05; CSS only, plus the arrow `<span>`):**
  - Background of every page (login and `error.html` included): `body` = navy linear gradient + a cyan radial glow at top left + a gold one (`--dorado` `#d9a441`) at bottom right, `background-attachment: fixed`. iOS Safari ignores `fixed` (the background scrolls there).
  - Cards `.card-modulo` (Portal3 home and statistics home) and `.card-admin`: `--card-fondo` gradient + `--card-sombra` at rest. On hover/focus-visible they rise 4 px with border + glow in `--brillo` (cyan; `.card-estadistica` sets it to `--color-portal`, glow via `color-mix` with a cyan fallback) and a bigger shadow, the icon gets a `drop-shadow`, and the arrow `.modulo-flecha` moves 5 px. «Entrar →» is now `Entrar <span class="modulo-flecha">→</span>` (`inicio.html` and `estadisticas-inicio.js`). Titles use `clamp(1.3rem, 1rem + 1.4vw, 1.85rem)` (admins: `clamp(1.2rem, 0.95rem + 1vw, 1.6rem)`), weight 700. Transitions use `--transicion` (0.25 s). With `prefers-reduced-motion` there is no movement, only color, shadow and glow changes.
  - `.btn`: hover and focus-visible get a glowing border (`--brillo-btn`, cyan; `.btn-peligro` uses red) and a soft shadow; focus-visible also has a 2 px outline. `.btn-fantasma` lights up cyan instead of grey.
- The user reviewed all of v17 locally (search + visual refresh) and approved it on 2026-11-05.
- Commit `c1d1f5d`. Deployed on 2026-11-05 (~12:51 UTC) as image `mira-admin-app:v17`, revision `--0000018`.
  - Checks: `/health` 200; `/login` 200 and serves `?v=17`; `/static/styles.css?v=17` 200; `/static/estadisticas.js?v=17` 200 (contains `/api/estadisticas/resumen`); `GET /api/estadisticas/resumen` without a session 401; startup clean. `--0000018` has 100% of the traffic; `--0000017` (v16) was deprovisioning.
  - Not done by Claude in Azure: a real login and using the search with real data (needs the user's password; prod read).

### v16 (2026-11-03): charts in `/estadisticas` (Chart.js) + one page per section — DEPLOYED
- Asked for by the user. Details under "Charts" in Architecture. **810 tests pass** (new `tests/test_graficos.py`). JS checked with esprima (not the vendor file). Static `?v=16`.
- User decisions (2026-11-03): Chart.js hosted in the repo (no CDN); one portal-color map in `graficos.js` (`{"energía": "#d9a441", "mirastock": "#29b8ec"}`, lowercase key) + a 6-color palette by name hash for future portals; `/series` without dates fills between the first and last day with data; 731-day cap; no chart by Cliente for now.
- Chart.js **4.4.7** UMD downloaded from registry.npmjs.org (tarball sha512 checked against the registry's `dist.integrity`), saved as `app/static/vendor/chart.umd.4.4.7.min.js` (sha256 `2812cb88…b632cb`) + `chart.js-LICENSE.md` (MIT). It has no `eval`/`new Function`/inline `<style>`, so the CSP is unchanged.
- Read-only prod check (approved by the user, 2026-11-03): `db.estadisticas_series` and `db.estadisticas_distribucion` ran on Azure SQL and every total matched `db.estadisticas_portales` (last 30 days and all history; Energía 41 sessions, MiraStock 44).
- The user reviewed the charts locally (2026-11-03: «se ven muy bien») and asked, inside the same v16, to drop the accordion: `/estadisticas` becomes a home with cards and each section gets its own page and date filter. Details under "Charts" in Architecture. **866 tests pass** (new `tests/test_estadisticas_vistas.py`). Still `?v=16` (never deployed).
  - User decisions (2026-11-03): `slug` field in `/api/estadisticas/portales` computed and tested in Python; repeated slugs → the second (alphabetical) gets `-2`; «Historial completo» on the home and in each view.
- The user reviewed the new structure locally (cards, views, dates per view, unknown portal, phone width, no CSP errors in the console) and approved it on 2026-11-03.
- Commit `783a819`. Deployed on 2026-11-03 (~13:05 UTC) as image `mira-admin-app:v16`, revision `--0000017`.
  - Checks: `/health` 200; `/login` 200; `/static/vendor/chart.umd.4.4.7.min.js?v=16` 200 (205,615 bytes); `/static/estadisticas-inicio.js?v=16` 200; `/estadisticas`, `/estadisticas/general` and `/estadisticas/portal/energia` without a session → 303 `/login?siguiente=<ruta>`; startup clean. `--0000017` has 100% of the traffic; `--0000016` (v15) was deprovisioning.
  - Not done by Claude in Azure: a real login and opening the statistics pages with data (needs the user's password; prod read).
  - PowerShell 5.1 `Invoke-WebRequest -MaximumRedirection 0` did not surface the 303s; `curl -D -` (Git Bash, `MSYS_NO_PATHCONV=1`) did.

### v15 (2026-11-03): server-side protection against inflated sessions + MiraStock key renewal — DEPLOYED
- Asked for by the user. The MiraStock and Energía JS already close the whole session after 30 min without activity and send no heartbeats without real activity (the user's side); v15 protects against late heartbeats (PC waking up, old tab, cached JS).
- **758 tests pass** (47 new `test_v15_*` in `tests/test_latido.py`; 4 old tests adjusted to live sessions). No static changes (`?v=15` stays). Only SQL in `db.py` changed; `main.py` and responses are unchanged (204 even when nothing is updated).
- «Alive» = last activity ≤ 10 min ago (inclusive): `db._VIVA_MIRASTOCK` = `COALESCE(FinalSesion, CreadoEn) >= DATEADD(MINUTE, -10, SYSUTCDATETIME())`, `db._VIVA_ENERGIA` = `COALESCE(FinalSesion, Fecha) >= ...`. Appended to `_SQL_LATIDO_MIRASTOCK`, `_SQL_CIERRE_MIRASTOCK`, `_SQL_LATIDO_ENERGIA_LLAVE` and `_SQL_CIERRE_ENERGIA_LLAVE`. A late close does not mark «Botón», move FinalSesion or touch ExpiraEn. The Energía token mode (`latido_energia`/`cierre_energia`, 30-min window) is unchanged.
- MiraStock heartbeat also renews the key in the same UPDATE: `ExpiraEn = CASE WHEN ExpiraEn > now+30 THEN ExpiraEn ELSE now+30 END` (never shortens; user's option A, 2026-11-03). A heartbeat skipped by the 60 s rule does not renew.
- Data from the user: the flow `GenerarAccesoMiraStock` creates keys with `ExpiraEn = DATEADD(MINUTE, 30, SYSUTCDATETIME())`; `BDFalsa.agregar_sesion_agente` now defaults to +30 min.
- Commit `0da03b0`. Deployed on 2026-11-03 (~12:12 UTC) as image `mira-admin-app:v15`, revision `--0000016`.
  - Checks: `/health` 200; `/login` 200; `POST /api/latido` with an empty body 400; startup clean. `--0000016` has 100% of the traffic; `--0000015` (v14) was deprovisioning.
  - Not verified against the real DB: a real heartbeat inside/outside the 10-min window or a real key renewal (needs a live MiraStock/Energía session; checking it reads prod).
- Effect at deploy time: open MiraStock sessions start renewing their key with their next heartbeat.

### v14 (2026-11-03): «Sin actividad» / «No medida» sessions — DEPLOYED
- Asked for by the user. One image **v14** will carry v13 + v14 (the user's decision, 2026-11-03); v13 was never deployed on its own. One commit per version.
- Done by the user (Claude must not touch it): `core.vHistorialAccesos` has two new last columns, `Medible` (BIT; Energía: has a key; MiraStock: created after the first recorded heartbeat) and `SinActividad` (BIT; medible, no heartbeat ever, > 5 min). The view already sets `TiempoSesionSeg = 0` when `SinActividad = 1` and `EnCurso = 1` during the first 5 min of a medible session with no heartbeat.
- **711 tests pass** (new `tests/test_sin_actividad.py`). JS checked with esprima. Static `?v=15`.
- `db.listar_historial` reads `ISNULL(Medible, 0)` / `ISNULL(SinActividad, 0)` (NULL Medible = 0, user's decision). `_AGREGADOS_SESIONES` adds `ISNULL(SUM(CASE WHEN SinActividad = 1 ...), 0)` → `sinActividad` per portal, total and user (sum/avg logic unchanged: the 0 s count as measured).
- Texts, identical in UI (`comun.js` `textoCierre`/`textoTiempo`/`textoFinal`, used by `historial.js` and the «detallado» tab) and CSV (`main._texto_cierre`/`_tiempo_csv`/`_final_sesion`):
  - Cierre: Botón → En curso → Inactividad (FinalSesion) → Sin actividad → No medida (Medible = 0) → «—» (empty in CSV).
  - Tiempo: «0 min» (CSV `0`) if SinActividad; else as before («—» / empty when unmeasured).
  - Final: FinalSesion; else Fecha (login time) if SinActividad; else «—» / empty. The «En curso» chip stays.
  - Denegado rows: «—» / empty in all three (user's decision). Existing data wins over `Medible = 0` (same order as Cierre).
- `/estadisticas`: «sin actividad: K» help line under «medidas: N de M» in «General por portal» (only when K > 0); column «Sin actividad» after «Sesiones» in «Usuarios (general)»; CSV column «Sin actividad» after «Sesiones medidas» (portals, total row and users).
- Deployed on 2026-11-03 (~06:21 UTC) as image `mira-admin-app:v14`, revision `--0000015` (v13 + v14 together; commits `41f3292` v13 and `fcc3958` v14). The same update removed `TOKEN_AUDIENCE` from the Container App (approved by the user).
  - Checks: `/health` 200; `/login` 200 and serves `?v=15`; `/static/comun.js?v=15` 200; `/api/me` 401; startup clean. `--0000015` has 100% of the traffic; `--0000014` (v12) was deprovisioning.
  - Not done by Claude in Azure: a real login or opening `/historial` / `/estadisticas` with data (needs the user's password; prod read).
- The user reviewed v13 + v14 together locally and approved them on 2026-11-03 (including keeping existing data over `Medible = 0`).

### v13 (2026-11-03): email search in «Usuarios (general)» of `/estadisticas` — DEPLOYED (inside image v14)
- Asked for by the user. Details under "Statistics" in Architecture.
- **677 tests pass** (new search tests in `tests/test_estadisticas.py`, parametrized over Energía, MiraStock and a new portal). JS checked with esprima. Static `?v=14` (bumped from 13; the code image is still v13).
- Backend: `/api/estadisticas/usuarios` and `/csv` take optional `correo` (same validation and `LIKE` escaping as `/api/historial`, via `_filtros_estadisticas_portal` → `_filtros_historial`). The JSON adds `correo` (applied value or null) and `totalSinFiltro` (`db.contar_usuarios_portal`, only called when there is a filter or truncation; otherwise `len(filas)`). `/api/estadisticas/portales` ignores `correo`. No DB, flow or Power Pages changes.
- UI: same form as «Usuarios (detallado)» (form on top, counter below; user's decision 2026-11-03). Counter «7 usuarios» / «2 de 7 usuarios»; no match → «Sin usuarios que coincidan con la búsqueda» (and «0 de 7 usuarios»). The applied term (set on «Buscar»/Enter) is reused by date changes, «Reintentar» and the CSV export. Each tab keeps its own filter; the portal header meta stays unfiltered.
- Went out inside image v14 (`--0000015`, 2026-11-03); see v14. There is no v13 image.

### v12 (2026-10-30): own admin login + «Centro de administración principal» + Cliente — DEPLOYED
- Asked for by the user. Details under "Identity flow", "Admin center" and "Business rules" in Architecture.
- **634 tests pass** (new: `test_claves.py`, `test_login.py`, `test_administradores.py`; `test_auth.py` rewritten; `test_sin_auth.py` deleted; Cliente tests in `test_usuarios.py`). JS checked with esprima. Static `?v=13` (bumped from 12 during the local review for the password eye button; v12 was never deployed).
- Removed: `/auth/portal`, `/auth/logout`, `AUTH_ENABLED`, `TOKEN_AUDIENCE`, `auth.clave_portal`, `validar_token_portal`, `db.es_admin`, `sin_permisos.html` (`sin_acceso.html` → `error.html`), «Volver al portal», `{{PORTAL_URL}}` in pages. `PORTAL_BASE_URL` stays: `mailer.py` uses it for the link in the welcome email.
- Read-only prod queries C1–C3 (approved by the user, 2026-10-30):
  - `core.AdministradoresPortal`: Nombre nvarchar(150), Correo nvarchar(256) unique `UQ_AdministradoresPortal_Correo`, `AlgoritmoHash` default 'SHA2_512' (no CHECK), `FechaAlta` default sysutcdatetime(), the other dates NULL.
  - `sp_RestablecerContrasenaAdmin` did NOT set `FechaCambioContrasena` → the user got an ALTER (sets it to `SYSUTCDATETIME()`), needed by the 72 h rule.
  - Gerencias: «CONSTRUCCION E INFRAESTRUCTURA DE RED» is only in `core.UsuariosEntel` (1 row); `StockLurinERI` only has «CONST. E INFRA. DE RED» (10,354). The user got an UPDATE; no code change.
  - Cliente by domain: entel.pe → Entel (20), miragroup.cl → MiraGroup (13), gmail.com → Otro (3).
- User decisions (2026-10-30):
  - D1: Portal3 stays in UsuariosEntel only as data; the rules «no puedes quitarte tu Portal3 / eliminarte» are gone.
  - D2: a correct login with SHA2_512 and `DebeCambiarContrasena = 0` migrates the hash to PBKDF2.
  - D3: Cliente suggestion: `entel.pe` → Entel, `miragroup.cl` → MiraGroup, else Otro (JS only; the API just validates the 3 values).
  - D4: the default password only works 72 h from `COALESCE(FechaCambioContrasena, FechaAlta)`; simple in-memory limit per IP (20 / 15 min, login + card verification).
  - D5: inactive admins are listed as «Inactivo» and cannot be opened (blocked ones cannot be opened either).
  - Deploy: change `session-secret` in Azure (scratchpad script) and remove `AUTH_ENABLED` and `PORTAL_BASE_URL` env vars from the Container App (check first that `PORTAL_BASE_URL` equals the code default, or the email link changes).
  - Power Pages: the admin card in the external portal is hidden and its JS commented; nothing calls `/auth/portal`.
- Password eye button (asked during the local review): `comun.js` `prepararOjos(raiz)` wraps every `input[type="password"]` in `.campo-clave` with a `<button type="button" class="btn-ojo">` (SVG eye; `.ojo-tachado` shown when `aria-pressed="true"`; aria-label «Mostrar/Ocultar contraseña»). It runs on load and in `abrirModal`; `ocultarClaves` runs on every form submit (capture listener) and in `cerrarModal`. Focus and caret stay in the input. `/login` now loads `comun.js` too (header code is skipped when `#btn-logout` / `#admin-nombre` are missing).
- The user ran the gerencia UPDATE and the `sp_RestablecerContrasenaAdmin` ALTER, confirmed active admins, reviewed v12 locally (login, password change, admin center, eye button, Cliente) and approved it on 2026-10-30.
- Deployed on 2026-10-30 (~22:28 UTC) as revision `--0000014`:
  - `session-secret` was rotated first (scratchpad script; the value was never printed), so all old sessions are invalid and Azure no longer shares the local secret.
  - `AUTH_ENABLED` and `PORTAL_BASE_URL` were removed from the Container App (`PORTAL_BASE_URL` was equal to the code default). `TOKEN_AUDIENCE` stayed set (ignored) until the v14 update removed it on 2026-11-03.
  - Checks: `/health` 200; `/login` 200; `/` → 303 `/login`; `/administradores` → 303 `/login?siguiente=/administradores`; `/api/me` and `/api/usuarios` 401; `POST /auth/portal` 404; `/api/latido` with an empty body 400; `/static/comun.js?v=13` 200; startup clean. `--0000014` has 100% of the traffic; `--0000013` (v11) was deprovisioning.
  - Not done by Claude in Azure: a real login (needs the user's password).

### v11 (2026-10-30): «Estadísticas del Portal Corporativo MiraGroup» (`/estadisticas`) — DEPLOYED
- Asked for by management: statistics by level, each portal separately. Details under "Statistics" in Architecture.
- **488 tests pass** (`tests/test_estadisticas.py` is new; `test_historial.py` and `test_sin_auth.py` adjusted). JS checked with esprima. Static `?v=11`.
- The user reviewed `/estadisticas` locally (prod DB, `AUTH_ENABLED=false` for the process only) and approved it on 2026-10-30.
- Read-only check against production (approved by the user): `db.estadisticas_portales` matched independent SQL on the view, both for the last 30 days and for all history.
  - Energía: 6 users, 29 sessions, 4 measured.
  - MiraStock: 6 users, 19 sessions, 8 measured.
  - Total: 10 unique users (the sum would be 12), 48 sessions, 36,309 s. There were no `Denegado` rows.
- Commit `0198d2e` (v11). `body.json` is still untracked.
- Deployed on 2026-10-30 (~05:42 UTC) as revision `--0000013`. Checks after the deploy:
  - `/health`, `/`, `/estadisticas` and `/static/estadisticas.js?v=11` returned 200, and startup was clean.
  - `--0000013` (v11) has 100% of the traffic; `--0000012` (v10) was deprovisioning.
  - The `/api/estadisticas/*` endpoints were not called in Azure (prod read without approval); locally they were checked against the prod DB.
- User decisions (2026-10-30):
  - Unique users count only users with OK sessions.
  - Show the help text «medidas: N de M».
  - The per-portal detailed view has table, filters and CSV only; indicators and chart stay in `/historial`.
  - The CSVs have «Horas totales» (text) + «Minutos totales» (number). Every CSV, including `/historial`'s, uses local time via `tz_offset_min`, and the column header says so.
  - `/historial` stays as is, with no card on the home page. It links to `/estadisticas`, and `/estadisticas` links back with «Historial completo».
- Levels 3/4 (funcionalidades / subfuncionalidades) are planned but not built. They will be a new entry in `SUBVISTAS` in `estadisticas.js` plus their own endpoint and data source.

### v10 (2026-10-29): Energía heartbeat by key (`{"tipo":"energia","t":<guid>}`) — DEPLOYED
- **400 tests pass** (35 new in `tests/test_latido.py`). No static changes, so `?v=9` stays.
- Commits: `1a7e105` (pending v9 docs) and `e200a24` (v10). `body.json` is still untracked.
- Deployed on 2026-10-29 (~21:50 UTC) as revision `--0000012`. Checks after the deploy:
  - `/health` returned 200, and startup was clean.
  - v10 has 100% of the traffic; `--0000011` (v9) was still active with 0% right after the deploy.
  - `/api/latido` with `{"tipo":"energia","t":"x"}` returned 400 «La llave de sesión no es válida.».
- Not verified against the real DB: a real Energía heartbeat or close by key.
- Done by the user (Claude must not touch them):
  - `core.HistorialAccesos.Token UNIQUEIDENTIFIER NULL` with index `IX_HistorialAccesos_Token`.
  - The flow `ConsultarAccesoPortal` stores the key generated by the Energía card in `Token`, in the same INSERT.
  - The Energía Header sends `{"tipo":"energia","t":...}` (heartbeat) and `...,"cierre":true` (sendBeacon). It no longer uses the Power Pages token.
- User decisions (2026-10-29): both key UPDATEs also filter `Resultado = N'OK'`; the token mode stays as it is (no Header uses it now).

### v9 (2026-10-29): explicit session close (`"cierre": true` in `/api/latido`) — DEPLOYED
- **365 tests pass** (42 new). JS checked with esprima. The user skipped the browser review.
- Commit `a31cf3e` holds v8 + v9 together. They could not be split cleanly because v9 edited the same files. `body.json` is still untracked.
- The user ran `cierre_sesion.sql`: the `CierreExplicito` columns and the view are in production.
- Deployed on 2026-10-29 (~19:55 UTC) as revision `--0000011`. Checks after the deploy:
  - `/health` returned 200, and startup was clean.
  - v9 has 100% of the traffic.
  - `/api/latido` returned 400 for an empty body and for `"cierre":1`.
  - `/historial` serves `?v=9` and the «Cierre» column.
  - The access log showed `/health` and `/historial` but not the `/api/latido` POSTs, so the filter works in production.
- Not verified against the real DB: a real close or heartbeat, including the Energía `UPDATE ... OUTPUT INTO` batch. That branch first runs with the next real Energía heartbeat.
- Done by the user (Claude must not touch them):
  - `CierreExplicito BIT NULL DEFAULT 0` in `core.HistorialAccesos` and `core.SesionesAgente`.
  - The view returns `CierreExplicito` (last column), and `EnCurso` is 0 when it is 1.
  - The MiraStock page sends `{"tipo":"mirastock","t":...,"cierre":true}` by `sendBeacon` (text/plain) on «Atrás» / «Cerrar sesión».
  - The Energía close will be used in "Phase 4" (not sent yet).
- User decisions (2026-10-29):
  - The Energía "active row" is the MOST RECENT row in the 30-min window, open or closed; the state decides after that.
  - A normal Energía heartbeat is ignored if that row was closed less than 60 s ago.

### v8 (2026-10-29): session heartbeats (`POST /api/latido`) — DEPLOYED
- **323 tests pass** (93 new in `tests/test_latido.py`, plus new columns/indicators in `tests/test_historial.py`). JS checked with esprima.
- The user reviewed `/historial` locally (against the prod DB, `AUTH_ENABLED=false` for the process only) and approved it on 2026-10-29.
  - The local check against the real view: listado, resumen and CSV returned 200 with the new fields. There were 15 accesses in the last 7 days, none with heartbeats yet.
  - «En curso» and durations like «1 h 05 min» have not been seen with real data; only the tests cover them.
- Deployed on 2026-10-29 (~18:37 UTC) as revision `--0000010`. Checks after the deploy:
  - `/health` returned 200, and startup was clean.
  - `--0000010` (v8) has 100% of the traffic, and `--0000009` was deactivated.
  - `POST /api/latido` returned 400 for an empty body and for `{}`.
  - The preflight from `https://portalenergia.powerappsportals.com` returned 204 with ACAO, and from a disallowed origin it returned 403.
  - No real heartbeat (MiraStock key or Energía token) has been sent to production yet.
- Done by the user (Claude must not touch them):
  - `FinalSesion DATETIME2(0) NULL` (UTC) in `core.HistorialAccesos` and `core.SesionesAgente`.
  - `core.vHistorialAccesos` returns `FinalSesion`, `TiempoSesionSeg` and `EnCurso`.
  - Indexes `IX_HistorialAccesos_Correo_Fecha` (Correo, Fecha DESC) INCLUDE (Portal, Resultado) and `IX_SesionesAgente_Token`.
  - Expired `SesionesAgente` rows are no longer deleted.
  - The Power Pages JS (Energía and MiraStock) that sends the heartbeats every 2 minutes, plus `sendBeacon` on close. The user pastes it into Power Pages.
- After deploying: `ENERGIA_PORTAL_URL` and `LATIDO_ORIGINS` have code defaults, so no env change is needed unless the origins change.

### What happened after the v6 deploy (from Log Analytics and Graph)
- 2026-10-23, all from the user's IP:
  - 17:05 and 17:46 UTC: users Id 51, 52, 53 and 54 were deleted.
  - 17:11: user Id 55 was created. Its new code account is `9aff2b59-c702-43d3-9ced-78b142c0a100` (`diego.caso@miragroup.cl`, federated/mail). «Enviar correo» returned 200.
  - 17:47: user Id 56 was created, a new email with code account `767daab3-4637-4133-81f7-f9919df19a93` (federated/mail). «Enviar correo» returned 200, then a PUT followed.
- 2026-10-26 19:14: PUT on user Id 55.
- **The legacy password accounts are gone.** `17848@senati.pe` (`73310320-…`) and `diego.caso@miragroup.cl` (`0ac3f5d7-…`) no longer exist, and the recycle bin is empty. `17848@senati.pe` has no account of any type now.
- `diegocaso.dev1@gmail.com` still has ONE account (`485b9597-…`, federated/mail). It was not created from the app, so it presumably still has no DB row.
- All accounts created since 2026-10-23 are federated/mail with `passwordPolicies` null.
- **Self-service sign-up is OFF.** User flow `registro-inicio-portales` (`4d198f40-3ed6-4700-9eaa-13e2e31171dc`) has `isSignUpAllowed: false`, so External ID accounts come only from this app (or the sync).
  - The PATCH payload is the untracked `body.json` in the repo root. Whether to keep, delete or ignore it is undecided.

### v7 (2026-10-28): home page + «Logs control de ingresos» — DEPLOYED
- `/` is now the home page with two cards, `/contactos` is the user admin (moved unchanged) and `/historial` is the new read-only access log. Details under "Pages" and "Access history" in Architecture.
- **222 tests pass** (84 new in `tests/test_historial.py`). JS checked with esprima.
- The user reviewed `/`, `/contactos` and `/historial` in a browser (locally, against the prod DB) and approved them on 2026-10-28.
- Deployed on 2026-10-28 as revision `--0000009`. `/health`, the three pages and the new JS files return 200, and startup was clean.
- **Where the access rows come from** (all owned by the user; Claude must not create or change tables, views, flows or Power Pages files):
  - The user created `core.HistorialAccesos` and the view `core.vHistorialAccesos` in CopilotKnowledgeDB on 2026-10-28.
  - CHECK constraints on `core.HistorialAccesos`: `Portal IN (N'MiraStock', N'Energía')` and `Resultado IN (N'Denegado', N'OK')`.
  - The view is a `UNION ALL` of two branches. Both take `Usuario` from `core.UsuariosEntel` via `LEFT JOIN` on the lowercased, trimmed correo.
    - Branch 1 reads `core.HistorialAccesos` as is, with no filter.
    - Branch 2 reads `core.SesionesAgente`. Each generated key counts as one access, shown as `N'MiraStock'` / `N'OK'`, with `Fecha = CAST(CreadoEn AS DATETIME2(0))`.
  - **Energía:**
    - Clicking the Energía card on the external portal's Home calls the Power Automate flow `ConsultarAccesoPortal` with `{correo, destino: 'Energia'}`. The Home redirects even if the flow fails or takes longer than 3 s.
    - With `destino = 'Energia'`, the flow inserts a row into `core.HistorialAccesos`: Correo, `Portal = 'Energía'`, `Resultado` OK or Denegado depending on `Portal1`, and Fecha in UTC. `destino` is an optional input of the flow.
    - Tested on 2026-10-28: the row appears in `/historial`.
  - **MiraStock** is logged automatically through `core.SesionesAgente`. Nothing writes to `HistorialAccesos` for it.
  - `Fecha` and `Correo` are nullable in the view. The API returns `null` for them and the CSV leaves the cell empty.

### Session of 2026-11-05 (closed): v17 → v18 in production
- **v17** (`--0000018`, commit `c1d1f5d`): email search («contiene») for the cards and charts of each portal view (`GET /api/estadisticas/resumen`, `correo` in `/series` with portal and in `/distribucion`; `/series` with `correo` and no portal → 422), plus a visual refresh (dark gradient background with cyan/gold glows, cards with gradient/shadow/glow, buttons with glow).
- **v18** (`--0000019`, commit `67307d8`): MiraGroup logo from `app/media/logo2.jpg` (`app/static/img/logo-miragroup.png` + `@2x`; `logoMG.png` deleted), white sticky header with blue buttons, login as a polished steel bar, metallic menu cards on `/`.
- Docs commits `c45a669` (v17 state), `b3abd00` (v18 state) and this closing commit, all pushed to `origin/main`. **940 tests pass.** Static files at `?v=18`; the next image is **v19**.
- Claude did not log in to Azure in this session (needs the user's password): every visual check there is PENDIENTES 1.
- To regenerate the logo: Pillow is NOT in `requirements*.txt`; install it into a scratch dir (`pip install --target <dir> Pillow`) and redo the conversion described under v18 (logo pixels opaque, only the white background and grey shadow to alpha; crop; 240/480 px). `app/media/` (the originals) exists only on the user's machine: it is in `.gitignore` and `.dockerignore`.

### Session of 2026-11-03 (closed): v13 → v16 in production
- **v13** (inside image v14): email search («contiene») in «Usuarios (general)» of each portal; `totalSinFiltro` in `/api/estadisticas/usuarios`.
- **v14** (`--0000015`): «Sin actividad» / «No medida» from the view's `Medible` / `SinActividad`; Cierre priority Botón → En curso → Inactividad → Sin actividad → No medida; `sinActividad` counts in statistics and CSVs; `TOKEN_AUDIENCE` removed from the Container App.
- **v15** (`--0000016`): 10-min «alive» window for MiraStock and Energía-key heartbeats and closes (late ones are ignored); a MiraStock heartbeat renews `ExpiraEn` to now + 30 min without shortening it.
- **v16** (`--0000017`): charts with Chart.js 4.4.7 (hosted, CSP unchanged), `/api/estadisticas/series` + `/distribucion`, `/estadisticas` as a cards home with `/estadisticas/general` and `/estadisticas/portal/<slug>` (own date filter per view, `slug` in `/portales`).
- Commits from `41f3292` (v13) to the closing commit of this session, all pushed to `origin/main`. **866 tests pass.** Static files at `?v=16`; the next image is **v17**.

### PENDIENTES (next session)
1. **Verify v16–v18 in Azure with the user's login** (Claude has not logged in to Azure):
   - v18: logo in the header of every page, white sticky header over the charts and under the modals, blue header buttons, steel login (including an error message), metallic menu cards, phone width.
   - v17: the email search in a portal view (cards, charts and Top 10 filtered; chip «Filtrado por»; no match; remembered per portal), the dark background, cards and buttons.
   - v16: `/estadisticas` (cards), `/estadisticas/general` and a portal view with real data (charts, tables, tabs, date filter per view).
   - In every page: the browser console free of CSP errors.
2. **Verify with a real session** (MiraStock and Energía) that the JS close after 30 min of inactivity leaves the session at its last activity with Cierre «Inactividad», and that a heartbeat outside the 10-min window is ignored (v15). Checking it in `/historial` or by SQL is a prod read: ask the user first.
3. **Levels 3/4:** catalog of funcionalidades (level 3) and subfuncionalidades (level 4) per portal, when management defines it (and where the data will come from; nothing exists yet in the DB). It will be a new entry in `SUBVISTAS` in `estadisticas.js` plus its own endpoint.

### Next session: start here
- Start with **PENDIENTES** above. The older items below are still open unless noted.
- **v12 deployed on 2026-10-30.** Ask the user whether login, password change and `/administradores` work in Azure (Claude did not log in there). Each admin with the default password must change it within 72 h.
- **Session closed on 2026-10-30** after the v12 deploy; commits `13e114b` (v12 code), `77f756e` (docs) and its closing commit were pushed to `origin/main`.
- **Session closed on 2026-11-05** after the v18 deploy (`--0000019`): see "Session of 2026-11-05" and PENDIENTES 1.
- **v16 deployed on 2026-11-03** (`--0000017`): see PENDIENTES 1.
- **v15 deployed on 2026-11-03** (`--0000016`). With the user's OK (prod read), check in `/historial` that new MiraStock/Energía sessions no longer get inflated by late heartbeats, and that MiraStock users are not cut off from the agent after 30 min while active (key renewal).
- **v13 + v14 deployed on 2026-11-03** (image v14, `--0000015`). Ask the user whether the email search in «Usuarios (general)» and the «Sin actividad» / «No medida» texts look right in Azure with real data. `TOKEN_AUDIENCE` is gone from the Container App.
- `cracion_usuario.txt` (repo root) is the user's local file with the `sp_CrearAdministrador` EXECs (no passwords, per the user). It is in `.gitignore`; Claude must not open, delete or commit it. `body.json` is still untracked and undecided.
- **v11 follow-ups:**
  - With the user's OK (prod read), open `/estadisticas` in Azure and check that `/api/estadisticas/portales` and `/usuarios` answer 200 with the same totals as the local check.
  - Levels 3/4: see PENDIENTES 3.
0. **v8–v10 heartbeats:** ask the user whether the Power Pages JS (Energía Header with `t`, and MiraStock) is published. Then check in `/historial` that `FinalSesion` / «Tiempo de sesión» fill in for Energía and MiraStock, and that «Atrás» / «Cerrar sesión» shows «Botón» in «Cierre». A Log Analytics query for errors on `/api/latido` is possible: the app logs only errors there, never the key or token, and the access log excludes the route. Each query needs the user's OK.
1. **Ask the user** whether the welcome emails for Id 55 and 56 arrived and whether code-only sign-in worked for them. Not verified by Claude.
2. **Sync** (`python -m app.tools.sync_externalid`): there is no evidence it was ever run.
   - It is safe now: the v6 External ID logic is unchanged in v7, locally and in Azure.
   - Order: dry run first, the user reviews, then `--apply`. Each run needs the user's OK (it reads the production table).
3. **senati.pe never received the welcome email** (Graph 202 both times on 2026-10-23). TI needs a Message trace. See "Mail delivery" below.

### Deployment
- URL: https://ca-mira-admin.agreeablemushroom-64620b1a.eastus.azurecontainerapps.io
- Revision mode `Single`: traffic follows the latest revision, and no older one is kept for rollback.
- **Running: image v18, revision `ca-mira-admin--0000019`, with own login (always on), `MAIL_ENABLED=true`, `EXTID_ENABLED=true`.** It was deployed at ~13:46 UTC on 2026-11-05. `/health` is OK and startup was clean. It has 100% of the traffic; `--0000018` (v17) was deprovisioning right after the deploy. `ENERGIA_PORTAL_URL`, `LATIDO_ORIGINS`, `PORTAL_BASE_URL` and `TOKEN_AUDIENCE` are not set in Azure, so the code defaults apply. The next image is **v19** (static files are at `?v=18`; bump to `?v=19` if they change).
- Image history:
  - v3: auth off.
  - v4: External ID + PDF attachment.
  - v5: no attachment (`--0000005`; `--0000006` = v5 with `EXTID_ENABLED=false`).
  - v6: federated/mail accounts + 409 for legacy accounts (`--0000007` with External ID off, `--0000008` with it on).
  - v7: home page + `/contactos` + `/historial` (read-only access log) (`--0000009`).
  - v8: session heartbeats `POST /api/latido` + session time in `/historial` + `?v=8` cache busting (`--0000010`).
  - v9: explicit close (`"cierre": true`), «Cierre» column + «Cerradas con botón» indicator, `?v=9` (`--0000011`).
  - v10: Energía heartbeat/close by key `t` (`core.HistorialAccesos.Token`), no static changes (`--0000012`).
  - v11: `/estadisticas` + `/api/estadisticas/*`, generic portal filter, local-time CSVs, `?v=11` (`--0000013`).
  - v12: own admin login (`core.AdministradoresPortal`), `/administradores`, Cliente, password eye button, `?v=13` (`--0000014`).
  - v13: email search in «Usuarios (general)» (`?v=14`; never built as its own image).
  - v14: v13 + «Sin actividad» / «No medida», `sinActividad` counts, `?v=15`; `TOKEN_AUDIENCE` removed (`--0000015`).
  - v15: 10-min «alive» window for MiraStock and Energía-key heartbeats/closes + MiraStock key renewal, no static changes (`--0000016`).
  - v16: charts in `/estadisticas` (Chart.js 4.4.7 hosted), `/api/estadisticas/series` + `/distribucion`, cards home + `/estadisticas/general` and `/estadisticas/portal/<slug>`, `slug` in `/portales`, `?v=16` (`--0000017`).
  - v17: email search for the charts of each portal (`/api/estadisticas/resumen`, `correo` in `/series` and `/distribucion`) + visual refresh (background, cards, buttons), `?v=17` (`--0000018`).
  - v18: MiraGroup logo (`app/static/img/`), white sticky header with blue buttons, steel login, metallic menu cards, `?v=18` (`--0000019`).
- **az CLI** is logged in to both tenants (`e3112796-…` workforce/subscription, `cb938793-…` External ID), and the active one can switch. Before az commands on Azure resources, run `az account set --subscription 38b3f030-c7b5-4d38-822b-c533f88cd34a`.
- Logs older than the current replica (it scales to 0): Log Analytics workspace `d8a192a1-91f6-4add-882c-d1396d044ba0`, table `ContainerAppConsoleLogs_CL`, via `az monitor log-analytics query`. The app logs the user Id and the External ID account id, never the email.

### Auth
- **v12 (not deployed yet): own login** against `core.AdministradoresPortal`, always on. See "Identity flow".
- Deployed in Azure since 2026-10-30 (`--0000014`); `AUTH_ENABLED` no longer exists.
- Admins are created/reset only by SQL (`core.sp_CrearAdministrador`, `core.sp_RestablecerContrasenaAdmin`; default password `Admin@123456`). Claude must not create or change them.

### Mail
- **ON since 2026-10-20:**
  - Settings: `MAIL_ENABLED=true`, `MAIL_SENDER=no-reply@miragroup.cl`, `GRAPH_CLIENT_ID=e722c6e6-d604-4c2d-88ad-01c62a2c9235`.
  - The secret `graph-client-secret` exists only in Azure.
  - The local `.env` has no Graph secret and keeps `MAIL_ENABLED` unchanged.
- **The email has no attachment** since v5 (the user's decision). The PDF guide stays in `app/docs/` unused. The template text is the user's final code-only version.
- **Sender name:** it shows "No - Reply". The fix is on TI's side: `Set-Mailbox -Identity no-reply@miragroup.cl -DisplayName "Miragroup Corporativo"`. The payload sends no `from`.
- **Mail delivery:** two sends to `17848@senati.pe` (14:42 and 14:50 UTC, 2026-10-23) got Graph 202 but never arrived.
  - senati.pe's MX is Exchange Online, so a quarantine at the recipient's EOP is likely.
  - The app cannot see Sent Items: `saveToSentItems=false`, and the mail app has no read permission.
  - Needs a TI Message trace (sender `no-reply@miragroup.cl`) and a check of the no-reply inbox for bounces.

### External ID (tenant "MiraGroup Externos", `cb938793-21a7-440f-9787-2d3924b3fd67`)
- App registration `35d28c4c-144c-4e3c-9b37-0f0ae4970625` ("Admin Usuarios - Creacion de cuentas") has `User.ReadWrite.All`.
  - `/users/{id}/authentication/*` returns 403, so authentication methods cannot be read.
  - Its secret is in Container App secret `extid-client-secret` and in the local `.env`. The user loaded both with the scratchpad script.
- **Local `.env` has `EXTID_ENABLED=true` and the secret.** The local UI and the sync tool create, rename and delete real accounts.
- **Key finding (2026-10-23): only `{"signInType":"federated","issuer":"mail"}` accounts sign in with the code only.**
  - The v4/v5 code created `emailAddress` + random-password accounts, because Graph rejects `emailAddress` without `passwordProfile` (400 `Request_BadRequest`).
  - The portal asked those accounts for a password. Microsoft documents that existing password users keep being prompted for a password.
  - A Graph-created federated/mail account (`diegocaso.dev1@gmail.com`, `485b9597-…`) matched a self-registered one field for field. The user confirmed it signs in with the code only.
- **v4/v5 bug, fixed in v6:** `buscar_por_correo` only filtered by the domain issuer. It missed federated/mail accounts and could have duplicated them with a password.
- Details of the v6 logic are under "External ID" in Architecture.

### Verified / not verified
- Verified:
  - The portal public key loads (local and Azure).
  - `/health`, the no-session page, and the 401/404 checks pass.
  - **940 tests pass** (v18, locally; `tests/test_sin_auth.py` no longer exists).
  - v11 statistics match independent SQL on the production view (2026-10-30).
  - Code-only sign-in with a federated/mail account works.
  - Welcome emails arrive at other domains (per the user).
- Not tested yet:
  - v12 login against the real `core.AdministradoresPortal` (in particular that the Python SHA2_512 matches `HASHBYTES` for a real row).
  - The UI in a real browser beyond the user's own use.
  - v6 create + «Enviar correo» end to end: the app side worked for Id 55 and 56 (federated/mail account created, Graph 200 response). Delivery and code sign-in still need the user's confirmation.

### Pending on the user / TI
- TI: change the sender DisplayName, and run the senati.pe Message trace.

### Notes
- `64.76.106.60` is the public IP of the user's network, which this machine also uses. Visits from it in the logs are the user's or Claude's.
- Scratchpad helper scripts (read-only Graph lookups, account comparison, SQL row read, the secret loader) live in the session scratchpad. They are not part of the repo.

### Recommended security follow-ups (not done)
- Switch from `sqladmin` to a dedicated `mira_admin_app` DB user (SQL is in the README) and rotate the `sqladmin` password, which was exposed in chat.
- The SQL firewall uses the pre-existing `AllowAllWindowsAzureIps` rule.

## Working agreement

- Show a short plan (files and steps) and wait for the user's OK before writing code. Deliver complete files.
- Use neutral Spanish in the UI, API messages (`{"detail": "..."}`), comments and replies to the user.
- **The user approves each command** that touches the DB or Azure.
  - Auto mode's classifier blocks production DB reads ("Production Reads"). When it does, explain why and let the user decide; do not work around it.
  - **Never create Azure resources that have a cost without an explicit OK.** Reuse the existing environment, ACR and SQL.
  - Claude's shell is non-interactive: `Read-Host` cannot prompt. To enter a secret, write a script to the scratchpad that reads it with `Read-Host -AsSecureString`, discards the az output and prints only success or failure. The user runs it in their own PowerShell window.
- Never print secrets from `.env`, ACR credentials or Container App secrets. Show only secret *names*. Scripts that need secrets read them from `.env` inside the script and keep them out of the output.
- Do not create or modify Power Pages files. The user handles the portal.
- The frontend uses no frameworks or external JS/CSS libraries. The only external resource is the Google Fonts Exo 2 font. The logo is `app/static/img/logo-miragroup.png` (+ `@2x`); `app/media/` holds the originals and is never served or committed.

## Architecture (cross-cutting points)

- **Identity flow (v12, own login; `/auth/portal` and `AUTH_ENABLED` no longer exist):**
  1. `/login` (public, `login.js`, no `comun.js`) posts `{correo, contrasena}` to `POST /api/auth/login` (CSRF headers required). Pydantic `Ingreso` lowercases/trims the email and never trims passwords.
  2. `auth.autenticar`: unknown email, `Activo = 0` or `Bloqueado` → `claves.gastar_tiempo` (a throwaway PBKDF2, so timing does not reveal emails) + `CredencialesInvalidas`; else `auth.comprobar_contrasena`.
  3. `comprobar_contrasena` (shared with the cards and the change endpoint): wrong → `db.registrar_fallo_admin` (5 → `BloqueadoHasta` = +15 min; a failure after an expired lock restarts at 1; no counting while locked) and `CredencialesInvalidas`; right but `DebeCambiarContrasena` and `PorDefectoVencida` (72 h) → `ContrasenaPorDefectoVencida`; right → `registrar_exito_admin` (0 attempts, unlock, `UltimoAcceso` only on login) and, if SHA2_512 and not `DebeCambiar`, `migrar_hash_admin` (UPDATE guarded by `ContrasenaHash = old`).
  4. All login failures → 401 «Correo o contraseña incorrectos.» (the expired default password has its own message). 429 when `auth.limite_intentos` (20 / 15 min per IP, last `X-Forwarded-For` entry, since uvicorn trusts all proxies) is exceeded.
  5. Success → JSON `{redirect, debeCambiarContrasena}` (`?siguiente=` only internal paths via `main._siguiente_seguro`) + cookie `mira_admin_sesion` = itsdangerous `{id, h}`, `h` = `auth.huella(hash)` (HMAC-SHA256 with `SESSION_SECRET`, 32 hex). HttpOnly, Secure, SameSite=Lax.
  6. Middleware `sesion` only checks the signature (`request.state.sesion`) and renews the cookie on every valid response, unless the response already sets it (login, logout, password change) or is 401/403 or `/static/`.
  7. Pages (`main._pagina_protegida`): no cookie → 303 `/login?siguiente=<path>`; `auth.admin_de_sesion` reads the admin by Id and requires `Activo` and a matching huella, else 303 `/login` + cookie deleted; `DebeCambiarContrasena` → 303 `/cambiar-contrasena`; DB error → `error.html` 503.
- **Hashes (`app/claves.py`):** `SHA2_512` = `sha512(sal + clave.encode("utf-16-le"))` (what the SQL SPs produce); `PBKDF2_SHA256` = `pbkdf2_hmac("sha256", utf-8, sal32, ITERACIONES_PBKDF2 = 600_000)`, 32 bytes. `verificar` uses `hmac.compare_digest`, rejects > 128 chars and unknown algorithms. Policy `error_politica`: ≥ 10, ≤ 128, upper, lower, digit, symbol (not letter/digit/space), ≠ `Admin@123456`; "≠ current" is checked by each endpoint AFTER verifying the current password (otherwise it is a guessing oracle). `comun.js` mirrors the policy (`errorContrasena`, `marcarReglas`).
- **Authorization:** `auth.require_sesion` (admin with valid session, even if it must change the password; used by `/api/me` and `/api/auth/cambiar-contrasena`) and `auth.require_admin` (also raises `CambioContrasenaRequerido` → 403 `{detail, cambioRequerido: true}`; `comun.js`/`app.js` redirect to `/cambiar-contrasena`). Both re-read the admin in SQL on every request (cached in `request.state.admin`), so deactivating, deleting or changing/resetting the password cuts the session at once (401). Handlers take `admin: dict`.
- **Admin center (`/administradores`, v12):** `GET /api/administradores` (never hash/salt; `estado` activo/bloqueado/inactivo, `esYo`). `POST /{id}/verificar` with that admin's password → `auth.crear_permiso` (itsdangerous with its own salt, 300 s, `{d: target Id, p: session admin Id, h: target huella}`); wrong → 422 on `contrasena` and counts for THAT admin's lock; locked 423; inactive 403. `PUT /{id}` requires `auth.permiso_valido` (else 403 `{detail, permisoVencido: true}`), validates nombre (≤ 150)/correo (409 if taken), optional `nuevaContrasena` + `confirmacion` (policy, ≠ current checked against the hash since the permit proves knowledge). A new password closes that admin's other sessions; editing yourself re-issues your cookie. `administradores.js` keeps the permit in memory only and drops it when the ficha closes (`Mira.abrirModal(modal, foco, alCerrar)`).
- **Tests (v12):** `conftest.BDFalsa.admins` + `agregar_admin(...)` reproduce the SQL rules with `bd.ahora`; admin Id 1 = `ADMIN` / `CLAVE_ADMIN` (PBKDF2). Autouse `iteraciones_rapidas` lowers PBKDF2 to 1,000 (a test checks the source says 600_000) and `sin_limite_previo` clears the IP limiter. `cliente_admin` uses `poner_sesion` (signed cookie, no login); `ingresar(cliente, ...)` calls the login.
- **CSRF:** POST/PUT/PATCH/DELETE on `/api/*` require `Content-Type: application/json` and `X-Requested-With: mira-admin`. Otherwise the app returns 403. **Only exception: `/api/latido`** (public, no cookies, auth in the body).
- **Security headers:** Strict CSP (`script-src 'self'`; no inline scripts or `style=""` attributes in HTML), `nosniff` and `Referrer-Policy: no-referrer`. Never log tokens, cookies or bodies; claim *names* only at DEBUG. `main.py` forces the msal/httpx/httpcore loggers to WARNING.
- **DB (`db.py`):** pyodbc with ODBC Driver 18 and parameterized queries only. NULL bits count as 0. Correo is lowercased and trimmed.
  - The real schema is in the `db.py` docstring. `Apellido` is `NOT NULL`, so an empty apellido is stored as `''`.
  - Duplicate emails: the app pre-checks, and also catches unique-index errors 2627/2601 on `UQ_UsuariosEntel_Correo`. Either way it returns 409.
- **Gerencia is not free text.** The MiraStock agent compares it against `core.StockLurinERI.Gerencia`. Valid values are the sorted `UNION` of distinct Gerencia from both tables. The API matches the input case-insensitively but stores the DB's exact spelling.
- **Create and email are separate.** This overrides brief §4/§5.
  - `POST /api/usuarios` inserts (`Activo=1, InvitacionEnviada=0`) and ensures the External ID account. It returns `{usuario, mensaje: "Usuario creado.", avisoCuenta: false}`. No email is sent.
  - `POST /api/usuarios/{id}/enviar-correo` handles both the first send and resends. It ensures the External ID account first. On success it sets `InvitacionEnviada=1` and returns `{correoEnviado: true, mensaje: "Correo enviado a <correo>."}`. On failure it leaves the flag unchanged and returns `{"detail": "No se pudo enviar el correo: <motivo>"}`: 502 if Graph failed, 503 if mail is disabled or credentials are missing. `mailer.ResultadoEnvio.no_configurado` decides which.
  - The old `/reenviar` route no longer exists.
  - The UI button says "Enviar correo" or "Reenviar correo" depending on `InvitacionEnviada`, and on success redraws only that row.
- **Mail (`mailer.py`):** this is the only send path in the repo (Graph `sendMail` via msal client credentials, `saveToSentItems=false`). The payload has `subject`, HTML `body` and `toRecipients` only, with no attachments and no `from`. The sender name comes from Exchange.
  - The template text is the user's final version (code-only sign-in). It must not mention passwords, "Cree una cuenta", "¿Ha olvidado su contraseña?" or "Si ya tienes cuenta…"; `test_mailer.py` checks this.
- **External ID (`externalid.py`):**
  - Graph `/users` in tenant `EXTID_TENANT_ID`, using its own msal client.
  - **Account format (code-only sign-in):** identity `{"signInType":"federated","issuer":"mail","issuerAssignedId":<correo>}` + `mail`, with NO `passwordProfile`/`passwordPolicies`. This is the same as self-registration with a code, and it was verified in the portal on 2026-10-23. An `emailAddress`/domain identity is a password account, and the portal asks it for a password. Never go back to that format.
  - **`buscar_por_correo`** → `Cuenta(id, tipo)` or `None`:
    - Filter `identities/any(...)` with `issuer eq 'mail'` first, then `issuer eq '<EXTID_DOMAIN>'`. `'` is doubled.
    - Graph ignores the issuer when filtering `emailAddress` identities, so the type comes from the returned identities: `codigo` (`TIPO_CODIGO`) or `contrasena` (`TIPO_CONTRASENA`). If both exist, the code account wins.
  - **`crear`:** a single POST, no retry. On a non-201 it raises, and the log has the full Graph response body. Graph error bodies hold code, message and request-id, with no secrets.
  - **`asegurar`** → `(id, estado)`, where estado is `CREADA`, `EXISTE_CODIGO` or `EXISTE_CONTRASENA`; it returns `(None, None)` when disabled. A legacy password account is never duplicated: it is logged as a WARNING with its id. Converting it means deleting it (and purging the recycle bin) and then re-ensuring.
  - `actualizar_nombre` and `eliminar` work on both types.
  - Errors raise `ErrorExternalId(motivo)`, with a Spanish message. With `EXTID_ENABLED=false` every function is a DEBUG-logged no-op.
  - `main._cuenta()` wraps calls and returns `(resultado, motivo)`; motivo is None on success, or the reason (or "error inesperado").
  - API behavior:
    - Create: INSERT, then `asegurar`. On failure the INSERT is kept and the response is 201 with a warning.
    - enviar-correo: `asegurar` first. On failure → 502 "No se pudo crear la cuenta de acceso: …", and the mail is not sent.
    - enviar-correo with a legacy password account (`EXISTE_CONTRASENA`) → **409** "La cuenta de acceso es antigua (con contraseña): elimínala y vuelve a intentar". No mail is sent and `InvitacionEnviada` is not marked (user's decision, option b, 2026-10-23). The UI shows it as an error toast, through the generic `detail` handling.
    - PUT: `actualizar_nombre` only when Nombre/Apellido changed.
    - DELETE: `eliminar` after the SQL delete.
    - PUT, POST create and DELETE return `avisoCuenta` (bool). The UI shows a yellow `toast-aviso` when it is true.
  - Tests: the `cuentas` fixture (`CuentasFalsas` in `conftest.py`) fakes the API-level calls. `tests/test_externalid.py` fakes `httpx.request` + msal for the module and the sync script.
  - **Sync tool:** `python -m app.tools.sync_externalid [--apply]` reads `db.listar_usuarios_con_acceso()`. It exits 2 and touches nothing if External ID is disabled or missing credentials. This reads the **production** table, so the user approves each run.
- **Session heartbeats (`POST /api/latido`, v8):**
  - Public: no `require_admin`, no CSRF header, no cookies. Body JSON ≤ 8 KB (Content-Length and streamed size are both checked), `Content-Type` `application/json` or `text/plain` (for `sendBeacon`). The handler is `async` and runs token validation and DB calls with `run_in_threadpool`.
  - `{"tipo":"mirastock","t":<GUID>}` → `db.latido_mirastock` (UPDATE `core.SesionesAgente` by Token, CreadoEn within 12 h, 60 s rule, alive = `COALESCE(FinalSesion, CreadoEn)` ≤ 10 min ago (v15); accepted even after ExpiraEn, and renews it to now + 30 min without shortening it (v15)). The GUID is normalized with `uuid.UUID`.
  - `{"tipo":"energia","token":...}` → `auth.validar_token_energia` (via `auth._validar_token`, separate key cache `auth.clave_energia` from `ENERGIA_PORTAL_URL`, issuer = Energía host, no audience check) → `db.latido_energia(correo)`: one batch with `UPDLOCK, HOLDLOCK` that updates the latest OK Energía row whose `COALESCE(FinalSesion, Fecha)` is within 30 min (60 s rule via `CASE`, so a fast repeat never INSERTs), else INSERTs `Fecha = FinalSesion = SYSUTCDATETIME()`. It relies on the connection's transaction (`autocommit=False`), with no BEGIN TRAN.
  - v10: `{"tipo":"energia","t":<GUID>}` → `db.latido_energia_llave` / `db.cierre_energia_llave`: a plain UPDATE of `core.HistorialAccesos` by `Token`, `Portal = N'Energía'`, `Resultado = N'OK'`, `Fecha` within 12 h, not closed, alive (`COALESCE(FinalSesion, Fecha)` ≤ 10 min ago, v15; also for the close); the heartbeat has the 60 s rule, the close does not and sets `CierreExplicito = 1`. Never INSERTs (the flow creates the row). `t` and `token` together, or neither (key presence, even `null`) → 400 «Envía la llave (t) o el token, no ambos.». The GUID goes through `main._llave_latido`, shared with MiraStock.
  - Responses: 204 whenever valid (never reveals whether a key exists), 400 bad body, 401 bad token, 503 DB error or `auth.ClaveNoDisponible` (Energía key download failed; it subclasses `TokenInvalido`).
  - CORS: custom `cors_latido` middleware for this route only. Origins from `LATIDO_ORIGINS` (normalized: lowercase, no trailing slash), POST only, header Content-Type, no credentials, Max-Age 600. A preflight or POST with a disallowed Origin → 403. No Origin → processed.
  - Never log `t` or the token (rejections are logged at DEBUG with the reason only). `main._SinLatidos` filters `/api/latido` out of `uvicorn.access`.
  - Tests: `BDFalsa.latido_*` reproduce the SQL rules with `bd.ahora`; `crear_token_energia` + autouse fixture `clave_de_energia` (`estado["error"]` simulates the key being unavailable).
- **Static cache busting:** pages reference `/static/*.css|js?v=18` (and the logo images, v18). Bump it on every release that changes static files.
- **Explicit close (v9):** optional `"cierre"` in `/api/latido`, which must be a real bool (`type(x) is bool`; anything else → 400, `false` = normal heartbeat).
  - MiraStock: `db.cierre_mirastock` sets FinalSesion, `CierreExplicito = 1`, and `ExpiraEn = now` if it was in the future (the key is revoked). No 60 s rule, and never on an already closed session or one that is no longer alive (v15). Normal heartbeats add `COALESCE(CierreExplicito, 0) = 0`.
  - Energía: `_SQL_ENERGIA_INICIO` picks the latest row in the window (no closed filter) with `UPDLOCK, HOLDLOCK`. `UPDATE ... OUTPUT deleted.* INTO @previa` captures its prior state.
    - `latido_energia`: open → extend (60 s rule); closed ≥ 60 s ago or no row → INSERT; closed < 60 s ago → ignored.
    - `cierre_energia`: closes it only if open, and never inserts.
  - `/historial`: rows have `CierreExplicito` and resumen has `cerradasBoton`. The «Cierre» column (UI `textoCierre`, CSV `main._texto_cierre`) shows Botón > En curso > Inactividad (if FinalSesion) > Sin actividad > No medida (v14) > «—» (empty in the CSV); Denegado rows always «—».
- **Business rules (API and UI):** At least one portal must be checked. Correo cannot be edited. `cliente` is required (`schemas.CLIENTES` = Entel, MiraGroup, Otro; case-insensitive, stored canonical) in `core.UsuariosEntel.Cliente` (v12); the UI suggests it from the email domain on create, adds the «Cliente» column and a filter. Since v12 there are no "self" rules (Portal3 is only data). The pydantic models use `validate_default=True`, so a missing field is validated too. Validation errors return 422 `{detail, errores: {campo: msg}}`, and the UI shows them next to each field.
- **Pages:** static HTML read at startup; only `templates/error.html` gets `{{MENSAJE}}` (escaped). There is no Jinja. v12 adds `login.html`, `cambiar-contrasena.html` (+ `cambiar.js`) and `administradores.html` (+ `administradores.js`); the home has a third card «Centro de administración principal».
  - v11 adds `estadisticas.html` (`/estadisticas`, uses `comun.js`; since v16 it is the cards home, see "Statistics pages"). The home card now says «Estadísticas del Portal Corporativo MiraGroup» and links to `/estadisticas`; `/historial` has no card.
  - The page routes share `main._pagina_protegida(request, html)` (see "Identity flow" step 7). `/login` with a valid session → 303 `/` (or `/cambiar-contrasena`).
  - `contactos.html` + `app.js` is the user admin, unchanged except the h1 («Centro Administración de contactos») and the «Inicio» link. `app.js` has its own API client and header code. The other pages use `comun.js` (`window.Mira`: `api`, `solicitar`, `el`, `toast`, `setOcupado`, `abrirModal`/`cerrarModal`, `sesion` (promise of `/api/me`), password policy, session-expired overlay with a link to `/login`, header with the admin's name, logout to `POST /api/auth/logout`).
  - The header markup is duplicated in each HTML (no templating). `.nav-inicio` holds the «Inicio» link outside `.sesion`; `#admin-nombre` shows the admin's name (email as title).
- **Access history (`/historial`, read-only):**
  - Source: view `core.vHistorialAccesos` (Fecha DATETIME2(0) UTC, Correo lowercase, Usuario may be empty/NULL, Portal `Energía`|`MiraStock`, Resultado `OK`|`Denegado`, FinalSesion UTC or NULL, TiempoSesionSeg int or NULL, EnCurso bit). Owned by the user, not by this app.
  - v8: rows add `FinalSesion` (ISO `Z`/null), `TiempoSesionSeg`, `EnCurso` (bool). Resumen adds `tiempoPromedioSeg` (AVG of non-NULL, or null), `tiempoTotalSeg: {Energía, MiraStock}` and `enCurso`. CSV adds «Final de sesión (UTC)» and «Tiempo de sesión (min)» (truncated integer minutes). UI: «En curso» chip, durations «< 1 min» / «44 min» / «1 h 05 min» (truncated), 4 new indicators.
  - `db.py`: `FiltrosHistorial` dataclass; `_where_historial` builds the WHERE from fixed fragments + `?` (correo uses `LIKE ? ESCAPE '\'` with `% _ [ \` escaped, lowercased). `listar_historial(filtros, pagina, tamano=50)` → `(filas, total)` with `ORDER BY Fecha DESC, Correo OFFSET/FETCH`. `resumen_historial(filtros, tz_offset_min)` → totals + `porDia` grouped by `CAST(DATEADD(minute, ?, Fecha) AS date)`.
  - `main.py`: `_filtros_historial` dependency validates everything at once and raises `ErrorValidacion(errores)` → 422 `{detail, errores}`. Resultado matches case-insensitively and is stored canonical. Portal (v11) is generic: any trimmed text ≤ `MAX_LARGO_PORTAL` (50); `PORTALES_HISTORIAL` only fixes the spelling of Energía/MiraStock. `/api/historial/csv` takes `tz_offset_min` (v11): dates shifted to local time, headers «Fecha (hora local, UTC-03:00)» (or «(UTC)» with 0). Dates: ISO 8601, aware → converted to naive UTC, naive = UTC; `desde` inclusive, `hasta` exclusive, `desde < hasta`. `pagina` 1..1,000,000, `tz_offset_min` −840..840. `admin` is declared first so 401 comes before 422.
  - Endpoints: `GET /api/historial` → `{filas, total, pagina, tamano, paginas}` (Fecha as `...Z`); `/api/historial/resumen` → `{total, usuariosUnicos, porPortal, denegados, porDia}`; `/api/historial/csv` → BOM + `;` + CRLF, Fecha `AAAA-MM-DD hh:mm:ss` UTC, cells starting with `= + - @ \t \r` get a `'`, filename `historial_accesos_AAAAMMDD.csv`, cap `TOPE_CSV_HISTORIAL` = 50,000 (more → header `X-Historial-Truncado`).
  - `historial.js`: default last 7 days; local days → UTC (`hasta` = next day 00:00 local); `tz_offset_min = -getTimezoneOffset()`. CSS bar chart (bar heights set via `element.style`, which the CSP allows); zero-filled up to 92 days, labels up to 31. The CSV is downloaded with fetch + blob, so 401/422 show in the UI and truncation shows a warning toast.
  - Tests: `BDFalsa.historial` + `agregar_acceso()` in `conftest.py`, and `llamadas_historial` records the filters received. `test_historial.py` also checks the SQL text and params of `db.py` with a fake cursor.
- **Statistics pages (v16):**
  - `/estadisticas` (`estadisticas.html` + `estadisticas-inicio.js`, no Chart.js): cards «General por portal» + one per portal from `/api/estadisticas/portales` (last 30 days), with `--color-portal` set via `style.setProperty` (CSSOM). Grid `.modulos-estadisticas`: 3 / 2 (≤ 900 px) / 1 (≤ 600 px) columns.
  - `/estadisticas/general` (`estadisticas-general.html`, `<body data-vista="general">`) and `/estadisticas/portal/{slug}` (`estadisticas-portal.html`, `data-vista="portal"`), both through `_pagina_protegida` (which now takes `status_code`). A slug that does not match `_SLUG_VALIDO` (`[a-z0-9]+(-[a-z0-9]+)*`, ≤ `MAX_LARGO_SLUG` = 64) → the same page with 404; a valid unknown slug → 200 and the page shows `#portal-no-encontrado`.
  - Slug: `main._slug_portal` (NFKD → ASCII, lowercase, non-alphanumeric runs → `-`, ≤ 60, empty → `portal`) and `_slugs_portales` (unique: alphabetical, then `-2`, `-3`…). Only `/api/estadisticas/portales` returns it (not the total, not the CSV).
  - `estadisticas.js` picks the mode from `data-vista`: `general` → `montarTablaGeneral` + `montarGraficosGeneral` into `#general-cuerpo`; `portal` → `resolverPortal()` finds `p.slug === SLUG` in `datosPortales()`, sets h1/title and `montarPortal(portal)` (charts above the tabs in `#portal-cuerpo`; tabs lazy via `!panel.hidden`). Dates: `fijarRangoInicial` / `guardarRango` in `sessionStorage` (`CLAVE_RANGO` = `mira.estadisticas.rango.general` or `.portal.<slug>`), wrapped in try/catch.
- **Charts (`/estadisticas`, v16):**
  - `db.estadisticas_series(portal, desde, hasta, tz)`: `SELECT DISTINCT Portal` (only without portal) + one `GROUP BY GROUPING SETS ((Dia, Portal), (Dia))` over a derived table with `CAST(DATEADD(minute, ?, Fecha) AS date) AS Dia` (GROUP BY cannot repeat an expression with parameters). `main.api_estadisticas_series` fills the days with 0 (`_limites_series`: local day of `desde` to local day of `hasta − 1 µs`; without a date, first/last day with data) and returns 422 on `hasta` over `MAX_DIAS_SERIES` = 731.
  - `db.estadisticas_distribucion(portal, desde, hasta, tz)`: three queries — `_CASE_CIERRE` (same priority as `_texto_cierre`; `db.TIPOS_CIERRE`, «Otro» = medible without data), `_CASE_DURACION` (`db.BORDES_DURACION` = 300/900/1800/3600 s; −1 sin actividad, −2 sin medir) and the 7 × 24 matrix with `DATEDIFF(day, '19000101', CAST(L AS date)) % 7` (Monday = 0, no `@@DATEFIRST`) over a derived `DATEADD(minute, ?, Fecha) AS L`. `portal` required (`_filtros_distribucion`, no correo).
  - Frontend: `graficos.js` (`window.MiraGraficos`: theme from CSS vars into `Chart.defaults`, `colorPortal`, `crearPanel` with carga/vacío/error + `dibujar` that always `destroy()`s first, `tarjetas`, `mapaCalor` as a CSS grid with `element.style` intensity and `title` per cell). `estadisticas.js`: `datosPortales()` shares one `/portales` request per range version between the table, the general charts and the portal cards; `seccionGraficos` registers each chart section as a view (always visible since there is no accordion), inserted above the table / above the tabs. Top 10 comes from `/api/estadisticas/usuarios`.
  - Tests: `BDFalsa.estadisticas_series/_distribucion` (weekday via `datetime.weekday()`), `tests/test_graficos.py` (endpoints, borders, weekday/tz, SQL via `CursorFalso`, static files, CSP, portal names only in the color map).
  - **v17 email search (portal views only):** `graficosPortal(portal)` returns `[buscador, seccion.nodo]` (`montarPortal` does `tablist.before(...)`): a «Correo» form («Contiene…», `maxlength` 256, «Buscar»/Enter) between the date filter and the cards, and the chip `.filtro-activo` «Filtrado por: <texto>» with a × (`aria-label` «Quitar filtro») as the first grid item. The applied text (`buscado`) is stored in `sessionStorage` `mira.estadisticas.correo.portal.<slug>` (try/catch) and reused by date changes and «Reintentar». With a filter, the cards come from `GET /api/estadisticas/resumen?portal&correo&desde&hasta` (`{portal, correo, usuariosUnicos, sesiones, segundosTotales, promedioSeg, sesionesMedidas, ultimaConexion, sinActividad}`, via `_filtros_estadisticas_portal`); without one, from `datosPortales()` as before. `/series`, `/distribucion` and `/usuarios` (Top 10) get `correo`. No match → cards at 0 and every panel `mostrar("vacio", "Sin sesiones que coincidan con la búsqueda")` (`graficos.js` `mostrar` takes an optional empty text). A 422 on `correo` is shown under the field (`cargarPaneles(..., alFallar)`). `BDFalsa` records `correo` in the `series`/`distribucion` call tuples only when it is set.
- **Statistics (`/estadisticas`, v11, read-only on `core.vHistorialAccesos`):**
  - A session is a row with `Resultado = 'OK'`. Denied rows count neither as sessions nor as users.
  - `db._where_sesiones` reuses `_where_historial` with `resultado="OK"`.
  - `db.estadisticas_portales(desde, hasta)` runs two queries:
    - `SELECT DISTINCT Portal` over the whole view, so every known portal appears with zeros when it has no sessions in the range.
    - One `GROUP BY GROUPING SETS ((Portal), ())`. The `()` row is the total; `COUNT(DISTINCT Correo)` there does not repeat users across portals.
    - Aggregates (`_AGREGADOS_SESIONES`): `COUNT(*)`, `SUM` and `AVG` of `TiempoSesionSeg` (AVG ignores NULLs, so only measured sessions count), `COUNT(TiempoSesionSeg)` (= `sesionesMedidas`), `MAX(Fecha)` and (v14) the SinActividad count (= `sinActividad`).
  - `db.estadisticas_usuarios(portal, desde, hasta, tope)`:
    - `TOP (tope+1)` grouped by Correo, ordered by hours DESC, then sessions DESC, then Correo.
    - Returns `(filas, truncado)`.
  - Endpoints (`admin` first):
    - `GET /api/estadisticas/portales` → `{portales: [{portal, usuariosUnicos, sesiones, segundosTotales, promedioSeg, sesionesMedidas, ultimaConexion}], total: {...}}`.
    - `GET /api/estadisticas/usuarios?portal=` (required; missing → 422 «Indica el portal.», merged with correo/date errors) `&correo=` (optional, v13: contains, ≤ 256) → `{portal, correo, filas: [{usuario, correo, ...}], total, totalSinFiltro, truncado}`, capped by `TOPE_USUARIOS_ESTADISTICAS` = 5,000. The CSV also takes `correo`.
    - Both have a `/csv` with `tz_offset_min`.
    - `segundosTotales`/`promedioSeg` are `null` when nothing was measured.
  - CSV:
    - `main._respuesta_csv` is shared with `/api/historial/csv`: BOM, `;`, CRLF and the `X-Historial-Truncado` header.
    - Columns `_encabezados_sesiones`: Sesiones, Sesiones medidas, Sin actividad (v14), Horas totales (text from `_duracion_texto`, the same as the UI), Minutos totales (int), Promedio por sesión, `Última conexión (<_zona_csv>)`.
    - The portals CSV ends with the «Total Portal Corporativo» row.
    - Filenames are `estadisticas_portales_*` and `estadisticas_<_nombre_archivo(portal)>_usuarios_*` (ASCII, e.g. `energia`).
  - UI (`estadisticas.js`):
    - A date filter (default 30 days) with `<details>` blocks. «General por portal» always loads, and builds one block per portal from `<template id="tpl-portal">`. No portal names are hardcoded (a test checks this).
    - Each block has WAI-ARIA tabs built from `SUBVISTAS` (`{titulo, montar(panel, portal, vista)}`).
    - Views register in `vistas` and load lazily: `refrescarVisibles()` loads the open/selected views whose `version` is behind `estado.version`.
    - The detailed tab calls `/api/historial?portal=` with its own correo/resultado filters and pagination.
  - `comun.js` (v11) holds the shared helpers used by `historial.js` and `estadisticas.js`: `numero`, `textoDia`, `inicioDiaLocal`, `agregarRango`, `tzOffsetMin`, `fechaLocal`, `duracion`, `textoCierre`, `descargarCsv`.
  - Tests:
    - `BDFalsa.estadisticas_portales/_usuarios` reproduce the SQL rules over `bd.historial`.
    - `tests/test_estadisticas.py` checks the SQL text with `CursorFalso`/`cursor_falso` imported from `test_historial.py`.

## Commands (PowerShell, from the repo root; venv at `.venv`)

- Install: `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`
- Run locally: `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000`. It reads `.env`, which has real prod credentials and `LOG_LEVEL=DEBUG`. Local UI actions change the **production** table.
- Tests: `.\.venv\Scripts\python.exe -m pytest`, or a single test with `pytest tests/test_usuarios.py::test_name`.
  - `tests/conftest.py` sets its own env vars before importing the app, so the real `.env` is never used.
  - It swaps `app.db` and `mailer.enviar_bienvenida` for in-memory fakes and signs tokens with throwaway RSA keys.
  - The TestClient uses `https://testserver`. Cookies set manually need `domain="testserver.local"`.
- JS syntax check: there is no Node on this machine. Use esprima from a scratch target dir: `pip install --target <dir> esprima==4.0.1`, then `esprima.parseScript(...)`.
- Deploy a new version (always a new tag; v19 is next; bump `?v=` in the HTML, now `?v=18`, if static files changed): run the tests first, then `az acr build --registry acrscripth25prod --image mira-admin-app:vN .`, then `az containerapp update -n ca-mira-admin -g RG-COPILOT-DEV --image "acrscripth25prod.azurecr.io/mira-admin-app:vN"`. Verify `/health` and `az containerapp logs show -n ca-mira-admin -g RG-COPILOT-DEV --type console --tail 30 --format text`.
- Azure layout:
  - `ca-mira-admin` is in `RG-COPILOT-DEV`, East US, with 0.25 vCPU, 0.5 Gi and 0–1 replicas.
  - It reuses environment `managedEnvironment-rgscripth25prod-818f` and ACR `acrscripth25prod`, both in `rg-script-h25-prod`.
  - The image pulls with ACR admin credentials, because the user is only Contributor and cannot assign `AcrPull`.
  - The SQL server `sqlcopilotprd01` is in `RG-COPILOT-DEV`.
- PowerShell 5.1 gotchas:
  - `$ErrorActionPreference = "Stop"` turns az's stderr warnings ("altered by the following extension") into fatal errors. Use `Continue` and validate the values explicitly.
  - `Set-Content -Encoding utf8` writes a BOM.
  - `-MaximumRedirection 0` throws an error when a redirect happens.
- The image is `python:3.12-slim-bookworm` + `msodbcsql18` (Debian 12 has Microsoft's repo), running uvicorn on port 8000 with `--proxy-headers`. `.dockerignore` excludes `.env`, `.venv/`, `.claude/`, `brief.md`, `CLAUDE.md`, the tests and the dev files.
