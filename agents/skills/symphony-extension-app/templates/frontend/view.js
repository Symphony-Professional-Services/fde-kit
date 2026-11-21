/**
 * Symphony extension app -- VIEW frame.
 *
 * Load this from EVERY page the controller opens as a module.
 *
 * This is not optional and not cosmetic: the Symphony client keeps a module in its
 * loading state until the view frame handshakes. A view that never calls
 * connectView() renders as an indefinite spinner even though the page returned 200
 * with no console errors.
 *
 * Separate from controller.js because a view must NOT call ADK.start() and does not
 * own Circle of Trust.
 *
 * Placeholder to replace: {{APP_ID}}
 */

import * as ADK from '@symphony-ui/adk';

const APP_ID = '{{APP_ID}}';

ADK.connectView({ id: APP_ID })
  .then((info) => {
    console.log('[View] Connected to Symphony client:', {
      userReferenceId: info && info.userReferenceId,
      locale: info && info.locale,
    });
  })
  .catch((err) => {
    // Log and continue: the page stays usable when opened directly in a browser
    // tab for debugging, it just won't be theme-aware.
    console.error('[View] connectView FAILED:', err);
  });
