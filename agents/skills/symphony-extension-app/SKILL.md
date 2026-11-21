---
name: symphony-extension-app
description: Builds, registers, deploys and verifies a Symphony extension app (left-nav app / module UI) using the Symphony ADK, including Circle of Trust authentication. Use when adding a client-side UI to an MCP server, when an app appears in the Marketplace but not the left nav, when a module renders as an endless spinner, or when debugging ADK registration and CoT handshake failures.
---

# Symphony Extension App (ADK) Builder

Scaffolds and verifies the **frontend half** of a Symphony integration: the app that
appears in the left-hand nav and opens a module inside the Symphony client.

This is a *different artifact* from the MCP server that `mcp-studio-builder` creates.
An MCP server exposes tools to an agent over SSE/streamable-HTTP. An extension app
renders UI inside the Symphony client. They are commonly deployed from the same
container and the same host, but nothing about one implies the other.

## ⚠️ Read this before writing any code

These five facts contradict the published documentation or are absent from it. Each
one has cost a full debugging session.

1. **ADK is an npm package, not a hosted script.** `@symphony-ui/adk` *contains* the
   postMessage protocol. There is **no** pod-hosted SDK to load. Any URL of the form
   `https://<pod>/apps/embed/default/symphony-api.js` returns
   `404 STARTPAGE__RESOURCE_NOT_FOUND`. Do not try to find it; it does not exist.

2. **Never hand-roll a `symphony-api.js` shim.** This is the single most expensive
   failure mode. A hand-written shim that `postMessage`es and then resolves its own
   promises will print a completely convincing sequence of success logs
   (`connected`, `registered`, `nav added`) while the Symphony client receives
   nothing, because the message types are invented and the client does not listen for
   them. If you find such a file in a project, **delete it** — it is not a fallback,
   it is a liar. Symptom: app visible in Marketplace, absent from left nav, no errors.

3. **ADK ships CommonJS only** (`main: lib/index.js`, no UMD/IIFE/browser build). It
   cannot be loaded from a `<script>` tag. A bundling step is mandatory — see
   `templates/frontend/package.json` and `templates/deploy/Dockerfile.adk-stage`.

