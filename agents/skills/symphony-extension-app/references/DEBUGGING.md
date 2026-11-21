# Debugging a Symphony extension app

Symptom-first. Each entry is a failure actually observed and diagnosed, with the
evidence that distinguished it from lookalikes.

## Rule 0: do not diagnose from the browser console alone

The Symphony client console is a shared bus for the client itself and **every**
installed app. Before theorising:

1. `kubectl get pods -n <ns>` — is a pod actually `1/1 Running`?
2. `kubectl describe pod <pod>` — read the **Events** at the bottom.
3. `kubectl logs <pod>` — **a container that never started has no logs. That absence
   is the diagnosis, not a dead end.**
4. Probe your host directly with `curl`, bypassing the client entirely.

Console errors that are **not yours** unless the appId matches your app:
- `AppInit.ts` / `CircleOfTrust.js` failures naming a different `appId`
  (e.g. `appId=ai-agent-studio`)
- `extension failed to load, "@symphony/marketplace-c2"`
- `GET https://localhost:4000/icon.png ERR_CONNECTION_REFUSED` — the ADK docs'
  placeholder icon, from some app that copy-pasted the example
- `client-bff/v1/messages`, `datafeed2/...`, `transportWorker.js` — Symphony client
  internals

## The CDN cache trap (causes the most wrong conclusions)

**Symptom:** `.png`, `.css`, `.js` return 200 while `.html` and `.json` return 503 or
error. Looks exactly like an edge policy blocking HTML.

**Reality:** the CDN in front of the host (Cloudflare here) caches static asset types
by default and does **not** cache `.html`/`.json`. Cached 200s keep serving from the
edge long after the origin is completely dead.

**Diagnostic:** probe a path that *cannot* be cached, and a path that does not exist:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<APP_HOST>/app/index.html
curl -s -o /dev/null -w '%{http_code}\n' https://<APP_HOST>/app/zzz-does-not-exist.json
```

If a **nonexistent** file returns the same status as a real one, you are not looking
at per-file 404s — you are looking at a dead backend.

## `503 unconditional drop overload`

Not an overload. This is the Google/Envoy edge reporting **no healthy backend**.
Related strings from the same layer: `fault filter abort` (404-ish),
`upstream connect error or disconnect/reset before headers`.

Check the pod first. Every time.

## CORS error on `bundle.json`

```
Access to fetch at 'https://<APP_HOST>/app/bundle.json' from origin
'https://<POD_HOST>' has been blocked by CORS policy: No
'Access-Control-Allow-Origin' header is present
```

Two distinct causes, and they look identical:

1. **Your backend is down.** The edge's own 5xx page carries no CORS headers. Fix the
   backend and the CORS error evaporates. **Check this first** — it is the common case.
2. **Genuinely missing CORS.** The client fetches `bundle.json` cross-origin, so the
   response needs `Access-Control-Allow-Origin`. Verify with an explicit `Origin`:

```bash
curl -s -D - -o /dev/null -H "Origin: https://<POD_HOST>" \
  https://<APP_HOST>/app/bundle.json | grep -i access-control
```

## App in Marketplace but not in the left nav

In order of likelihood:

1. **A hand-rolled `symphony-api.js` shim is intercepting everything.** Tell-tale: the
   console shows a tidy sequence of successes (`connected`, `registered`,
   `nav added`) and nothing happens in the UI. A real SDK failure produces a real
   rejection. Successful logs with zero effect ⇒ the logs are fabricated locally.
   Delete the shim.
2. **CoT is required and `getAppToken` is failing.** `TRUST_APP` in the bundle means
   the client will not complete registration. Check the network tab for your
   `/cot/token` call.
3. **`ADK.start({ id })` ≠ `appGroupId`** in the admin-portal bundle.
4. **The controller never loaded.** Confirm `bundle.json` → its inner `url` →
   controller HTML → bundle `.js` all return 200. A stale cache-buster on that inner
   `url` will serve an old controller.

## Nav item works, module spins forever

**The view frame never called `ADK.connectView()`.** The client holds the module in
its loading state until the view handshakes. The page will be HTTP 200 with no console
errors, which is why this is confusing.

Confirm the view bundle is actually referenced and served:

```bash
curl -s https://<APP_HOST>/app/index.html | grep -o 'dart-view\.js[^"]*'
curl -s -o /dev/null -w '%{http_code}\n' https://<APP_HOST>/app/<view-bundle>.js
```

Expected log: `[View] Connected to Symphony client: {...}`.

## `401 Subject must be a string` on `jwt/validate`

PyJWT ≥ 2.10 enforces RFC 7519's requirement that `sub` be a StringOrURI. Symphony's
user JWT puts the **numeric userId** there. Pass `verify_sub=False`; identity comes
from the `user` claim. Keep `algorithms=["RS512"]` pinned.

Note this failure is **silent in the ADK logs** — registration continues and the nav
item appears. Only the network tab shows the 401.

## `401 token pair does not match`

- Ta aged out of the store (Ts lives ~5 min) → restart the handshake, don't retry.
- More than one replica and a process-local store → the validate call hit a process
  that never saw the pair. Either `replicas: 1`, a shared store, or session affinity.

## Pod stuck in `ContainerCreating`

```
MountVolume.SetUp failed for volume "<name>" : secret "<name>" not found
```

A non-optional secret volume was added without provisioning the secret. With
`maxUnavailable: 1` at `replicas: 1` this is a **full outage**, because the old pod is
torn down before the new one is ready. Fix forward by provisioning the secret; prevent
recurrence with `maxUnavailable: 0`.

## `CrashLoopBackOff` immediately after a new import

Importing a module for its side-effect-free helper can drag in a package `__init__`
that does real work at import time. Observed:

```
FileNotFoundError: '.../site-packages/data/read_receipts.log'
  server.py -> src/interfaces/web/__init__.py -> web/app.py:24 (logging.FileHandler)
```

The `__init__.py` imported an unrelated web app whose module body opened a log file in
a directory excluded from the image. **Check the whole import chain in the traceback,
not just your own file**, and prefer a package path whose `__init__.py` is empty.

## Browser out-of-memory / `ERR_INSUFFICIENT_RESOURCES`

Usually client-wide, not yours — a small app is two ~125 KB scripts and two iframes
with no timers. Before blaming your app, check ordering: if the first
`ERR_INSUFFICIENT_RESOURCES` predates your app's first log line, exhaustion was
already underway.

One mechanism that *is* yours: a module stuck in its loading state may be retried,
accumulating iframes. Fix `connectView()` first, then measure.

To attribute it properly: fully quit the browser (not just reload), reopen, and watch
the tab in the browser's task manager while exercising your app. Unbounded growth ⇒
yours. Flat ⇒ the client or another extension.

## Verification matrix

`references/verify.sh <APP_HOST> <POD_HOST>` automates the checks below.

| Check | Expected |
|---|---|
| `/app/bundle.json` with `Origin:` | 200 + `access-control-allow-origin` |
| controller HTML, controller bundle, view bundle | 200, plausible byte counts |
| `/app/<nonexistent>.json` | different from the real files |
| `POST /api/v1/cot/token` | 200 `{"appToken": "..."}` |
| validate with forged Ts | 401 |
| validate with unknown Ta | 401 |
| validate with missing fields | 400 |
| `jwt/validate` with garbage | 401, **not** 500 |
| `GET <POD_HOST>/pod/v1/podcert` | 200 + PEM certificate |
