#!/usr/bin/env bash
# Verify a deployed Symphony extension app end to end, from outside the cluster.
#
#   ./verify.sh <APP_HOST> <POD_HOST> [APP_ID]
#   ./verify.sh mss.uat.symphony.com my-pod.on.uat.symphony.com my-app
#
# Exits non-zero if any REQUIRED check fails. Safe to run repeatedly; the only
# state it creates is short-lived Circle of Trust tokens.
#
# Everything here is a black-box check. If something fails, go to pod logs and
# `kubectl describe pod` next -- see references/DEBUGGING.md.

set -uo pipefail

APP_HOST="${1:?usage: verify.sh <APP_HOST> <POD_HOST> [APP_ID]}"
POD_HOST="${2:?usage: verify.sh <APP_HOST> <POD_HOST> [APP_ID]}"
APP_ID="${3:-}"

B="https://${APP_HOST}"
ORIGIN="https://${POD_HOST}"
FAILURES=0
CURL=(curl -sS -m 25)

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; }
head_() { printf '\n\033[1m%s\n\033[0m' "$1"; }

code_of() { "${CURL[@]}" -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || echo 000; }

# ---------------------------------------------------------------------------
head_ "1. Is the backend actually alive?"
# Probe an UNCACHEABLE path. A CDN caches .png/.css/.js but not .html/.json, so
# cached 200s on assets can mask a completely dead origin.
for p in /healthcheck /app/controller.html; do
  c=$(code_of "$B$p")
  [ "$c" = "200" ] && pass "$p -> 200" || fail "$p -> $c (uncacheable path; suspect no healthy backend)"
done

# A path that cannot exist. If it returns the same status as real files, you are
# not looking at per-file 404s -- the whole backend is down or shadowed.
c=$(code_of "$B/app/zzz-does-not-exist-$$.json")
if [ "$c" = "404" ]; then
  pass "nonexistent .json -> 404 (origin is serving and distinguishing paths)"
else
  warn "nonexistent .json -> $c (not 404; edge may be masking origin status)"
fi

# ---------------------------------------------------------------------------
head_ "2. App assets + CORS"
# bundle.json is fetched CROSS-ORIGIN by the client, so it needs CORS headers.
hdrs=$("${CURL[@]}" -D - -o /tmp/vf.$$ -H "Origin: $ORIGIN" "$B/app/bundle.json" 2>/dev/null)
c=$(printf '%s' "$hdrs" | awk 'NR==1{print $2}')
if [ "$c" = "200" ]; then
  pass "bundle.json -> 200 ($(wc -c </tmp/vf.$$) bytes)"
  if printf '%s' "$hdrs" | grep -qi 'access-control-allow-origin'; then
    pass "bundle.json sends Access-Control-Allow-Origin"
  else
    fail "bundle.json has NO Access-Control-Allow-Origin (client fetch will be blocked)"
  fi
  inner=$(grep -oE '"url"[[:space:]]*:[[:space:]]*"[^"]+"' /tmp/vf.$$ | head -1 | sed 's/.*"\(https\?:[^"]*\)".*/\1/')
  if [ -n "$inner" ]; then
    ic=$(code_of "$inner")
    [ "$ic" = "200" ] && pass "bundle.json url -> $inner -> 200" \
                      || fail "bundle.json url -> $inner -> $ic (controller will never load)"
  else
    warn "could not parse the \`url\` field out of bundle.json"
  fi
else
  fail "bundle.json -> $c"
fi
rm -f /tmp/vf.$$

if [ -n "$APP_ID" ]; then
  for f in "/app/${APP_ID}-controller.js" "/app/${APP_ID}-view.js"; do
    c=$("${CURL[@]}" -o /tmp/vb.$$ -w '%{http_code}' "$B$f" 2>/dev/null)
    sz=$(wc -c </tmp/vb.$$ 2>/dev/null || echo 0)
    if [ "$c" = "200" ] && [ "$sz" -gt 50000 ]; then
      pass "$f -> 200 ($sz bytes)"
    else
      fail "$f -> $c ($sz bytes; expected 200 and >50KB)"
    fi
    rm -f /tmp/vb.$$
  done
  if "${CURL[@]}" "$B/app/index.html" 2>/dev/null | grep -q "${APP_ID}-view.js"; then
    pass "index.html references the view bundle (connectView will run)"
  else
    fail "index.html does NOT reference ${APP_ID}-view.js -> modules will spin forever"
  fi
