/**
 * Symphony extension app -- CONTROLLER frame.
 *
 * Served by controller.html, which is the `url` in the client-fetched bundle.json
 * and the `loadUrl` in the admin-portal bundle. This frame is invisible; its only
 * jobs are to register the app, add the left-nav entry, and register any custom
 * entity renderer.
 *
 * Built with esbuild into the static dir. ADK ships CommonJS only, so it cannot be
 * loaded from a <script> tag without this bundling step.
 *
 * Placeholders to replace: {{APP_ID}} {{APP_TITLE}} {{ENTITY_TYPE}} {{VIEW_PATH}}
 */

import * as ADK from '@symphony-ui/adk';

// MUST equal `appGroupId` in the admin-portal bundle, or the client rejects us.
const APP_ID = '{{APP_ID}}';
const APP_TITLE = '{{APP_TITLE}}';
const ENTITY_TYPE = '{{ENTITY_TYPE}}';

// Absolute URLs: the Symphony client resolves relative paths against its own
// origin, not ours.
const BASE_URL = window.location.origin;
const VIEW_URL = `${BASE_URL}{{VIEW_PATH}}`;
const ICON_URL = `${BASE_URL}/app/icon.svg`;

function openApp(recordId) {
  const url = recordId ? `${VIEW_URL}?id=${encodeURIComponent(recordId)}` : VIEW_URL;
  // Pin moduleId so repeated opens focus one tab. Without it ADK derives the id
  // from the URL, so each distinct query string becomes its own tab.
  return ADK.modules.open(url, { title: APP_TITLE, moduleId: APP_ID });
}

async function postJson(path, body) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`${path} -> ${res.status} ${data.error || res.statusText}`);
  }
  return data;
}

/**
 * Circle of Trust. REQUIRED if the app bundle declares TRUST_APP / rsaKey --
 * the client will not release user identity without it. Delete this object and
 * the `circleOfTrust` argument below if the app is not a trusted app.
 *
 * ADK drives these in order: getAppToken -> register(tokenA) ->
 * validateAppToken(tokenA, tokenS) -> getJwt() -> validateJwt(jwt).
 *
 * Each MUST reject on failure. Note ADK catches the abort and only logs
 * AdkError, so a failure here still leaves the nav item present with identity
 * untrusted -- verify these endpoints return 200 in the network tab.
 */
const circleOfTrust = {
  getAppToken: async () => {
    const { appToken } = await postJson('/api/v1/cot/token');
    console.log('[App] CoT: obtained app token (Ta)');
    return appToken;
  },

  // ADK's (tokenA, tokenS).
  validateAppToken: async (appToken, symphonyToken) => {
    await postJson('/api/v1/cot/tokens/validate', { appToken, symphonyToken });
    console.log('[App] CoT: token pair validated');
  },

  validateJwt: async (jwt) => {
    const user = await postJson('/api/v1/cot/jwt/validate', { jwt });
    console.log('[App] CoT: user JWT verified, userId=%s', user.userId);
  },
};

async function main() {
  console.log('[App] Starting ADK, appId=%s', APP_ID);

  await ADK.start({ id: APP_ID, circleOfTrust });
  console.log('[App] ADK connected to Symphony client');

  // add(title, onClick, icon): onClick is a BARE FUNCTION. The published docs
  // show `{ onClick: ... }`, but lib/impl/Navigation.d.ts declares
  // `onClick: () => void`. The type declaration wins.
  const navItem = ADK.navigation.add(APP_TITLE, () => openApp(), ICON_URL);
  console.log('[App] Left-nav item added');

  // Optional: inline rendering of a custom entity in chat. Remove if unused.
  ADK.messages.registerRenderer(
    ENTITY_TYPE,
    (entityData) => ({
      template: `
        <entity>
          <action class="tk-button tk-button--primary" id="open_app" />
        </entity>
      `,
      actions: {
        open_app: {
          label: entityData.label || `Open in ${APP_TITLE}`,
          data: { recordId: entityData.recordId },
        },
      },
    }),
    (actionId, actionPayload) => {
      if (actionId === 'open_app') {
        openApp(actionPayload && actionPayload.data && actionPayload.data.recordId);
      }
    }
  );
  console.log('[App] Entity renderer registered for %s', ENTITY_TYPE);

  return navItem;
}

main().catch((err) => {
  // The signal that matters: a real rejection from the Symphony client.
  console.error('[App] ADK registration FAILED:', err);
});
