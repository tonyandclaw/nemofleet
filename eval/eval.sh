#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# eval.sh — 跑 eval/tasks.jsonl 評分→沉澱 lessons.json→記 LEDGER;最後自動把教訓刷進 Hermes + OpenClaw 常駐 SKILL.md。
# 關掉自動沉澱:SEDIMENT=0 eval/eval.sh
export PATH="$NEMOFLEET_NODE_BIN:$PATH"
DIR=$NEMOFLEET_ROOT
python3 "$DIR/eval/eval.py" "$@"; rc=$?
if [ "${SEDIMENT:-1}" = "1" ]; then
  echo "---- 沉澱教訓進 Hermes + OpenClaw SKILL.md ----"
  "$DIR/scripts/lessons-to-skill.sh" both 2>&1 | grep -E '渲染|安裝' || true
fi
exit $rc
