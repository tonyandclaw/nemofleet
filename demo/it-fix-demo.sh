#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# it-fix-demo.sh — Phase B:OpenClaw 當 IT operator,實作「找 bug → 修 → 驗證」。
# 流程:host 放一個有 bug 的腳本進 OpenClaw 沙箱(chown 998)→ nsenter 進 gateway netns 用 `openclaw agent`
#        叫 OpenClaw 用 read/write 工具修好 → host 端實際跑它驗證輸出。
# 用法:it-fix-demo.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
:
[ -n "$CT_O" ] || { echo "[it-fix] openclaw 容器未找到" >&2; exit 4; }
WD=/sandbox/.openclaw/workspace/it-task
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 1) 故意有 bug 的腳本(可切換場景:BUG=fw|subnet|bandwidth|dhcp,預設 fw;見 lib.sh)
#    drift 是多檔場景、僅 bridge 路徑支援,單檔流程不適用 → 導引過去
[ "${BUG:-fw}" = drift ] && { echo "[it-fix] drift 是多檔場景,走 bridge 路徑:bash tests/bridge-regress.sh drift(或 Telegram 委派,見 demo_telegram.md 2-b)" >&2; exit 2; }
bug_scenario "${BUG:-fw}" || exit 2
bug_emit "${BUG:-fw}" > "$TMP/$BUG_FILE"
docker exec "$CT_O" sh -lc "mkdir -p $WD"
docker cp "$TMP/$BUG_FILE" "$CT_O:$WD/$BUG_FILE"
docker exec -u 0 "$CT_O" sh -lc "chown -R 998:998 $WD && chmod -R a+rX $WD"   # 必須 chown 998
echo "[it-fix] 場景=${BUG:-fw};已放入有 bug 的 $WD/$BUG_FILE(目前輸出:$(docker exec "$CT_O" sh -lc "python3 $WD/$BUG_FILE" 2>&1) ← 應為 $BUG_MARKER)"

# 2) 叫 OpenClaw(管 ASUS 網路產品的 IT operator)修 bug
GW=$(docker exec "$CT_O" sh -lc 'pgrep -f openclaw-gateway | head -1')
[ -z "$GW" ] && { echo "[it-fix] openclaw-gateway 未跑" >&2; exit 4; }
MSG="你是管理 ASUS 網路產品的 IT operator。檔案 $WD/$BUG_FILE $BUG_OC 請用 read 工具讀檔、用 write 工具寫回修正版,只用 read/write 不要 exec。修好回報你改了什麼。"
echo "[it-fix] 觸發 OpenClaw 修 bug(openclaw agent via nsenter)..."
docker exec -e HOME=/sandbox "$CT_O" nsenter -t "$GW" -n sh -lc \
  "openclaw agent --agent main --session-id itfix-$(date +%s) -m \"$MSG\" --thinking low --timeout 240" \
  2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -avE 'staging bundled|failed to stage|Config warnings|\[plugins\]|npm error' | tail -4

# 3) host 驗證:實際跑修正後的腳本
OUT=$(docker exec "$CT_O" sh -lc "python3 $WD/$BUG_FILE" 2>&1)
echo "[it-fix] 修正後輸出:$OUT"
if echo "$OUT" | grep -q "$BUG_MARKER"; then echo "[it-fix] ✅ PASS — OpenClaw 修好了 bug($BUG_MARKER)"; exit 0
else echo "[it-fix] ❌ FAIL — 仍非 $BUG_MARKER($OUT)"; exit 1; fi
