#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-compliance-cron.sh — 定期合規流水線(排程用):
#   ① 從真機 EBG19P 唯讀同步設定 → node A 的 ebg19p-current.conf(ebg19p-monitor-sync.sh)
#   ② POST /monitor-scan:OpenClaw 巡檢,對「安全退化」經治理 egress(policy:jira)去重開 Jira
# 同步在 host 端(沙箱無 192.168.50.1 egress);開單在 OpenClaw 端(受治理)。日誌 /tmp/ebg19p-compliance.log。
# crontab 範例:*/15 * * * * /usr/bin/bash $NEMOFLEET_ROOT/scripts/ebg19p-compliance-cron.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
LOG="${EBG19P_CRON_LOG:-/tmp/ebg19p-compliance.log}"
ts(){ date '+%F %H:%M:%S %Z'; }
{
  echo "[$(ts)] === EBG19P 合規流水線 ==="
  bash "$DIR/scripts/ebg19p-monitor-sync.sh" 2>&1 | sed 's/^/  /' || echo "  [warn] 設定同步失敗(裝置不可達?)"
  bash "$DIR/scripts/ebg19p-asset-sync.sh"   2>&1 | sed 's/^/  /' || echo "  [warn] 資產同步失敗"
  bash "$DIR/scripts/ebg19p-syslog-sync.sh"  2>&1 | sed 's/^/  /' || echo "  [warn] syslog 同步失敗"
  bash "$DIR/scripts/ebg19p-traffic-sync.sh" 2>&1 | sed 's/^/  /' || echo "  [warn] 流量同步失敗"
  CTO="$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)"
  TOKEN="$(cat "$BRIDGE_DIR/.bridge-token" 2>/dev/null)"
  if [ -n "$CTO" ] && [ -n "$TOKEN" ]; then
    R="$(docker exec "$CTO" sh -c "curl -s -m15 -X POST -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/monitor-scan" 2>/dev/null)"
    echo "  monitor-scan → $(printf '%s' "$R" | python3 -c 'import json,sys;r=json.load(sys.stdin);print("alerts=%s opened=%s"%(r["alerts"],[t["ticket"] for t in r["tickets_opened"]]))' 2>/dev/null || printf '%.180s' "$R")"
  else
    echo "  [warn] node A 容器或 token 不存在,跳過 monitor-scan"
  fi
} >> "$LOG" 2>&1
