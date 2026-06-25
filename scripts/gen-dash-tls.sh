#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# gen-dash-tls.sh — 產生儀表板自簽 TLS 憑證(P1-6,選用)。
# 產生後以 DASH_TLS=1 啟動 dashboard 即走 https://127.0.0.1:8899。
# 用法:bash scripts/gen-dash-tls.sh  然後  DASH_TLS=1 python3 $BRIDGE_DIR/agent-dashboard.py
set -uo pipefail
DIR=$NEMOFLEET_ROOT; B="$BRIDGE_DIR"
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 \
  -keyout "$B/dash-key.pem" -out "$B/dash-cert.pem" \
  -subj "/CN=nemoclaw-dashboard.local" \
  -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" >/dev/null 2>&1
chmod 600 "$B/dash-key.pem"; chmod 644 "$B/dash-cert.pem"
echo "✓ 已產生 $B/dash-cert.pem 與 dash-key.pem(RSA-3072 / SHA-256 / 825 天)"
echo "  啟用:fuser -k 8899/tcp; DASH_TLS=1 setsid python3 $B/agent-dashboard.py >/tmp/agent-dashboard.log 2>&1 &"
echo "  注意:自簽憑證瀏覽器會提示一次例外(localhost 用途可接受)。"