else
  warn "APP_ID not supplied; skipping bundle checks"
fi

# ---------------------------------------------------------------------------
head_ "3. Pod endpoints used by Circle of Trust"
c=$("${CURL[@]}" -o /tmp/vc.$$ -w '%{http_code}' "$ORIGIN/pod/v1/podcert" 2>/dev/null)
if [ "$c" = "200" ] && grep -q "BEGIN CERTIFICATE" /tmp/vc.$$; then
  pass "$ORIGIN/pod/v1/podcert -> 200 with PEM certificate"
else
  fail "$ORIGIN/pod/v1/podcert -> $c (JWT verification cannot work)"
fi
rm -f /tmp/vc.$$

# ---------------------------------------------------------------------------
head_ "4. Circle of Trust endpoint contract"
c=$("${CURL[@]}" -o /tmp/vt.$$ -w '%{http_code}' -X POST \
      -H 'Content-Type: application/json' "$B/api/v1/cot/token" 2>/dev/null)
if [ "$c" = "404" ]; then
  warn "/api/v1/cot/token -> 404; app is not a trusted app (no TRUST_APP), skipping CoT"
elif [ "$c" = "200" ]; then
  TA=$(grep -oE '"appToken"[[:space:]]*:[[:space:]]*"[^"]+"' /tmp/vt.$$ | sed 's/.*"\([^"]*\)"$/\1/')
  if [ -n "$TA" ]; then
    pass "getAppToken -> 200, Ta issued (${#TA} chars) -- pod backend auth works"

    c2=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
          -d "{\"appToken\":\"$TA\",\"symphonyToken\":\"forged\"}" \
          "$B/api/v1/cot/tokens/validate" 2>/dev/null)
    [ "$c2" = "401" ] && pass "forged symphonyToken -> 401" \
                      || fail "forged symphonyToken -> $c2 (expected 401)"

    c3=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
          -d '{"appToken":"never-issued","symphonyToken":"x"}' \
          "$B/api/v1/cot/tokens/validate" 2>/dev/null)
    [ "$c3" = "401" ] && pass "unknown appToken -> 401" \
                      || fail "unknown appToken -> $c3 (expected 401)"

    c4=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
          -d '{}' "$B/api/v1/cot/tokens/validate" 2>/dev/null)
    [ "$c4" = "400" ] && pass "missing fields -> 400" \
                      || fail "missing fields -> $c4 (expected 400)"
  else
    fail "getAppToken -> 200 but no appToken in the body"
  fi
else
  fail "getAppToken -> $c (502 usually means the RSA key is missing or not registered)"
fi
rm -f /tmp/vt.$$

c5=$("${CURL[@]}" -o /tmp/vj.$$ -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
      -d '{"jwt":"not.a.jwt"}' "$B/api/v1/cot/jwt/validate" 2>/dev/null)
case "$c5" in
  401) pass "garbage JWT -> 401 (fails closed)" ;;
  404) warn "jwt/validate -> 404 (no CoT configured)" ;;
  200) fail "garbage JWT -> 200 -- JWT VERIFICATION IS BROKEN" ;;
  *)   fail "garbage JWT -> $c5 (expected 401)" ;;
esac
if grep -qi "Subject must be a string" /tmp/vj.$$ 2>/dev/null; then
  fail "jwt/validate enforces string sub -> real Symphony JWTs will 401. Set verify_sub=False."
fi
rm -f /tmp/vj.$$

# ---------------------------------------------------------------------------
head_ "Result"
if [ "$FAILURES" -eq 0 ]; then
  printf '  \033[32mAll required checks passed.\033[0m\n'
  printf '  Remaining checks need a real client: hard-reload Symphony and confirm\n'
  printf '  BOTH "CoT: user JWT verified" and "[View] Connected to Symphony client".\n'
  exit 0
else
  printf '  \033[31m%d check(s) failed.\033[0m See references/DEBUGGING.md.\n' "$FAILURES"
  exit 1
fi
