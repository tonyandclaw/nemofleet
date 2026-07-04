#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# whereami.sh — 重開機後一眼看:該用哪個 URL 連儀表板 + 整個 stack 健康狀態 + TLS/IP 是否對齊。
# 用法:bash scripts/whereami.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"
export PATH="$HOME/.local/bin:$NEMOFLEET_NODE_BIN:/usr/local/bin:/usr/bin:/bin:$PATH"
g(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
r(){ printf '  \033[31m✗\033[0m %s\n' "$*"; }
hr(){ printf '\n\033[1;36m%s\033[0m\n' "$*"; }
IP=$(ip -4 -o addr show eth0 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}' | head -1)
TOKEN=$(cat $BRIDGE_DIR/.bridge-token 2>/dev/null)

hr "🔗 連線網址(目前 WiFi/WSL IP = ${IP:-未知})"
echo "  Windows 本機 / 同 WiFi 裝置: https://${IP:-127.0.0.1}:8899"
echo "  localhost:                   https://127.0.0.1:8899"

hr "📊 儀表板 :8899"
code=$(curl -sk -m4 -o /dev/null -w '%{http_code}' https://127.0.0.1:8899/login 2>/dev/null)
[ "$code" = 200 ] && g "https 正常(200)" || r "未回應(code=$code → 跑 bash scripts/boot-stack.sh;log /tmp/agent-dashboard.log)"
ss -ltn 2>/dev/null | grep -q '0.0.0.0:8899' && g "監聽 0.0.0.0:8899(對 LAN 開放)" || r "未監聽 0.0.0.0(可能只 localhost / 沒起)"
if [ -n "$IP" ] && openssl x509 -in $BRIDGE_DIR/dash-cert.pem -noout -ext subjectAltName 2>/dev/null | grep -q "$IP"; then
  g "TLS 憑證 SAN 含目前 IP($IP)→ 裝過 CA 的瀏覽器零警告"
else
  r "TLS 憑證 SAN 不含 $IP → bash scripts/gen-dash-ca.sh 重簽,再 boot-stack 重啟"
fi

hr "🧩 Stack 健康"
GWP="${NEMOCLAW_GATEWAY_PORT:-8080}"; gw=$(curl -s -m3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$GWP/" 2>/dev/null); { [ -n "$gw" ] && [ "$gw" != 000 ]; } && g "OpenShell gateway :$GWP" || r "gateway :$GWP 未起"
hm=$(curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8642/v1/models 2>/dev/null); { [ -n "$hm" ] && [ "$hm" != 000 ]; } && g "Hermes API :8642" || r "Hermes :8642 未起"
for entry in "worker-a:A" "worker-b:B"; do
  frag=${entry%%:*}; ct=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -m1 "$frag")
  if [ -n "$ct" ]; then
    c=$(docker exec "$ct" sh -c "curl -s -m4 -o /dev/null -w '%{http_code}' -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/health" 2>/dev/null)
    [ "$c" = 200 ] && g "worker $frag :9099 健康" || r "worker $frag :9099 異常($c)"
  else r "worker $frag 容器不在"; fi
done
g "容器運行中:$(docker ps --format '{{.Names}}' 2>/dev/null | wc -l)"

hr "🩺 開機自啟 / 排程"
crontab -l 2>/dev/null | grep -q boot-stack-autostart && g "@reboot 自啟 stack 已設" || r "@reboot 自啟未設"
crontab -l 2>/dev/null | grep -q ebg19p-compliance && g "機隊同步 cron 已設(每 5 分)" || r "機隊同步 cron 未設"
echo
echo "  提醒:LAN 連不到時 → Windows 系統管理員 PowerShell 開 8899 inbound;CA 根憑證 $BRIDGE_DIR/dash-ca.pem 各裝置裝一次。"
