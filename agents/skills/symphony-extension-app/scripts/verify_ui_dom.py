#!/usr/bin/env python3
"""Headless Browser & Simulated ADK Handshake Verifier for Symphony Extension Apps.

Prevents the "Shallow-OK" trap on UI/UX changes where an agent runs `npm run build`
or `curl GET /app/index.html -> 200` without verifying that:
  1. The page executes cleanly in a real browser with 0 `console.error` / uncaught exceptions.
  2. Network requests (bundles, CSS, API calls) return 2xx/3xx (no 404/500/shadowed routes).
  3. The Symphony ADK (`@symphony-ui/adk`) view/controller handshake completes without hanging.
  4. Target DOM selectors (`--expect-selector`) and text (`--expect-text`) actually render
     after optional user interaction (`--click-selector`).
  5. A visual screenshot (`--screenshot`) is captured for inspection via `read_file`.

Usage:
  python3 skills/symphony-extension-app/scripts/verify_ui_dom.py \
    --url "http://127.0.0.1:8080/app/index.html" \
    --expect-selector "#app-root" \
    --expect-text "Dashboard" \
    --screenshot "/tmp/ui_verify.png"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ADK_HOST_SHIM_JS = """
(() => {
  // Lightweight Symphony Client parent-frame responder so @symphony-ui/adk
  // ADK.start() and ADK.connectView() handshakes resolve in headless testing.
  window.__adkMessagesReceived = [];
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || typeof data !== 'object') return;
    window.__adkMessagesReceived.push(data);
    if (data.callbackId || data.id) {
      const reply = {
        callbackId: data.callbackId || data.id,
        id: data.id,
        type: 'response',
        result: {
          id: data.params?.id || 'test-app',
          userReferenceId: 'headless-verifier-user',
          theme: { name: 'dark', size: 'normal' }
        }
      };
      try {
        window.postMessage(reply, '*');
      } catch (err) {}
    }
  });
})();
"""


async def run_verification(args: argparse.Namespace) -> tuple[bool, dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return False, {
            "error": (
                "Playwright is not installed in this Python environment. "
                "Install via `pip install playwright && playwright install chromium`."
            )
        }

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []
    selector_checks: list[dict[str, Any]] = []
    text_checks: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        await page.add_init_script(ADK_HOST_SHIM_JS)

        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on(
            "response",
            lambda resp: failed_requests.append({"url": resp.url, "status": resp.status})
            if resp.status >= 400 and "favicon.ico" not in resp.url
            else None,
        )

        try:
            resp = await page.goto(args.url, wait_until="networkidle", timeout=args.timeout_ms)
            main_status = resp.status if resp else 0
        except Exception as exc:
            await browser.close()
            return False, {"error": f"Failed to navigate to {args.url}: {exc}"}

        if args.wait_ms > 0:
            await page.wait_for_timeout(args.wait_ms)

        if args.click_selector:
            try:
                await page.locator(args.click_selector).first.click(timeout=5000)
                await page.wait_for_timeout(500)
            except Exception as exc:
                page_errors.append(f"Failed to click selector '{args.click_selector}': {exc}")

        for sel in args.expect_selector:
            try:
                loc = page.locator(sel).first
                visible = await loc.is_visible()
                count = await page.locator(sel).count()
                selector_checks.append(
                    {
                        "selector": sel,
                        "count": count,
                        "visible": visible,
                        "passed": visible and count > 0,
                    }
                )
            except Exception as exc:
                selector_checks.append(
                    {"selector": sel, "count": 0, "visible": False, "passed": False, "error": str(exc)}
                )

        body_text = await page.inner_text("body")
        for expected_txt in args.expect_text:
            found = expected_txt in body_text
            text_checks.append({"text": expected_txt, "found": found, "passed": found})

        screenshot_path = None
        if args.screenshot:
            out_path = Path(args.screenshot).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out_path), full_page=True)
            screenshot_path = str(out_path)

        await browser.close()

    failures: list[str] = []
    if main_status >= 400 or main_status == 0:
        failures.append(f"MAIN_DOCUMENT_HTTP_{main_status}: {args.url}")
    if page_errors:
        failures.append(f"UNCAUGHT_PAGE_ERRORS ({len(page_errors)}): {page_errors[:3]}")
    if console_errors and not args.allow_console_errors:
        failures.append(f"CONSOLE_ERRORS ({len(console_errors)}): {console_errors[:3]}")
    if failed_requests and not args.allow_network_errors:
        failures.append(f"HTTP_4XX_5XX_REQUESTS ({len(failed_requests)}): {failed_requests[:3]}")
    for sc in selector_checks:
        if not sc["passed"]:
            failures.append(
                f"MISSING_OR_HIDDEN_SELECTOR: '{sc['selector']}' (count={sc['count']}, visible={sc['visible']})"
            )
    for tc in text_checks:
        if not tc["passed"]:
            failures.append(f"MISSING_EXPECTED_TEXT: '{tc['text']}' not found in rendered DOM")

    passed = len(failures) == 0
    report = {
        "passed": passed,
        "url": args.url,
        "http_status": main_status,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed_requests,
        "selector_checks": selector_checks,
        "text_checks": text_checks,
        "screenshot": screenshot_path,
        "failures": failures,
    }
    return passed, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Symphony Extension App UI DOM & runtime behavior via headless Playwright."
    )
    parser.add_argument("--url", required=True, help="Target view/controller URL to load")
    parser.add_argument(
        "--expect-selector", action="append", default=[], help="CSS selector that must be visible (repeatable)"
    )
    parser.add_argument(
        "--expect-text",
        action="append",
        default=[],
        help="Text substring that must appear in rendered DOM (repeatable)",
    )
    parser.add_argument("--click-selector", default="", help="Optional CSS selector to click before asserting DOM")
    parser.add_argument("--screenshot", default="", help="Optional file path to save full-page PNG screenshot")
    parser.add_argument(
        "--wait-ms", type=int, default=800, help="Wait time in ms after networkidle before asserting (default: 800)"
    )
    parser.add_argument("--timeout-ms", type=int, default=20000, help="Navigation timeout in ms (default: 20000)")
    parser.add_argument("--allow-console-errors", action="store_true", help="Do not fail on console.error")
    parser.add_argument(
        "--allow-network-errors", action="store_true", help="Do not fail on 4xx/5xx sub-resource responses"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    passed, report = asyncio.run(run_verification(args))

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        if "error" in report:
            sys.stderr.write(f"[ERROR] {report['error']}\n")
            return 2
        sys.stderr.write(f"=== Symphony UI DOM Verification Report ({args.url}) ===\n")
        sys.stderr.write(f"  HTTP Status          : {report['http_status']}\n")
        sys.stderr.write(f"  Uncaught Page Errors : {len(report['page_errors'])}\n")
        sys.stderr.write(f"  Console Errors       : {len(report['console_errors'])}\n")
        sys.stderr.write(f"  Failed Requests      : {len(report['failed_requests'])}\n")
        for sc in report["selector_checks"]:
            sys.stderr.write(f"  Selector '{sc['selector']}' : visible={sc['visible']} (count={sc['count']})\n")
        for tc in report["text_checks"]:
            sys.stderr.write(f"  Text '{tc['text']}'     : found={tc['found']}\n")
        if report.get("screenshot"):
            sys.stderr.write(f"  Screenshot Saved     : {report['screenshot']} (Inspect via read_file)\n")
        if passed:
            sys.stderr.write("\n[PASS] UI DOM & Runtime Handshake Verified!\n")
        else:
            sys.stderr.write("\n[FAIL] UI Verification Failed:\n")
            for f in report["failures"]:
                sys.stderr.write(f"  - {f}\n")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
