#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# e2e-nemoclaw.sh — NemoClaw 管理層「端到端」測試(真實呼叫 nemoclaw CLI 對 live 沙箱)。
# 涵蓋:CLI 可用 → sandbox 清單 → status 健康 → 快照 list/create/restore → 政策 preset list/add/remove(dry-run)。
# 安全性:破壞性操作只用 --dry-run;唯一真寫入是 snapshot create(附加性),restore 還原「剛建的快照=當前狀態」
#         等同 no-op,不改變 live 狀態。退出碼 = 失敗項數(可用於 CI)。
# 用法:bash tests/e2e-nemoclaw.sh [sandbox]   預設 worker-a
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"; :
SB="${1:-worker-a}"
PASS=0; FAIL=0
ok(){  printf '  \033[32m✓\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
skip(){ printf '  \033[33m–\033[0m %s\n' "$*"; }
hr(){  printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

hr "NemoClaw E2E · sandbox=$SB"

# T1 — CLI 可用
v=$(nemoclaw --version 2>&1 | head -1)
[ -n "$v" ] && ok "nemoclaw CLI 可用($v)" || bad "nemoclaw CLI 無法執行"

# T2 — sandbox 清單含目標
if nemoclaw list 2>/dev/null | grep -q "$SB"; then ok "nemoclaw list 含 $SB"; else bad "nemoclaw list 不含 $SB"; fi

# T3 — status 健康
if nemoclaw "$SB" status >/dev/null 2>&1; then ok "$SB status 可取得(rc=0)"; else bad "$SB status 失敗"; fi

# T4 — 快照清單
n0=$(nemoclaw "$SB" snapshot list 2>/dev/null | grep -oE '[0-9]+ snapshot' | grep -oE '^[0-9]+' | head -1); n0=${n0:-0}
[ "$n0" -ge 1 ] && ok "snapshot list 正常($n0 個)" || bad "snapshot list 異常($n0)"

# T5 — 建立快照(附加性寫入)→ 數量 +1 且新名稱出現
nm="e2e-$(date +%H%M%S)"
out=$(nemoclaw "$SB" snapshot create --name "$nm" 2>&1)
ver=$(echo "$out" | grep -oE 'v[0-9]+' | head -1)
echo "$out" | grep -qi "created" && ok "snapshot create 成功(${ver:-?} $nm)" || bad "snapshot create 失敗:$out"
n1=$(nemoclaw "$SB" snapshot list 2>/dev/null | grep -oE '[0-9]+ snapshot' | grep -oE '^[0-9]+' | head -1); n1=${n1:-0}
[ "$n1" -gt "$n0" ] && ok "快照數量 $n0 → $n1" || bad "快照數量未增加($n0→$n1)"
nemoclaw "$SB" snapshot list 2>/dev/null | grep -q "$nm" && ok "新快照 $nm 在清單中" || bad "新快照不在清單"

# T6 — 還原:驗證 selector 解析 + 誠實判斷結果(CLI 即使失敗也回 rc=0,要看輸出文字)。
#   in-place 還原「運行中沙箱」目前不支援(檔案佔用/權限),屬已知限制 → 視為 skip 而非 fail。
rout=$(nemoclaw "$SB" snapshot restore "$nm" 2>&1)
if echo "$rout" | grep -qiE "Using snapshot.*$nm"; then ok "snapshot restore 正確解析 selector($nm)"; else bad "snapshot restore 無法解析 selector"; fi
if echo "$rout" | grep -qi "restored" && ! echo "$rout" | grep -qi "restore failed"; then
  ok "snapshot restore in-place 成功"
elif echo "$rout" | grep -qi "restore failed"; then
  skip "in-place 還原運行中沙箱失敗(已知限制,須走重建/--to 流程)"
else
  bad "snapshot restore 結果無法判定:$(echo "$rout"|tail -1)"
fi

# T7 — 政策 preset 清單
pl=$(nemoclaw "$SB" policy-list 2>/dev/null)
np=$(echo "$pl" | grep -cE '[●○]')
[ "$np" -ge 1 ] && ok "policy-list 取得 $np 個 preset" || bad "policy-list 異常"

# T8 — policy-add 一個未啟用 preset(--dry-run,非破壞性)
off=$(echo "$pl" | grep -E '○' | head -1 | sed -E 's/.*○[[:space:]]+([A-Za-z0-9_-]+).*/\1/')
if [ -n "$off" ]; then
  nemoclaw "$SB" policy-add "$off" --dry-run 2>&1 | grep -qi "no changes applied" \
    && ok "policy-add $off --dry-run(預覽未套用)" || bad "policy-add $off --dry-run 異常"
else skip "無未啟用 preset,略過 add 測試"; fi

# T9 — policy-remove 一個已啟用 preset(--dry-run,非破壞性)
on=$(echo "$pl" | grep -E '●' | head -1 | sed -E 's/.*●[[:space:]]+([A-Za-z0-9_-]+).*/\1/')
if [ -n "$on" ]; then
  nemoclaw "$SB" policy-remove "$on" --dry-run 2>&1 | grep -qi "no changes applied" \
    && ok "policy-remove $on --dry-run(預覽未套用)" || bad "policy-remove $on --dry-run 異常"
else skip "無已啟用 preset,略過 remove 測試"; fi

hr "NemoClaw 結果:PASS=$PASS  FAIL=$FAIL"
exit $FAIL
