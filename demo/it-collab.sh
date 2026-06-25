#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# it-collab.sh — Phase E:端到端「人 → Hermes 前台規劃/指派 → OpenClaw IT 實作 → Hermes 回報」。
# 情境:OpenClaw = 管理 ASUS 網路產品的 IT operator。用可驗證的真實網路 bug 當 IT 動作。
# 可切換場景(lib.sh bug_scenario):BUG=fw|subnet|bandwidth|dhcp(預設 fw)。
#   fw=韌體誤報已最新 / subnet=/26 可用 IP -2 / bandwidth=Mbps 漏除8 / dhcp=位址池 off-by-one。
# 3 個 Azure turn(都 bounded)。撞 429 就稍後重試(30 分 cadence 會讓速率恢復)。
# 用法:it-collab.sh ["<人類需求字串>"]   或   BUG=subnet it-collab.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
:
[ -n "$CT_O" ] && [ -n "$CT_H" ] || { echo "[it-collab] 容器未找到" >&2; exit 4; }
WD=/sandbox/.openclaw/workspace/it-task
hermes(){ # $1=prompt $2=maxtok  -> 印出 content
  python3 - "$1" "${2:-80}" <<'PY'
import json,sys,urllib.request
b=json.dumps({"model":"hermes-agent","stream":False,"max_tokens":int(sys.argv[2]),
  "messages":[{"role":"user","content":sys.argv[1]}]}).encode()
r=urllib.request.Request("http://127.0.0.1:8642/v1/chat/completions",data=b,headers={"Content-Type":"application/json"})
try:
  d=json.loads(urllib.request.urlopen(r,timeout=240).read()); print(d["choices"][0]["message"].get("content") or "(空)")
except Exception as e: print(f"(Hermes 呼叫失敗:{e})")
PY
}

[ "${BUG:-fw}" = drift ] && { echo "[it-collab] drift 是多檔場景,走 bridge 路徑:bash tests/bridge-regress.sh drift(或 Telegram 委派,見 demo_telegram.md 2-b)" >&2; exit 2; }
bug_scenario "${BUG:-fw}" || exit 2
REQ="${1:-$BUG_REQ}"
echo "== 人類需求(場景:${BUG:-fw}) =="; echo "  $REQ"

# 1) 放可驗證的 bug(由 lib.sh bug_emit 產出該場景的有 bug 腳本)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
bug_emit "${BUG:-fw}" > "$TMP/$BUG_FILE"
docker exec "$CT_O" sh -lc "mkdir -p $WD"; docker cp "$TMP/$BUG_FILE" "$CT_O:$WD/$BUG_FILE"
docker exec -u 0 "$CT_O" sh -lc "chown -R 998:998 $WD"
echo "== 現況(bug) =="; echo "  $(docker exec "$CT_O" sh -lc "python3 $WD/$BUG_FILE")  ← 錯誤輸出(應為 $BUG_MARKER)"

# 2) Hermes 前台:確認問題 + 指派一句指令給 OpenClaw
echo "== ① Hermes(前台)規劃/指派 =="
hermes "$BUG_HCTX 你是 IT 前台,請用繁中兩句:(1)確認問題,(2)給管理 ASUS 網路產品的 IT operator 一句明確指令。簡短。" 130 | sed 's/^/  /'

# 3) OpenClaw(IT operator)實作修復
echo "== ② OpenClaw(IT operator)實作修復 =="
GW=$(docker exec "$CT_O" sh -lc 'pgrep -f openclaw-gateway | head -1')
MSG="你是管理 ASUS 網路產品的 IT operator。$WD/$BUG_FILE $BUG_OC 請用 read 工具讀檔、用 write 工具寫回修正版,只用 read/write 不要 exec。修好回報你改了什麼。"
docker exec -e HOME=/sandbox "$CT_O" nsenter -t "$GW" -n sh -lc \
  "openclaw agent --agent main --session-id collab-$(date +%s) -m \"$MSG\" --thinking low --timeout 240" \
  2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -avE 'staging bundled|failed to stage|Config warnings|\[plugins\]|npm error' | tail -3 | sed 's/^/  /'
OUT=$(docker exec "$CT_O" sh -lc "python3 $WD/$BUG_FILE" 2>&1)
echo "  [驗證] $OUT"
echo "$OUT" | grep -q "$BUG_MARKER" && VERDICT="已修復,驗證輸出正確($OUT)" || VERDICT="仍未修復($OUT)"

# 4) Hermes 前台:對人回報
echo "== ③ Hermes(前台)對人回報 =="
hermes "IT operator 回報:$BUG_HCTX 結果 $VERDICT。請用繁中一句、對客戶口吻回報結案。" 110 | sed 's/^/  /'

echo "$OUT" | grep -q "$BUG_MARKER" && { echo "[it-collab] ✅ 端到端 PASS"; exit 0; } || { echo "[it-collab] ❌ FAIL"; exit 1; }
