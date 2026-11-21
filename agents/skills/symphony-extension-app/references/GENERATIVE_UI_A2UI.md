# Dual-Host Generative UI (`A2UI v1.0` + `SEP-1865`) Integration Guide

**Target:** Symphony Extension Apps (`Client2` / ADK), Claude Desktop / Standard MCP App Hosts (`SEP-1865`), and `template-mcp`
**Authoritative Master Guide:** **[`docs/A2UI_EXTENSION_GUIDE.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/A2UI_EXTENSION_GUIDE.md)**
**Architecture Spec:** [`docs/MCP_SERVER_AND_APP_ARCHITECTURE_SPEC.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/MCP_SERVER_AND_APP_ARCHITECTURE_SPEC.md)

---

## 1. Overview & Why A2UI v1.0 Replaces Bespoke Widget Bundles

Historically, rendering rich UI in Symphony chat required writing, bundling, and redeploying bespoke frontend widgets for every tool (`registerChartRenderer`, custom React/CopilotKit bundles), while remaining incompatible with non-Symphony MCP hosts.

`template-mcp` ships an **opt-in, zero-build Dual-Host A2UI v1.0 Extension** (`src/extensions/a2ui/`, gated behind `ENABLE_A2UI=true` or `--a2ui` at scaffold time) that solves both problems simultaneously:
1. **A2UI v1.0 Wire Envelope (`application/a2ui+json`)**: Backend tools emit flat, declarative JSON component lists (`id: "root"`) + `dataModel` (`@path` two-way bindings, `visibleWhen`, `Tabs`) across 5 canonical SDS archetypes (`overview_stats`, `progressive_wizard`, `execution_progress`, `item_receipt_list`, `approval_gate`) or custom domain builders.
2. **Symphony Client2 Host (`EntityJSON` + ADK)**: `web/adk/controller.js` registers a single universal renderer (`com.symphony.a2ui.surface`), mounting a strict ExtensionML `<entity><iframe width="460px" height="{H}px" src=".../app/a2ui-surface.html?inline=1#a2ui=..."/></entity>` card with 0-RTT hash hydration and 1-click `SIDE_BY_SIDE` companion escalation (`/app/index.html?embed=companion`).
3. **Claude Desktop & Standard MCP App Hosts (`SEP-1865` / `2026-01-26`)**: `mcp_bindings.py` registers `@mcp.resource("ui://<app>/a2ui/{surface_type}/{target_id}", mime_type="text/html;profile=mcp-app")` and returns `_meta.ui` + `_meta.a2ui` from `@mcp.tool()`, speaking JSON-RPC 2.0 (`ui/initialize`, `ui/notifications/tool-result`, `ui/size-change`, and `tools/call` -> `a2ui_dispatch_action`) over `postMessage`.

---

## 2. Authoritative A2UI v1.0 Envelope Schema (`protocol.py`)

Every A2UI v1.0 message declares `"version": "1.0"`, `"mimeType": "application/a2ui+json"`, and **exactly one** control key (`createSurface`, `updateComponents`, `updateDataModel`, or `deleteSurface`). Legacy v0.9 keys (`theme`, `primaryColor`, `Surface`, nested JSX trees) are rejected.

