#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# fleet-compliance-cron.sh — 全機隊定期合規流水線(排程用):
#   ① 從各真機唯讀同步設定/狀態 → node A 工作區(EBG19P 4 項 + RT-AX89X 設定)
#   ② POST /monitor-scan:OpenClaw 巡檢,對「安全退化」經治理 egress(policy:jira)去重開 Jira
# 同步在 host 端(沙箱無真機 egress);開單在 OpenClaw 端(受治理)。裝置不可達會靜默跳過。
# 日誌 /tmp/fleet-compliance.log。crontab 範例:*/5 * * * * /usr/bin/bash $NEMOFLEET_ROOT/scripts/fleet-compliance-cron.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
LOG="${FLEET_CRON_LOG:-/tmp/fleet-compliance.log}"
ts(){ date '+%F %H:%M:%S %Z'; }
{
  echo "[$(ts)] === 機隊合規流水線 ==="
  bash "$DIR/scripts/ebg19p-monitor-sync.sh"   2>&1 | sed 's/^/  /' || echo "  [warn] EBG19P 設定同步失敗(裝置不可達?)"
  bash "$DIR/scripts/ebg19p-asset-sync.sh"     2>&1 | sed 's/^/  /' || echo "  [warn] EBG19P 資產同步失敗"
  bash "$DIR/scripts/ebg19p-syslog-sync.sh"    2>&1 | sed 's/^/  /' || echo "  [warn] EBG19P syslog 同步失敗"
  bash "$DIR/scripts/ebg19p-traffic-sync.sh"   2>&1 | sed 's/^/  /' || echo "  [warn] EBG19P 流量同步失敗"
  bash "$DIR/scripts/ebg19p-crypto-sync.sh"   2>&1 | sed 's/^/  /' || echo "  [warn] EBG19P 憑證掃描失敗"
  bash "$DIR/scripts/rt-ax89x-monitor-sync.sh" 2>&1 | sed 's/^/  /' || echo "  [warn] RT-AX89X 設定同步失敗(裝置不可達?)"
  # 註:OpenClaw B 的 SBOM/SAST/CWE 已改由 B 自己(endpoint 在容器內經治理 egress)自主抓上游 repo,
  #     不再由 host 注入。source-sbom-sync.sh / source-sast-sync.sh 僅保留為手動 fallback(容器無 egress 時)。
  CTO="$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)"
  TOKEN="$(cat "$BRIDGE_DIR/.bridge-token" 2>/dev/null)"
  if [ -n "$CTO" ] && [ -n "$TOKEN" ]; then
    R="$(docker exec "$CTO" sh -c "curl -s -m15 -X POST -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/monitor-scan" 2>/dev/null)"
    echo "  monitor-scan → $(printf '%s' "$R" | python3 -c 'import json,sys;r=json.load(sys.stdin);print("alerts=%s opened=%s"%(r["alerts"],[t["ticket"] for t in r["tickets_opened"]]))' 2>/dev/null || printf '%.180s' "$R")"
    LA="$(docker exec "$CTO" sh -c "curl -s -m20 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/log-analysis" 2>/dev/null)"
    echo "  log-analysis → $(printf '%s' "$LA" | python3 -c 'import json,sys;r=json.load(sys.stdin);print("findings=%s fusion=%s jira=%s"%(len(r.get("findings",[])),len(r.get("fusion",[])),r.get("jira_opened",[])))' 2>/dev/null || printf '%.120s' "$LA")"
  else
    echo "  [warn] node A 容器或 token 不存在,跳過 monitor-scan"
  fi
} >> "$LOG" 2>&1
