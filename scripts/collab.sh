#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# collab.sh — 兩 harness「協作鏈」:Hermes 產/驗技能 → 自動同步 → OpenClaw 用該技能完成互動任務。
# 比 dispatch「二選一」更進一步:一個目標同時用到兩個 harness 的強項。
# Usage: collab.sh "<要 Hermes 產的技能描述>" "<要 OpenClaw 用該技能做的互動任務>"
# 注意:會跑 2 次 Azure agent turn(Hermes authoring + OpenClaw 互動),較花時間/成本。
set -euo pipefail
DIR=$NEMOFLEET_ROOT
:
SKILL_SPEC="${1:?需要:要 Hermes 產的技能描述}"
USE_TASK="${2:?需要:要 OpenClaw 用該技能做的互動任務}"

echo "[collab] 1/2 → Hermes 產技能並自動回流 OpenClaw"
"$DIR/scripts/dispatch.sh" --to hermes "$SKILL_SPEC（請建成可重用 skill 並回報路徑)" 256

echo "[collab] 2/2 → OpenClaw 用(剛同步來的)技能完成互動任務"
"$DIR/scripts/dispatch.sh" --to openclaw "$USE_TASK"
echo "[collab] done. (Hermes 產 → sync → OpenClaw 用 的協作鏈)"
