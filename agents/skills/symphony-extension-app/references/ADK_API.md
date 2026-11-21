# Symphony ADK — verified API reference

Everything here was read from the type declarations in
`node_modules/@symphony-ui/adk/lib/**/*.d.ts` at version **3.15.0**, and exercised
against a live UAT pod. Where the published docs at
`symphonyplatformsolutions.github.io/symphony-adk` disagree, that is called out.

> **Rule: the `.d.ts` files are ground truth.** The docs site is generated from an
> older tree and its hand-written `@example` blocks have drifted. Before trusting any
> signature in the docs, run:
> `cat node_modules/@symphony-ui/adk/lib/impl/<Namespace>.d.ts`

## Installation

```bash
npm install @symphony-ui/adk@3.15.0 esbuild
```

`package.json` of the published package declares only `main: lib/index.js` (CommonJS)
and `types: lib/index.d.ts`. There is **no** `browser`, `module`, `unpkg`, or
`jsdelivr` field, therefore no browser-ready build. Bundling is mandatory.

## Entry points

```ts
// SymADK.d.ts
export declare function start(config: SymphonyAppDescriptor): Promise<SymphonyApp>;
export declare function connectView(config: SymphonyAppDescriptor):
  Promise<Pick<SymphonyExternalApp, 'userReferenceId' | 'locale'>>;
```

```ts
// SymAppConfig.d.ts
interface SymphonyAppDescriptor {
  id: string;                          // MUST equal appGroupId in the admin bundle
  circleOfTrust?: CircleOfTrustConfig;
  themeUpdate?: ThemeUpdateCallback;
}
type CircleOfTrustConfig = {
  getAppToken: () => Promise<string>;
  validateAppToken: (appToken: string, symphonyToken: string) => Promise<void>;
  validateJwt: (jwt: string) => Promise<void>;
};
```

| Frame | Call | Notes |
|---|---|---|
| Controller (bundle `loadUrl`) | `start()` | Registers the app. Owns CoT. Runs once. |
| Any module page it opens | `connectView()` | **Required.** Client keeps the module in its loading state until this resolves. |

`connectView()` takes no `circleOfTrust` — CoT belongs to the controller only.

## navigation

```ts
// Navigation.d.ts  — NOTE: docs show `{ onClick: ... }`; the type is a bare function
export declare function add(
  title: string,
  onClick: () => void,
  icon?: string | URL,
): NavItemApi;
```

- Argument order is **title first**; there is no item id.
- `icon` must be a **fully-qualified URL to a 16×16 image**. Build it from
  `window.location.origin`, never a relative path — the client resolves relative URLs
  against *its* origin, not yours. (The docs' example uses
  `https://localhost:4000/images/symphony.png`; if you see a
  `localhost:4000` request in the console it is a copy-paste of that example, quite
  possibly from a different app.)
- Returns `NavItemApi`: `.rename(title)`, `.remove()`, and
  `.notificationCounter.{increment,decrement,set,clear}()`.

## modules

```ts
export declare function open(viewName: string, options?: ModuleOptions): ModuleApi;
export declare function openLink(url: string): void;
```

```ts
type ModuleOptions = {
  title: string;
  iconUrl?: string;
  moduleId?: string;          // custom id; must be unique
  openMode?: ModuleOpenMode;  // POPUP | SIDE_BY_SIDE | ...
  parentModuleId?: string;
};
```

- `viewName` is **either a URL or an ADK-React view name**.
- Two args, not five. (Legacy raw Extension API used
  `open(appId, title, controller, url, options)` — unrelated.)
- Set `moduleId` explicitly when the URL carries variable query params, or every
  variation opens its own tab instead of reusing one.
- `openLink()` opens in the user's real browser. Use it instead of
  `<a target="_blank">`.

## dialogs

```ts
// impl/Dialogs.d.ts & interfaces/Dialogs.d.ts
export declare function show(template: string, options?: DialogOptions): DialogApi;

export type DialogOptions = {
  data?: JsonObject;
  actions?: Record<string, {
    label: string;
    action: () => void;
  }>;
  size?: 'small' | 'normal' | 'large' | 'auto'; // defaults to 'large'
  onClose?: () => void;
};

export interface DialogApi {
  close(): void;
  rerender(template: string, data: JsonObject): void;
}
```

