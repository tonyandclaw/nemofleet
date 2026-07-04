#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# healthcheck.sh — one-shot health/hygiene check for the combined setup. Zero LLM cost.
# Usage: healthcheck.sh
set -uo pipefail
:
BUS=$BUS_DIR
ok(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m⚠\033[0m %s\n' "$*"; }

# 時鐘漂移檢查:系統 UTC vs 外部 HTTP Date(權威)。WSL2 在 Windows 睡眠後常漂移;
# 偏差大會弄錯迴圈停時、且會讓推理後端 TLS 憑證驗證失敗 → 推理掛掉。閾值 120s。
clock_check(){
  local hdr ext sys diff src
  for src in https://www.google.com https://www.cloudflare.com; do
    hdr=$(curl -sI -m 6 "$src" 2>/dev/null | grep -i '^date:' | head -1 | sed 's/^[Dd]ate:[ ]*//;s/\r$//')
    [ -n "$hdr" ] && break
  done
  if [ -z "$hdr" ]; then warn "時鐘漂移:拿不到外部時間,略過(網路?)"; return; fi
  ext=$(date -u -d "$hdr" '+%s' 2>/dev/null); sys=$(date -u '+%s')
  [ -z "$ext" ] && { warn "時鐘漂移:無法解析外部 Date,略過"; return; }
  diff=$(( sys - ext )); diff=${diff#-}
  if [ "$diff" -le 120 ]; then ok "時鐘同步(vs 外部偏差 ${diff}s)"
  else bad "時鐘漂移 ${diff}s(>120s)!會弄錯迴圈停時並可能讓推理後端 TLS 失敗 → 校時:sudo hwclock -s 或 wsl --shutdown"; fi
}

echo "== nemofleet healthcheck $(date '+%F %H:%M %Z') =="
clock_check
[ -n "$CT_LEAD" ] && ok "hermes container: $CT_LEAD" || bad "hermes container missing"
[ -n "$CT_WA" ] && ok "worker-a container: $CT_WA" || bad "worker-a container missing"
[ -n "$CT_WB" ] && ok "worker-b container: $CT_WB" || warn "worker-b container 未見(資安節點;非致命)"
[ -n "$CT_WC" ] && ok "worker-c container: $CT_WC" || warn "worker-c container 未見(治理節點;非致命)"
curl -sS -m 6 "$HERMES_API/models" 2>/dev/null | grep -q hermes-agent && ok "hermes API alive ($HERMES_API)" || bad "hermes API down"
[ "$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:18789/ 2>/dev/null)" = 200 ] && ok "worker UI :18789" || bad "worker UI not 200"
ss -ltn 2>/dev/null | grep -q ':18080' && ok "openshell gateway :18080" || bad "gateway :18080 down"
# 06-11 起納管 bridge 與 mail 元件(否則 boot 後「全綠」不代表 demo 主線可跑)
if [ -n "$CT_WA" ] && docker exec "$CT_WA" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200; then
  ok "worker 修復端點 :9099(bridge 委派鏈)"
else bad "fix endpoint :9099 down → boot-stack.sh 的 ensure_xagent 會拉起"; fi
if [ -n "$CT_WB" ]; then docker exec "$CT_WB" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200 \
  && ok "worker-b 端點 :9099(資安:CVE/nuclei/SBOM)" || warn "worker-b :9099 未回應(資安節點;boot 會拉起)"; fi
if [ -n "$CT_WC" ]; then docker exec "$CT_WC" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200 \
  && ok "worker-c 端點 :9099(治理:backup/firmware/rollback/review)" || warn "worker-c :9099 未回應(治理節點;boot 會拉起)"; fi
[ -n "${SMTP_HOST:-}" ] && [ -n "${SMTP_FROM:-}" ] && ok "SMTP relay 設定($SMTP_FROM via $SMTP_HOST:${SMTP_PORT:-587})" || warn "SMTP relay 未設定(.env SMTP_HOST/SMTP_FROM;通知寄不出)"
if [ -n "${JIRA_URL:-}" ]; then
  [ "$(curl -s -m4 -o /dev/null -w '%{http_code}' "$JIRA_URL" 2>/dev/null)" != 000 ] && ok "真實 Jira 可達($JIRA_URL)" || warn "Jira 不可達($JIRA_URL)"
else warn "JIRA_URL 未設定(.env;升級只在儀表板提醒)"; fi
[ "$(curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/ 2>/dev/null)" = 200 ] && ok "Agent Dashboard :8899(web 即時狀態盤)" || warn "Agent Dashboard :8899 down(boot-stack 會拉起)"
pgrep -f "scripts/teamlead-proactive.sh" >/dev/null 2>&1 && ok "team-lead 主動巡邏 loop(積極 agent)" || warn "team-lead 主動巡邏未跑(boot-stack 的 ensure_proactive 會拉起)"
echo "  ﹒bus: inbox=$(ls "$BUS/inbox" 2>/dev/null|wc -l) outbox=$(ls "$BUS/outbox" 2>/dev/null|wc -l) xfer-leftovers=$(ls -d "$BUS"/skill-xfer-* 2>/dev/null|wc -l)"
echo "  ﹒scripts=$(ls "$(dirname "$0")"/*.sh|wc -l) snapshots=$(nemoclaw team-lead snapshot list 2>/dev/null|grep -cE '^\s+v[0-9]')"
