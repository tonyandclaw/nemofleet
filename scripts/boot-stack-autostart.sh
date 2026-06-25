#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# boot-stack-autostart.sh — 開機自動把 NemoClaw 整個 stack 拉起(cron @reboot 用)。
# 重開機後 gateway 不會自己起,sandbox 抓不到政策會 crash-loop → 全離線;此腳本補上。
# 設計重點(對應實測坑):
#   - 無登入環境:自帶 PATH(~/.local/bin 的 nemoclaw + nvm node)。
#   - 等 docker daemon 就緒才動。
#   - 避開重開機後 ~150s 的 sandbox 自癒視窗(太早跑 boot-stack step1 會失敗)。
#   - boot-stack 失敗自動重試(實測首跑常在 step1 timing 失敗,需重跑一次)。
export PATH="$HOME/.local/bin:$NEMOFLEET_NODE_BIN:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="${HOME:-$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)}"
DIR=$NEMOFLEET_ROOT
LOG=/tmp/boot-stack-autostart.log
exec >>"$LOG" 2>&1
echo "==== autostart $(date '+%F %T') uptime=$(awk '{print int($1)}' /proc/uptime)s ===="

# 1) 等 docker 就緒(最多 ~90s)
for _ in $(seq 1 45); do docker info >/dev/null 2>&1 && break; sleep 2; done
docker info >/dev/null 2>&1 || { echo "docker 未就緒,放棄(交給手動/下次)"; exit 1; }

# 2) 避開 <~150s 自癒視窗
up=$(awk '{print int($1)}' /proc/uptime)
[ "$up" -lt 150 ] && sleep $((150 - up))

# 3) 跑 boot-stack,失敗重試三次
for attempt in 1 2 3; do
  echo "---- boot-stack attempt $attempt $(date '+%T') ----"
  if bash "$DIR/scripts/boot-stack.sh"; then
    echo "boot-stack OK (attempt $attempt) $(date '+%T')"; exit 0
  fi
  echo "attempt $attempt 失敗,20s 後重試"; sleep 20
done
echo "boot-stack 三次仍失敗;請手動檢查 /tmp/boot-stack.*.log"; exit 1
