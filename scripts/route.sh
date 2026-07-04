#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# route.sh — decide which agent HARNESS should handle a task.
# 單一決策來源 = lib.sh route_decide()(dispatch.sh 用同一個,避免兩套啟發式打架):
#   worker = IT operator(網管/診斷/bug 修復/部署 的實作)
#   Hermes   = 對人前台 + 自我進化(規劃/解釋/報告/產技能;預設)
# Prints the decision + the suggested command. Does NOT auto-run the expensive path.
# Usage: route.sh "<task>"
set -euo pipefail
DIR=$NEMOFLEET_ROOT
:
TASK="${1:?task required}"

AGENT=$(route_decide "$TASK")
if [ "$AGENT" = worker ]; then
  WHY="IT/網管/診斷/修復 字眼 → worker harness(IT operator,動手實作)"
  CMD="$DIR/scripts/dispatch.sh \"$TASK\"   # 全自動走 worker 腿(put→nsenter 觸發→取回);或 worker-cp-task.sh all \"$TASK\""
else
  WHY="規劃/解釋/報告/產技能 → Hermes harness(對人前台、HTTP API、自我進化;預設)"
  CMD="$DIR/scripts/dispatch.sh \"$TASK\" 256"
fi

echo "[route] task: $TASK"
echo "[route] → $AGENT  ($WHY)"
echo "[route] 建議執行:"
echo "    $CMD"
