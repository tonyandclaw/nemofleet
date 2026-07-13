#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# eval.sh — 跑 eval/tasks.jsonl 評分→沉澱 lessons.json→記 LEDGER→算 r_task 技能成效;
# 最後自動把教訓刷進 Hermes + worker 常駐 SKILL.md。關掉自動沉澱:SEDIMENT=0 eval/eval.sh
set -uo pipefail
export PATH="${NEMOFLEET_NODE_BIN:-}:$PATH"
DIR=$NEMOFLEET_ROOT
# eval.py 呼叫 http://127.0.0.1:8642(team-lead 的 Hermes API),需要先有 host→sandbox 的 forward。
# 冪等:已經 forward 過也能安全重跑(openshell 自己認得,不會重複開)。
command -v openshell >/dev/null 2>&1 && openshell forward start --background 8642 team-lead >/dev/null 2>&1
python3 "$DIR/eval/eval.py" "$@"; rc=$?
# r_task:skills/skill-stats.json 已隨 skills/ 整包在開機時同步進 worker-c(boot-stack.sh),但那只在
# 重開機/重建時才會刷新。這裡額外立刻 docker cp 一次,讓這輪 eval 算出的最新成效不用等下次重開機
# 才在 worker-c 端看得到(worker-c 未部署/CT_WC 空 → 安靜略過,不是必要步驟)。
if [ -n "${CT_WC:-}" ] && [ -s "$DIR/skills/skill-stats.json" ]; then
  docker cp "$DIR/skills/skill-stats.json" "$CT_WC:/usr/local/share/nemofleet-skills/skill-stats.json" >/dev/null 2>&1 \
    && echo "r_task 技能成效已同步進 worker-c" || true
fi
if [ "${SEDIMENT:-1}" = "1" ]; then
  echo "---- 沉澱教訓進 Hermes + worker SKILL.md ----"
  "$DIR/scripts/lessons-to-skill.sh" both 2>&1 | grep -E '渲染|安裝' || true
fi
exit "$rc"
