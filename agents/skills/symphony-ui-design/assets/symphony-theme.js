/* Symphony host theme sync for vanilla (non-React) pages.
 *
 * Inside an ADK view you do NOT need this: connectView() already puts
 * `light|dark` and `spacious|condensed` on <body> and follows themeChangeV2.
 * Load it on pages the ADK view does not drive (standalone pages, the
 * controller page, local previews) so symphony-tokens.css still gets a theme.
 *
 * Signals, first match wins:
 *   1. ?theme=light|dark in the URL
 *   2. AI Studio style ?id=<app>_<theme>
 *   3. window.parent.currentThemeName (same-origin hosts)
 *   4. postMessage {type: 'themeChange', theme: 'light'|'dark'} from the host
 *   5. otherwise nothing is set and the CSS follows prefers-color-scheme
 */
(function () {
  var THEMES = ['light', 'dark'];

  function apply(theme) {
    if (THEMES.indexOf(theme) === -1 || !document.body) return;
    document.body.classList.remove('light', 'dark');
    document.body.classList.add(theme);
  }

  function initial() {
    var params = new URLSearchParams(window.location.search);
    var t = params.get('theme');
    if (THEMES.indexOf(t) !== -1) return t;
    t = (params.get('id') || '').split('_')[1];
    if (THEMES.indexOf(t) !== -1) return t;
    try {
      t = window.parent && window.parent !== window && window.parent.currentThemeName;
      if (THEMES.indexOf(t) !== -1) return t;
    } catch (e) { /* cross-origin parent */ }
    return null;
  }

  function start() {
    var t = initial();
    if (t) apply(t);
    window.addEventListener('message', function (event) {
      if (event.source !== window.parent && event.source !== window) return;
      var d = event.data;
      if (d && d.type === 'themeChange') apply(d.theme);
    });
  }

  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start);
})();