```json
{
  "version": "1.0",
  "mimeType": "application/a2ui+json",
  "createSurface": {
    "surfaceId": "overview_stats:fx_spot",
    "catalogId": "https://symphony.com/a2ui/v1_0/catalogs/sds/catalog.json",
    "components": [
      { "id": "root", "component": "Card", "child": "main_col" },
      { "id": "main_col", "component": "Column", "gap": "sm", "children": ["hdr_row", "subtitle_txt", "kpi_strip", "trend_bars", "actions"] },
      { "id": "hdr_row", "component": "Row", "justify": "between", "align": "center", "children": ["hdr_title", "health_pill"] },
      { "id": "hdr_title", "component": "Text", "variant": "h3", "text": { "@path": "/header/title" } },
      { "id": "health_pill", "component": "StatusPill", "label": { "@path": "/status/label" }, "tone": { "@path": "/status/tone" } },
      { "id": "subtitle_txt", "component": "Text", "variant": "caption", "text": { "@path": "/header/subtitle" } },
      { "id": "kpi_strip", "component": "MetricStrip", "metrics": { "@path": "/metrics" } },
      { "id": "trend_bars", "component": "SparklineBar", "label": "Hourly throughput", "values": { "@path": "/series" } },
      { "id": "actions", "component": "Row", "justify": "end", "gap": "xs", "children": ["dock_btn", "refresh_btn"] },
      {
        "id": "dock_btn",
        "component": "Button",
        "label": "Open in workspace",
        "variant": "secondary",
        "hostOnly": "symphony",
        "action": { "name": "open_companion", "context": { "tab": "overview" } }
      },
      {
        "id": "refresh_btn",
        "component": "Button",
        "label": "Refresh metrics",
        "variant": "primary",
        "action": { "name": "refresh_overview", "context": { "desk": "fx_spot" } }
      }
    ],
    "dataModel": {
      "header": { "title": "FX Spot execution summary", "subtitle": "London · Last 60m" },
      "status": { "label": "Healthy", "tone": "positive" },
      "metrics": [
        { "label": "Pair", "value": "EUR/USD" },
        { "label": "Notional", "value": "$10.0M" },
        { "label": "Spread", "value": "0.85 bps" }
      ],
      "series": [42, 58, 64, 61, 79, 84]
    }
  }
}
```

---

## 3. Symphony ADK Controller Registration (`web/adk/controller.js`)

**Critical ExtensionML Rule**: Symphony's sanitizer strips or rejects `<iframe>` elements containing `id`, `class`, `style`, `frameborder`, or `allowtransparency`. Pass **only** `src`, `width`, and `height` (`<= 1000px`), and XML-escape `&` as `&amp;`:

```javascript
const APP_ID = 'APP_NAME';
const ENTITY_TYPE = 'com.symphony.a2ui.surface';

function escapeXmlAttr(value) {
  return String(value || '')
    .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const renderEntity = (entityData) => {
  const payload = (entityData && entityData.a2uiSurface) ? entityData.a2uiSurface : (entityData || {});
  const surfaceType = String(payload.surfaceType || 'overview_stats');
  const clampedHeight = Math.max(180, Math.min(960, Number(payload.preferredHeight) || 348));
  const fallbackUrl = `${window.location.origin}/app/a2ui-surface.html?surface=${encodeURIComponent(surfaceType)}&inline=1`;
  const safeUrl = escapeXmlAttr(payload.a2uiSurfaceUrl || fallbackUrl);
  return {
    template: `<entity><iframe src="${safeUrl}" width="460px" height="${clampedHeight}px"/></entity>`,
    actions: {}
  };
};
ADK.messages.registerRenderer(ENTITY_TYPE, renderEntity);

function handleBridgeMsg(event) {
  if (event.origin !== window.location.origin) return;
  const msg = event.data;
  if (!msg || typeof msg !== 'object') return;
  if (msg.type === 'a2ui:open_companion') {
    const url = `${window.location.origin}/app/index.html?embed=companion&tab=${encodeURIComponent(msg.tab || 'overview')}`;
    ADK.modules.open(url, { title: `${APP_ID} Workspace`, moduleId: `${APP_ID}-companion`, openMode: 'SIDE_BY_SIDE' });
  } else if (msg.type === 'a2ui:open_modal' && msg.url && ADK.dialogs && typeof ADK.dialogs.show === 'function') {
    const safeModalUrl = escapeXmlAttr(new URL(msg.url, window.location.origin).toString());
    const safeTitle = escapeXmlAttr(msg.title || APP_ID);
    const templateHtml = `<dialog><h3>${safeTitle}</h3><iframe src="${safeModalUrl}" width="100%" height="520px"/><action id="close_dialog" class="tk-button tk-button--secondary tk-button--medium"/></dialog>`;
    const dialog = ADK.dialogs.show(templateHtml, {
      size: 'large',
      actions: { close_dialog: { label: 'Close', action: () => dialog.close() } },
    });
  }
}
```