- `show()` takes **`(templateHtml, options)`** — an ExtensionML `<dialog>...</dialog>` string first, and `DialogOptions` second (do **not** pass a `{ id, title, url }` object as the first argument; `size` accepts `'small' | 'normal' | 'large' | 'auto'`).
- Action buttons inside `<dialog>` MUST use ExtensionML `<action id="..." />` bound to `options.actions[<id>].{ label, action }` (never `window.alert/confirm`):

```js
const templateHtml =
  `<dialog>` +
    `<h3>${safeTitle}</h3>` +
    `<iframe src="${safeModalUrl}" width="100%" height="520px"/>` +
    `<action id="close_dialog" class="tk-button tk-button--secondary tk-button--medium" />` +
  `</dialog>`;

const dialog = ADK.dialogs.show(templateHtml, {
  size: 'large',
  actions: {
    close_dialog: {
      label: 'Close',
      action: () => dialog.close(),
    },
  },
});
```

## messages

```ts
export declare function registerRenderer(
  entityType: string,
  renderer: (entityData: any) => MessageRenderResult,
  onAction?: (actionId: string, actionPayload?: ActionPayload) => void,
): void;
```

The renderer returns `{ template, actions }`, where `template` is ExtensionML:

```js
ADK.messages.registerRenderer(
  'com.example.my-entity',
  (entityData) => ({
    template: `<entity><action class="tk-button tk-button--primary" id="open" /></entity>`,
    actions: { open: { label: entityData.label, data: entityData.actionData } },
  }),
  (actionId, actionPayload) => { /* actionPayload.data */ },
);
```

This replaces the legacy `entity` service's `registerRenderer(type, version, name)`.

## Legacy raw Extension API — do not use

If you find code calling any of these, it predates ADK and will not work without a
pod-hosted SDK that does not exist:

| Legacy | ADK equivalent |
|---|---|
| `SYMPHONY.remote.hello()` | (internal to `ADK.start`) |
| `SYMPHONY.application.register(appId, services, provided)` | `ADK.start({ id })` |
| `SYMPHONY.application.connect(...)` | `ADK.connectView({ id })` |
| `SYMPHONY.services.subscribe('applications-nav').add(...)` | `ADK.navigation.add(...)` |
| `SYMPHONY.services.subscribe('modules').open(...)` | `ADK.modules.open(...)` |
| `entity.registerRenderer(type, 'v1', name)` | `ADK.messages.registerRenderer(...)` |
| `services.register(name).implement({ select })` | the `onClick` callback |

ADK still uses `applications-nav` and friends *internally* — that is expected in the
bundled output and is not a sign of legacy code in your source.

## Circle of Trust call order

From `lib/impl/CircleOfTrust.js`, the exact sequence ADK drives:

```
getAppToken()                       -> Ta
SYMPHONY.application.register({ tokenA: Ta, appId }) -> { tokenS: Ts, ...rest }
validateAppToken(Ta, Ts)
services.get('extended-user-info').getJwt()          -> jwt
validateJwt(jwt)
return { jwt, ...rest }
```

**Every callback must reject on failure** — ADK aborts registration when one throws.

⚠️ **But ADK swallows the abort.** `getCircleOfTrust` wraps the whole sequence in
`try/catch` and only does `console.error(AdkError)`. Registration continues and your
nav item appears, so a `validateJwt` failure is invisible in the happy-path logs.
Confirm HTTP 200 on your `jwt/validate` endpoint; do not trust the logs.

## Pod endpoints used by the backend

| Purpose | Request |
|---|---|
| App backend auth | `POST https://<POD_HOST>/login/v1/pubkey/app/authenticate/extensionApp` body `{appToken, authToken}` → `{appId, appToken, symphonyToken, expireAt}` |
| JWT signing cert | `GET https://<POD_HOST>/pod/v1/podcert` → `{certificate}` (PEM) |

- `authToken` is a JWT signed by **your app's RSA private key**, `RS512`, 4096-bit,
  claims `{sub: <appId>, iat, exp}` with a short expiry.
- The public half must be registered as `rsaKey` in the admin-portal bundle.
- `symphonyToken` (Ts) expires within **5 minutes**.
- User JWT is signed **RS512**; verify against the `podcert` certificate and pin the
  algorithm. `sub` is the numeric userId — see the PyJWT note in `SKILL.md`.
