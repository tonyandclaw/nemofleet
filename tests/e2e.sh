#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# e2e.sh — 一鍵跑 NemoClaw + OpenShell 端到端測試並彙總。退出碼 = 總失敗項數(CI 友善)。
# 用法:bash tests/e2e.sh [nemoclaw_sandbox] [openshell_sandbox]
#   預設:NemoClaw 測 my-assistant、OpenShell 測 hermes-demo。
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"
NSB="${1:-my-assistant}"; OSB="${2:-hermes-demo}"
rc=0
bash tests/e2e-nemoclaw.sh  "$NSB"; rc=$((rc + $?))
bash tests/e2e-openshell.sh "$OSB"; rc=$((rc + $?))
if [ "$rc" -eq 0 ]; then
  printf '\n\033[1;32m==== E2E 總結:全數通過 ✓ ====\033[0m\n'
else
  printf '\n\033[1;31m==== E2E 總結:%s 項失敗 ✗ ====\033[0m\n' "$rc"
fi
exit $rc
