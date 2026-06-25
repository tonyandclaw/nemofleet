#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# telegram-watchdog.sh — 偵測 Hermes Telegram 輪詢「靜默死亡」並自動復原(cron 用)。
# 判定:近 10 分鐘 Hermes 容器 log 內 getUpdates=0 → 視為死亡。
# 復原:重啟 Hermes 容器 + boot-stack 在 netns 內重建(實測唯一可靠路徑;簡單 recover 會 probe 失敗)。
# 防抖:復原後 30 分冷卻,避免狂重啟。健康時靜默快退(只一個 grep)。日誌 /tmp/telegram-watchdog.log。
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"
export PATH="$HOME/.local/bin:$NEMOFLEET_NODE_BIN:/usr/local/bin:/usr/bin:/bin:$PATH"
LOG="${TG_WD_LOG:-/tmp/telegram-watchdog.log}"
STAMP=/tmp/.telegram-watchdog-last
COOLDOWN=1800
ts(){ date '+%F %H:%M:%S'; }

CTH="$(docker ps --format '{{.Names}}' | grep -m1 hermes-demo)"
[ -n "$CTH" ] || exit 0   # 容器不在(可能 stack 沒起),交給 boot-stack autostart

N=$(docker logs --since 10m "$CTH" 2>&1 | grep -ac getUpdates)
[ "$N" -gt 0 ] && exit 0   # 健康 → 靜默退出

now=$(date +%s); last=$(cat "$STAMP" 2>/dev/null || echo 0)
if [ $(( now - last )) -lt "$COOLDOWN" ]; then
  echo "[$(ts)] Telegram 無輪詢,但在冷卻期($(( (now-last)/60 )) 分前剛復原),等待" >>"$LOG"; exit 0
fi
echo "[$(ts)] ⚠ Telegram 輪詢死亡(近10分 getUpdates=0)→ 自動復原" >>"$LOG"
echo "$now" > "$STAMP"
docker restart "$CTH" >>"$LOG" 2>&1 || echo "[$(ts)] hermes restart 失敗" >>"$LOG"
bash "$DIR/scripts/boot-stack.sh" >>"$LOG" 2>&1 || echo "[$(ts)] boot-stack 復原非零退出" >>"$LOG"
sleep 30
N2=$(docker logs --since 2m "$CTH" 2>&1 | grep -ac getUpdates)
echo "[$(ts)] 復原後 getUpdates(近2分)=$N2 $([ "$N2" -gt 0 ] && echo '✓ 已恢復' || echo '✗ 仍未恢復,下個冷卻週期再試')" >>"$LOG"
