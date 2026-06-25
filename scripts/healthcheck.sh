#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# healthcheck.sh — one-shot health/hygiene check for the combined setup. Zero Azure.
# Usage: healthcheck.sh
set -uo pipefail
:
BUS=$BUS_DIR
ok(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m⚠\033[0m %s\n' "$*"; }

# 時鐘漂移檢查:系統 UTC vs 外部 HTTP Date(權威)。WSL2 在 Windows 睡眠後常漂移;
# 偏差大會弄錯迴圈停時、且會讓 Azure TLS 憑證驗證失敗 → 推理整個掛掉。閾值 120s。
clock_check(){
  local hdr ext sys diff src
  for src in https://www.google.com https://2026msf15.cognitiveservices.azure.com; do
    hdr=$(curl -sI -m 6 "$src" 2>/dev/null | grep -i '^date:' | head -1 | sed 's/^[Dd]ate:[ ]*//;s/\r$//')
    [ -n "$hdr" ] && break
  done
  if [ -z "$hdr" ]; then warn "時鐘漂移:拿不到外部時間,略過(網路?)"; return; fi
  ext=$(date -u -d "$hdr" '+%s' 2>/dev/null); sys=$(date -u '+%s')
  [ -z "$ext" ] && { warn "時鐘漂移:無法解析外部 Date,略過"; return; }
  diff=$(( sys - ext )); diff=${diff#-}
  if [ "$diff" -le 120 ]; then ok "時鐘同步(vs 外部偏差 ${diff}s)"
  else bad "時鐘漂移 ${diff}s(>120s)!會弄錯迴圈停時並可能讓 Azure TLS 失敗 → 校時:sudo hwclock -s 或 wsl --shutdown"; fi
}

echo "== nemofleet healthcheck $(date '+%F %H:%M %Z') =="
clock_check
[ -n "$CT_H" ] && ok "hermes container: $CT_H" || bad "hermes container missing"
[ -n "$CT_O" ] && ok "openclaw container: $CT_O" || bad "openclaw container missing"
curl -sS -m 6 "$HERMES_API/models" 2>/dev/null | grep -q hermes-agent && ok "hermes API alive ($HERMES_API)" || bad "hermes API down"
[ "$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:18789/ 2>/dev/null)" = 200 ] && ok "openclaw UI :18789" || bad "openclaw UI not 200"
ss -ltn 2>/dev/null | grep -q ':18080' && ok "openshell gateway :18080" || bad "gateway :18080 down"
# 06-11 起納管 bridge 與 mail 元件(否則 boot 後「全綠」不代表 demo 主線可跑)
if [ -n "$CT_O" ] && docker exec "$CT_O" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200; then
  ok "openclaw 修復端點 :9099(bridge 委派鏈)"
else bad "fix endpoint :9099 down → boot-stack.sh 的 ensure_xagent 會拉起"; fi
docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^greenmail-demo$' && ok "greenmail-demo 容器(mail demo)" || warn "greenmail-demo 未跑(mail demo 需要;bash $MAIL_DIR/up.sh)"
ss -ltn 2>/dev/null | grep -q ':3587' && ok "SMTP shim :3587(mail demo)" || warn "SMTP shim :3587 down(mail demo 需要;boot-stack 會拉起)"
[ "$(curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:3690/health 2>/dev/null)" = 200 ] && ok "mock Jira :3690(修不了→治理 egress 升級)" || warn "mock Jira :3690 down(Jira 升級 demo 需要;boot-stack 會拉起)"
[ "$(curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/ 2>/dev/null)" = 200 ] && ok "Agent Dashboard :8899(web 即時狀態盤)" || warn "Agent Dashboard :8899 down(boot-stack 會拉起)"
echo "  ﹒bus: inbox=$(ls "$BUS/inbox" 2>/dev/null|wc -l) outbox=$(ls "$BUS/outbox" 2>/dev/null|wc -l) xfer-leftovers=$(ls -d "$BUS"/skill-xfer-* 2>/dev/null|wc -l)"
echo "  ﹒scripts=$(ls "$(dirname "$0")"/*.sh|wc -l) snapshots=$(nemoclaw hermes-demo snapshot list 2>/dev/null|grep -cE '^\s+v[0-9]')"
