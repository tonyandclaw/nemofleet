#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# dispatch.sh — route a task to the right harness and run it unattended.
#   hermes  腿:打 Hermes OpenAI API,並自動偵測新技能 → sync 給 OpenClaw(轉派閉環)
#   openclaw腿:openclaw-cp-task.sh all(put〔chown〕→ nsenter 觸發 openclaw agent → get)
# Usage:
#   dispatch.sh "<task>" [max_tokens]            # 自動 route_decide 選 harness
#   dispatch.sh --to hermes|openclaw "<task>" [max_tokens]   # 強制指定
set -euo pipefail

DIR=$NEMOFLEET_ROOT
:

TARGET=""
if [ "${1:-}" = "--to" ]; then TARGET="${2:?--to needs hermes|openclaw}"; shift 2; fi
TASK="${1:?task required}"; MAXTOK="${2:-256}"
[ -z "$TARGET" ] && TARGET=$(route_decide "$TASK")
echo "[dispatch] route → $TARGET"

if [ "$TARGET" = "openclaw" ]; then
  # OpenClaw 腿(全自動):投遞→觸發→取回。IT/網管/診斷/bug 修復類任務。
  "$DIR/scripts/openclaw-cp-task.sh" all "$TASK"
  echo "[dispatch] done (openclaw)."
  exit 0
fi

# ── Hermes 腿:API 轉派 + 自我進化技能回流 ──
snap() { docker exec "$CT_H" sh -lc "find $HSKILLS -iname SKILL.md | sort"; }
echo "[dispatch] task -> hermes (the expert)"
BEFORE=$(snap)
"$DIR/scripts/relay.sh" hermes "$TASK" "$MAXTOK"        # 1 Azure call (bounded); reply also lands in $BUS_DIR/outbox
AFTER=$(snap)

# detect newly-authored skills (Hermes self-evolving) and share them with OpenClaw
NEWDIRS=$(comm -13 <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") | sed -E 's#.*/skills/[^/]+/([^/]+)/SKILL.md#\1#' | sort -u)
if [ -n "$NEWDIRS" ]; then
  echo "[dispatch] Hermes authored new skill(s): $NEWDIRS — sharing to OpenClaw"
  for s in $NEWDIRS; do "$DIR/scripts/skill-sync.sh" hermes2openclaw "$s" || true; done
else
  echo "[dispatch] no new skill authored this run (nothing to share)"
fi
echo "[dispatch] done (hermes)."