4. **Controller frame and view frame are different, and both must handshake.**
   - Controller (the bundle's `loadUrl`, invisible): `await ADK.start({ id })`
   - Every module page it opens: `await ADK.connectView({ id })`

   The Symphony client holds a module in its **loading state until the view frame
   connects**. A view that skips `connectView()` renders as an endless spinner even
   though the page itself loaded fine (HTTP 200, no console errors).

5. **The published API docs are wrong about `navigation.add`.** Docs show
   `add('Title', { onClick: ... })`. The type declaration says
   `add(title: string, onClick: () => void, icon?: string | URL)` — a **bare
   function**. When docs and `node_modules/@symphony-ui/adk/lib/**/*.d.ts` disagree,
   **the type declaration wins**. Read the `.d.ts` files; they are the ground truth.

See `references/ADK_API.md` for every verified signature.

---

# Process

## Phase 1: Establish what already exists

Do not scaffold blindly. Determine:

1. **Is there an MCP server / container already serving static files?** Extension
   apps are normally served from the same origin. Find the static mount (in this
   template: `Mount("/app", StaticFiles(...))` in the server entrypoint).
2. **Are the Bot Service Account and Extension App registered in the Symphony Admin Console?**
   Ask the user for `APP_ID`, `BOT_USERNAME`, `POD_HOST`, and whether the RSA keypair is generated.
   If not yet registered, guide the user through the exact fields detailed in `references/SYMPHONY_ADMIN_PORTAL_SETUP.md`:
   - Generate RSA key pair: `openssl genrsa -out app-bot-private-key.pem 4096 && openssl rsa -in app-bot-private-key.pem -pubout -out app-bot-public-key.pem`.
   - **Bot Service Account**: Admin Console → Accounts → Service Accounts. Upload public key. Record username and numeric user ID.
   - **Application (Extension App)**: Admin Console → Applications → App Management. Set `appGroupId` to `APP_ID`, `domain` to `<INGRESS_HOST>`, `loadUrl` to `https://<INGRESS>/mcp/<APP>/v1/app/controller.html`, enable `TRUST_APP`, paste public key, set availability to "All users in the pod".
3. **Does the app bundle declare `TRUST_APP` and an `rsaKey`?** If yes, Circle of
   Trust is **mandatory** — the client will not release user identity without it.
   Verify that the private half of `rsaKey` is provided in `BOT_RSA_PRIVATE_KEY`.
4. **What are the two hostnames?** They are almost always different and confusing
   them breaks backend auth:
   - **Pod host** (e.g. `<pod>.on.uat.symphony.com`) — serves the Symphony client
     and `/login/v1/...`, `/pod/v1/...`. Backend auth goes here.
   - **App/ingress host** (e.g. `mss.uat.symphony.com`) — serves *your* app. Does
     **not** serve `/login/v1/...`.

## Phase 2: Two registration artifacts, both required

Getting one and not the other is a classic half-working state.

| Artifact | Who reads it | Key fields |
|---|---|---|
| **Admin-portal bundle** | Symphony backend, at app install | `appGroupId`, `loadUrl`, `iconUrl`, `domain`, `permissions`, `rsaKey` |
| **Static `bundle.json`** | Symphony **client**, fetched cross-origin from your host | `applications[].id`, `.url` (→ your controller HTML), `.icon`, `.domain` |

Non-obvious consequences:

- The client fetches `bundle.json` **cross-origin**, so your host must send
  `Access-Control-Allow-Origin`. Without it you get a CORS error that looks like a
  routing problem.
- **The `url` inside `bundle.json` is what actually loads the controller** — not the
  admin bundle's `loadUrl`. Bump a cache-busting query on it when you change the
  controller, or the client serves a stale one.
- `ADK.start({ id })` must equal the admin bundle's **`appGroupId`**, or the client
  rejects the connection.
- Do not assume `bundle.json` is dead legacy config because it looks like an old
  format. Confirm by watching the network tab for `GET /app/bundle.json` before
  deleting anything.

## Phase 3: Scaffold the frontend

Copy from `templates/frontend/`, replacing `{{APP_ID}}`, `{{APP_TITLE}}`,
`{{ENTITY_TYPE}}`, `{{APP_HOST}}`:

| Template | Destination | Purpose |
|---|---|---|
| `controller.js` | `<adk-src>/controller.js` | `ADK.start`, nav item, entity renderer, CoT wiring |
| `view.js` | `<adk-src>/view.js` | `ADK.connectView` — **do not skip** |
| `package.json` | `<adk-src>/package.json` | Pins ADK + esbuild, two build entrypoints |
| `controller.html` | `<static>/controller.html` | Loads only the built controller bundle |
| `bundle.json` | `<static>/bundle.json` | Client-fetched app descriptor |

Rules:
- Keep the ADK source **outside** the static dir. Only built bundles are served.
- Build with `--format=iife --platform=browser --target=es2020`. ESM in a plain `<script>` will not execute.
- Gitignore the built bundles and `node_modules`; they are CI artifacts.

## Phase 4: Circle of Trust (only if `TRUST_APP` / `rsaKey`)

Copy `templates/backend/cot_auth.py` (Starlette; port it if the backend is another
language). It implements the app-backend half of the flow and exposes three
endpoints that map 1:1 onto ADK's callbacks:

| ADK callback | Endpoint | Does |
|---|---|---|
| `getAppToken()` | `POST /api/v1/cot/token` | Mints Ta, exchanges it with the pod for Ts, stores the pair, returns Ta |
| `validateAppToken(Ta, Ts)` | `POST /api/v1/cot/tokens/validate` | Constant-time compare against the stored pair |
| `validateJwt(jwt)` | `POST /api/v1/cot/jwt/validate` | Verifies the user JWT against the pod certificate |

Pod endpoints (verified working):
- `POST https://<POD_HOST>/login/v1/pubkey/app/authenticate/extensionApp`
  body `{"appToken": "<Ta>", "authToken": "<RS512 JWT signed by app RSA key>"}`
  → `{appId, appToken, symphonyToken, expireAt}`
- `GET https://<POD_HOST>/pod/v1/podcert` → `{"certificate": "<PEM>"}`

Hard-won details:
- **Mount CoT routes outside the static mount.** `/app/...` is a `StaticFiles` mount
  and will shadow sibling API paths. Use `/api/v1/cot/...`.
- **Ts expires within 5 minutes.** The token-pair store must have a matching TTL.
- **A process-local pair store requires `replicas: 1`.** With more replicas,
  `tokens/validate` can hit a process that never saw the pair and 401s
  intermittently. Use a shared store or session affinity before scaling.
- **PyJWT ≥ 2.10 needs `verify_sub=False`.** It enforces RFC 7519's "sub must be a
  string"; Symphony's user JWT carries the numeric `userId` there, producing
  `401 Subject must be a string`. Identity comes from the `user` claim, not `sub`.
- **Pin `algorithms=["RS512"]` and never fall back to unverified decode.** This
  endpoint gates user identity; it must fail closed.
- **ADK swallows a `validateJwt` rejection.** `getCircleOfTrust` catches it, logs
  `AdkError`, and continues — so the nav item still appears while identity is
  silently untrusted. Always confirm `jwt/validate` returned 200 in the network tab;
  do not trust the "Circle of Trust established" log alone.

## Phase 5: Deploy

Apply `templates/deploy/`:
- `Dockerfile.adk-stage` — node build stage + copying both bundles into the image.
- `deployment-snippet.yml` — RSA key volume, `SYMPHONY_*` env, and
  **`maxUnavailable: 0`**.
- `workflow-snippet.yml` — provisions the RSA key secret from a CI secret and fails
  fast if it is missing or not PEM.

Three rules that turn a bad deploy into a non-event:

1. **Never add a secret volume without provisioning the secret in the same change.**
   A non-optional missing secret leaves the pod in `ContainerCreating` forever.
2. **`maxUnavailable: 0` whenever `replicas: 1`.** Otherwise Kubernetes removes the
   serving pod before the replacement is ready, so any startup failure becomes a
   full outage instead of a failed rollout.
3. **`.dockerignore` must exclude `node_modules/`** and the built bundles, or a
   blanket `COPY src /app/src` bakes local artifacts over the CI build.

## Phase 6: Verify before handing back

Run `scripts/verify.sh <APP_HOST> <POD_HOST> [APP_ID]` (also available at `references/verify.sh`) and run headless browser DOM + ADK handshake verification with `scripts/verify_ui_dom.py`:

```bash
bash skills/symphony-extension-app/scripts/verify.sh <APP_HOST> <POD_HOST> <APP_ID>
python3 skills/symphony-extension-app/scripts/verify_ui_dom.py \
  --url "http://127.0.0.1:8000/app/index.html" \
  --expect-selector "body" \
  --screenshot "/tmp/ui_verify.png"
```

`verify.sh` checks asset delivery with CORS headers, both bundles, and the full CoT endpoint contract including negative cases; `verify_ui_dom.py` verifies `0` `console.error` / `4xx` / `5xx` responses and simulated ADK `postMessage` handshake completion in headless Chromium.

Then have the user hard-reload the client and confirm **both** handshake logs:

```
[App] CoT: obtained app token (Ta)
[App] CoT: token pair validated
[App] CoT: user JWT verified, userId=...      <- must be present, not a 401
[App] ADK connected to Symphony client
[App] Left-nav item added
[View] Connected to Symphony client            <- module left its loading state
```

Missing last line ⇒ endless spinner ⇒ `connectView()` is absent or failing.

---

## Phase 7: In-Chat Rich UI & Dual-Host A2UI v1.0 Surfaces

Beyond the left-nav module view, extension apps can render declarative A2UI v1.0 cards and progressive sub-cards directly inside chat messages (and simultaneously in Claude / standard MCP App sandboxes via `SEP-1865`):

1. **Register the Universal A2UI Entity Renderer**: Register `com.symphony.a2ui.surface` via `ADK.messages.registerRenderer(...)` in `web/adk/controller.js`.
2. **Mount Strict ExtensionML Widget Iframe**: Return `<entity><iframe src="https://.../app/a2ui-surface.html?surface=...&amp;inline=1#a2ui=..." width="460px" height="348px"/></entity>` (strictly `src`, `width`, `height` only; XML-escaped `&amp;`; height `<= 1000px`).
3. **Zero-Build Vanilla A2UI v1.0 + SDS Core UI v1.0.0**: `a2ui-surface.html` + `a2ui-renderer.js` render flat `application/a2ui+json` envelopes (`createSurface`, `updateDataModel`, `@path` bindings, `visibleWhen`, `Tabs`) using Two-Layer `❖ SDS Core UI` v1.0.0 tokens (`symphony-tokens.css` + `app-tokens.css`, `0` raw hexes) and scoped `st_...` `surface_token` RBAC.
4. **Side-Room Escalation & Auto-Resize**: Measure height via `ResizeObserver` (`ui/size-change` in SEP-1865 mode; synchronized `FIXED_SURFACE_HEIGHTS` in Symphony ADK) and escalate complex workflows via `a2ui:open_companion` -> `ADK.modules.open(..., { openMode: 'SIDE_BY_SIDE' })` (`/app/index.html?embed=companion&tab=overview`) or `a2ui:open_modal` -> `const dialog = ADK.dialogs.show(templateHtml, { size: 'large', actions: { close_dialog: { label: 'Close', action: () => dialog.close() } } })` with `<action id="close_dialog" class="tk-button tk-button--secondary tk-button--medium"/>`.
5. **Theme Synchronization**: Sync `light`/`dark` and `spacious`/`condensed` classes dynamically across `themeChange`, `symphony:theme`, and `ui/notifications/host-context-changed`.

👉 **Complete Implementation Guide**: Read [`docs/A2UI_EXTENSION_GUIDE.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/A2UI_EXTENSION_GUIDE.md), [`references/GENERATIVE_UI_A2UI.md`](./references/GENERATIVE_UI_A2UI.md), and [`docs/MCP_SERVER_AND_APP_ARCHITECTURE_SPEC.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/MCP_SERVER_AND_APP_ARCHITECTURE_SPEC.md).

---

## Debugging

**Read `references/DEBUGGING.md` before forming a hypothesis from console logs.** It
covers the traps that generate false conclusions, most importantly:

- A CDN in front of your host caches `.png`/`.css`/`.js` but not `.html`/`.json`, so
  **cached 200s can mask a completely dead backend**. Always probe a `.html` or
  `.json` path to see the truth.
- `503 unconditional drop overload` from a Google/Envoy edge means **no healthy
  backend**, not an overloaded one.
- The Symphony client console is shared by every installed app. Errors mentioning
  another `appId`, another app's CoT, or `localhost:4000` are **not yours**.
- Never diagnose from console logs alone when you can read pod logs and
  `kubectl describe pod`. A container that never started has no logs — that absence
  is itself the diagnosis.
