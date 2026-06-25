#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# openclaw-cp-task.sh — bridge the bus to OpenClaw (no native inbound API; :9099 fix endpoint 為 scoped 例外,見 $BRIDGE_DIR/).
# host -> sandbox delivery of a task, and sandbox -> host retrieval of the result.
# OpenClaw consumes the task via the 'bus-worker' skill; 'run' triggers it programmatically (no UI needed).
# Usage:
#   openclaw-cp-task.sh put "<task text>"     # deliver a task into the OpenClaw sandbox (chown 998)
#   openclaw-cp-task.sh run                    # 觸發處理:nsenter 進 gateway netns 跑 openclaw agent(免 UI)
#   openclaw-cp-task.sh get                    # pull the result back to $BUS_DIR/outbox (if OpenClaw wrote one)
#   openclaw-cp-task.sh all "<task text>"      # put → run → get 一條龍(全自動)
set -euo pipefail
:
WS=$OCWS
BUS=$BUS_DIR
mkdir -p "$BUS/outbox"
CMD="${1:?put|get}"

case "$CMD" in
  put)
    MSG="${2:?task text required}"
    TMP=$(mktemp)
    printf '# bus task (from host)\n# 處理完請把回覆寫到 %s/bus-result.md\n\n%s\n' "$WS" "$MSG" > "$TMP"
    docker cp "$TMP" "$CT_O:$WS/bus-task.md"; rm -f "$TMP"
    # 關鍵:docker cp 進來的檔是 root/node 擁有、agent(uid 998)讀不到 → chown + 可讀,否則 turn 會 EACCES→退而用 exec→撞 elevated gate→繞圈
    docker exec -u 0 "$CT_O" sh -lc "chown 998:998 $WS/bus-task.md && chmod 644 $WS/bus-task.md" 2>/dev/null
    echo "[cp-task] delivered to OpenClaw: $WS/bus-task.md (chowned to sandbox uid 998)"
    echo "[cp-task] 下一步:觸發 bus-worker(UI 或 host: nsenter 進 gateway netns 跑 openclaw agent)。"
    ;;
  get)
    if docker exec "$CT_O" sh -lc "[ -f $WS/bus-result.md ]" 2>/dev/null; then
      OUT="$BUS/outbox/openclaw-$(date +%s).md"
      docker cp "$CT_O:$WS/bus-result.md" "$OUT"
      echo "[cp-task] result pulled -> $OUT"; sed 's/^/   /' "$OUT" | head
    else
      echo "[cp-task] no bus-result.md yet (OpenClaw 尚未處理或仍在跑)"
    fi
    ;;
  run)
    # 觸發 OpenClaw 處理 bus-task.md(程式化,免 UI):進 gateway netns 跑 openclaw agent。
    # 關鍵:docker exec 預設在外層 netns 連不到 gateway(ws 1006);須 nsenter -t <gw-pid> -n。
    GW=$(docker exec "$CT_O" sh -lc 'pgrep -f openclaw-gateway | head -1')
    [ -z "$GW" ] && { echo "[cp-task] openclaw-gateway 未在跑" >&2; exit 4; }
    MSG='讀取 /sandbox/.openclaw/workspace/bus-task.md(用 read 工具、絕對路徑),依內容完成,然後用 write 工具把結果寫入 /sandbox/.openclaw/workspace/bus-result.md(覆蓋)。只用 read/write 檔案工具,不要用 exec/shell。完成後回報一行。'
    docker exec -e HOME=/sandbox "$CT_O" nsenter -t "$GW" -n sh -lc "openclaw agent --agent main --session-id bus-$(date +%s) -m \"$MSG\" --thinking low --timeout 240" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -avE '^\s*$|staging bundled|failed to stage|Config warnings|plugin' | tail -5
    ;;
  all)
    "$0" put "${2:?task text required}"; echo "--- 觸發 ---"; "$0" run; echo "--- 取回 ---"; "$0" get ;;
  *) echo "usage: $0 put \"<task>\" | run | get | all \"<task>\"" >&2; exit 2 ;;
esac