---

## 4. Claude Desktop & Standard MCP App Contract (`SEP-1865`)

In `src/extensions/a2ui/mcp_bindings.py`, tools return `CallToolResult` with `_meta.ui` + `_meta.a2ui` and JSON `TextContent` body `"symphony": {"presentationML": ..., "entityJSON": ...}`, paired with a self-contained `text/html;profile=mcp-app` `ui://` resource:

```python
@mcp.resource("ui://template-mcp/a2ui/{surface_type}/{target_id}", mime_type="text/html;profile=mcp-app")
def read_a2ui_mcp_app_surface(surface_type: str, target_id: str) -> str:
    """Self-contained HTML shell bundling symphony-tokens.css + app-tokens.css + a2ui-renderer.js."""
    ...

@mcp.tool()
def render_a2ui_surface(surface_type: str = "overview_stats", target_id: str = "default") -> CallToolResult:
    ...
    meta_payload = {
        "ui": {
            "resourceUri": f"ui://{slug}/a2ui/{surface_type}/{target_id}",
            "iframeUrl": iframe_url,
            "preferredFrameSize": ["460px", f"{height}px"],
            "mcpAppsSpec": "2026-01-26",
        },
        "a2ui": {
            "version": "1.0",
            "mimeType": "application/a2ui+json",
            "surfaceId": surface_id,
            "surfaceType": surface_type,
            "surfaceToken": token,
            "messages": [envelope],
        },
    }
    body_payload = {
        "status": "ok",
        "surfaceId": surface_id,
        "surfaceType": surface_type,
        "preferredHeight": height,
        "symphony": {"presentationML": pml, "entityJSON": entity_json},
        "_meta": meta_payload,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body_payload, indent=2))],
        _meta=meta_payload,
    )
```

---

## 5. Zero-Build Vanilla Renderer & Locked `❖ SDS Core UI` v1.0.0 Rules

`src/extensions/a2ui/static/a2ui-renderer.js` (`~12 KB` gzipped / `~42 KB` unminified, zero React/build runtime) enforces strict security and design invariants:
1. **DOM Construction Only (`createElement` / `textContent`)**: Never passes untrusted payload values into `innerHTML`. Unknown component names fall back to a safe semantic note (`color: var(--muted-foreground)` — never hardcoded `'red'` or `'#888'`).
2. **Two-Layer `❖ SDS Core UI` v1.0.0 Tokens**: Load `symphony-tokens.css` verbatim first, then `app-tokens.css` (`var(--sds-*)` primitives only, including Light `-60` / Dark `-30`/`-20` `--app-*-fg` WCAG AA foreground tokens; `0` findings under `token_audit.py --strict`).
3. **Transparent Inline Canvas**: Inline card pages set `html, body { color-scheme: normal !important; background: transparent !important; }` + `html.inline-chat-frame { overflow-x: hidden; overflow-y: auto; }` so rounded `8px` (`--radius-md`) corners never show opaque dark rectangles in Light-Mode chat bubbles.
4. **Scoped `st_...` `surface_token` RBAC**: Interactive `POST /api/v1/a2ui/action` mutations verify HMAC-SHA256 `st_...` role claims (`operator`/`admin` allowed; `recipient` -> HTTP `403`).
5. **Anti-AI-Slop Craft Floor**: Enforce `>= 12px` text floor, `tabular-nums` on all metrics, Sentence-case `--radius-pill` buttons (`<= 1` primary CTA, `<= 3` buttons/row), static `6px` status dots, `2.1s` feathered white-ice active progress sheen, and zero `>1px` colored left stripes, stacked uppercase kickers, nested cards, or `window.alert/confirm/prompt` dialogs.
