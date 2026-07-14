#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# gen-dash-ca.sh — 自建本機 CA + 簽發儀表板伺服器憑證(把 CA 裝進裝置信任清單後,browser 零警告)。
# 私有 IP 無法用公開 CA(Let's Encrypt 不簽),故走「自管 CA」。
# CA 只建一次、之後重用;IP 變了重跑只重簽伺服器憑證,各裝置「不必重裝 CA」。
# 用法:bash scripts/gen-dash-ca.sh [IP]   IP 省略則自動抓主要 LAN IP(default-route source,不管介面叫什麼名字)
set -uo pipefail
DIR=$NEMOFLEET_ROOT; B="$BRIDGE_DIR"
IP="${1:-$(primary_ip)}"
[ -n "$IP" ] || { echo "抓不到 IP,請手動帶:bash scripts/gen-dash-ca.sh 10.88.23.85" >&2; exit 1; }
CA_KEY="$B/dash-ca-key.pem"; CA_CRT="$B/dash-ca.pem"

# 1) 本機 CA(重用)
if [ ! -s "$CA_CRT" ]; then
  openssl genrsa -out "$CA_KEY" 4096 2>/dev/null; chmod 600 "$CA_KEY"
  openssl req -x509 -new -nodes -key "$CA_KEY" -sha256 -days 3650 \
    -subj "/CN=NemoClaw Local CA/O=NemoClaw" -out "$CA_CRT" 2>/dev/null
  echo "✓ 已建立本機 CA:$CA_CRT(★需安裝到各裝置信任清單,只裝一次)"
else
  echo "· 重用既有 CA:$CA_CRT(裝過的裝置不必重裝)"
fi

# 2) 伺服器憑證(SAN 含 IP + localhost + hostname;EKU serverAuth → 現代瀏覽器要求)
openssl genrsa -out "$B/dash-key.pem" 3072 2>/dev/null; chmod 600 "$B/dash-key.pem"
SAN="DNS:localhost,DNS:nemoclaw.local,IP:127.0.0.1,IP:$IP"
openssl req -new -key "$B/dash-key.pem" -subj "/CN=nemoclaw-dashboard" -out /tmp/dash-ca.csr 2>/dev/null
openssl x509 -req -in /tmp/dash-ca.csr -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -days 825 -sha256 \
  -extfile <(printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n" "$SAN") \
  -out "$B/dash-cert.pem" 2>/dev/null
chmod 644 "$B/dash-cert.pem"; rm -f /tmp/dash-ca.csr
echo "✓ 已簽發伺服器憑證 $B/dash-cert.pem"
echo "  SAN: $SAN"
echo "  重啟讓它生效:fuser -k 8899/tcp; DASH_BIND=0.0.0.0 DASH_TLS=1 setsid python3 $B/agent-dashboard.py >/tmp/agent-dashboard.log 2>&1 &"
echo "  安裝 CA(各裝置只一次):把 $CA_CRT 拷到裝置 → Windows 匯入「受信任的根憑證授權單位」;iOS/Android 安裝憑證描述檔並啟用信任。"
