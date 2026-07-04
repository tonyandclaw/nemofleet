#!/usr/bin/env bash
# tests/integration/dashboard_serving.sh — start the dashboard standalone (plain python3) and verify
# SPA serving, ETag/304 caching, the path-traversal guard, and the / -> /app default (classic at
# /classic). CI-able: needs only python3 + curl. Fully isolated — all user/auth/seed/audit files go
# to a temp dir via the DASH_*_FILE env overrides, so real dashboard state is never touched.
set -uo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT=18989; PASS=0; FAIL=0
ok(){ echo "  PASS: $*"; PASS=$((PASS + 1)); }
bad(){ echo "  FAIL: $*"; FAIL=$((FAIL + 1)); }
T=$(mktemp -d); DPID=""
cleanup(){ [ -n "$DPID" ] && { kill "$DPID" 2>/dev/null; wait "$DPID" 2>/dev/null; }; rm -rf "$T"; }
trap cleanup EXIT
printf '{"email":"ci@test.local","password":"Ci-pw-123456","role":"admin","must_change":false}\n' > "$T/seed.json"

DASHBOARD_PORT=$PORT DASH_SEED_FILE="$T/seed.json" DASH_USERS_FILE="$T/users.json" \
  DASH_AUTH_FILE="$T/auth.json" DASH_AUDIT_FILE="$T/audit.jsonl" \
  python3 "$R/services/bridge/agent-dashboard.py" >/tmp/dash-ci.log 2>&1 &
DPID=$!; for _ in $(seq 20); do curl -s -m1 -o /dev/null "http://127.0.0.1:$PORT/login" && break; sleep 0.5; done

# unauth
[ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/app")" = 302 ] && ok "/app (no auth) -> 302 login" || bad "/app no-auth"
[ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/app/app.js")" = 401 ] && ok "/app asset (no auth) -> 401" || bad "asset no-auth"

SID=$(curl -s -D - -o /dev/null -X POST "http://127.0.0.1:$PORT/api/login" -H 'Content-Type: application/json' \
  -d '{"email":"ci@test.local","password":"Ci-pw-123456"}' | sed -n 's/.*sid=\([^;]*\).*/\1/p')
[ -n "$SID" ] && ok "login ok" || bad "no session"
C="Cookie: sid=$SID"

# #1 flip: / -> /app default, classic at /classic
loc=$(curl -s -o /dev/null -D - -H "$C" "http://127.0.0.1:$PORT/" | sed -n 's/\r$//;s/^[Ll]ocation: *//p')
[ "$loc" = /app ] && ok "/ redirects to /app (SPA is default)" || bad "/ location: '$loc'"
CL=$(curl -s -H "$C" "http://127.0.0.1:$PORT/classic")   # large body → pipe-free match (grep -q would SIGPIPE echo under pipefail)
case "$CL" in *"<!doctype"*|*"<!DOCTYPE"*) ok "/classic still serves the legacy UI (fallback)" ;; *) bad "/classic missing (len ${#CL})" ;; esac

# SPA index + assets
body=$(curl -s -H "$C" "http://127.0.0.1:$PORT/app")
echo "$body" | grep -q 'id="root"' && echo "$body" | grep -q '/app/app.js' && ok "/app serves the SPA index" || bad "SPA index wrong"
echo "$(curl -s -o /dev/null -w '%{content_type}' -H "$C" "http://127.0.0.1:$PORT/app/app.js")" | grep -q javascript && ok "app.js served as JS" || bad "app.js content-type"
[ "$(curl -s -H "$C" "http://127.0.0.1:$PORT/app/vendor/react.production.min.js" | wc -c)" -gt 5000 ] && ok "vendored react served" || bad "react vendor size"

# ETag / 304 / cache policy
HH=$(curl -s -D - -o /dev/null -H "$C" "http://127.0.0.1:$PORT/app/app.js")
ET=$(printf '%s' "$HH" | sed -n 's/\r$//;s/^[Ee][Tt]ag: *//p')
[ -n "$ET" ] && ok "ETag present on app.js" || bad "no ETag"
printf '%s' "$HH" | grep -qi 'cache-control: no-cache' && ok "app files: no-cache/must-revalidate" || bad "app cache-control"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "$C" -H "If-None-Match: $ET" "http://127.0.0.1:$PORT/app/app.js")" = 304 ] && ok "If-None-Match -> 304" || bad "expected 304"
curl -s -D - -o /dev/null -H "$C" "http://127.0.0.1:$PORT/app/vendor/chart.umd.js" | grep -qi immutable && ok "vendor libs: immutable long cache" || bad "vendor not immutable"

# path traversal guard
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "$C" "http://127.0.0.1:$PORT/app/../agent-dashboard.py")" = 404 ] && ok "path-traversal blocked (404)" || bad "traversal not blocked"

echo "== dashboard_serving: $PASS pass, $FAIL fail =="
exit "$FAIL"
