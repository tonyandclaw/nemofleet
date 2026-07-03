#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# e2e-openshell.sh — OpenShell 強制層「端到端」測試(真實呼叫 openshell CLI 對 live gateway)。
# 涵蓋:CLI 可用 → policy get(版本/Loaded)→ active policy YAML 結構 → policy list 歷史
#        → policy prove 形式化證明(可執行 + 量化 + 決定性)→ policy set 冪等回灌。
# 安全性:唯一寫入是 policy set,且回灌的是「現行 active policy 本身」=冪等(Policy unchanged),不改變實際規則。
# 用法:bash tests/e2e-openshell.sh [sandbox]   預設 team-lead
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"; :
SB="${1:-team-lead}"
PASS=0; FAIL=0
ok(){  printf '  \033[32m✓\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
hr(){  printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
TMP=$(mktemp -d /tmp/e2e-osh.XXXX); trap 'rm -rf "$TMP"' EXIT
CRED="$TMP/cred.yaml"; printf 'version: 1\ncredentials: []\n' > "$CRED"

hr "OpenShell E2E · sandbox=$SB"

# T1 — CLI 可用
v=$(openshell --version 2>&1 | head -1)
[ -n "$v" ] && ok "openshell CLI 可用($v)" || bad "openshell CLI 無法執行"

# T2 — policy get(版本 + Loaded 狀態)
pg=$(openshell policy get "$SB" --full 2>/dev/null)
ver=$(echo "$pg" | grep -oE '^Version:[[:space:]]+[0-9]+' | grep -oE '[0-9]+' | head -1)
if [ -n "$ver" ] && echo "$pg" | grep -q "Loaded"; then ok "policy get 成功(version=$ver, Loaded)"; else bad "policy get 失敗"; fi

# T3 — 抽出 active policy YAML 並驗結構
PF="$TMP/pol.yaml"; echo "$pg" | awk 'f;/^---$/{f=1}' > "$PF"
if [ -s "$PF" ] && grep -qE "network_policies|filesystem_policy" "$PF"; then
  ok "active policy YAML 結構正常($(wc -l <"$PF") 行)"; else bad "policy YAML 抽取/結構異常"; fi

# T4 — policy list 版本歷史
hl=$(openshell policy list "$SB" 2>/dev/null)
nv=$(echo "$hl" | grep -cE '^[0-9]+[[:space:]]')
if echo "$hl" | grep -q "Loaded" && [ "$nv" -ge 1 ]; then ok "policy list 歷史可取得($nv 版)"; else bad "policy list 異常"; fi

# T5 — policy prove 形式化證明(可執行 + 量化)
pv=$(openshell policy prove --policy "$PF" --credentials "$CRED" --compact 2>&1)
gaps=$(echo "$pv" | grep -oE '[0-9]+ critical/high gaps' | grep -oE '^[0-9]+' | head -1)
if echo "$pv" | grep -qiE "gaps|PASS|FAIL"; then ok "policy prove 執行成功(critical/high gaps=${gaps:-0})"; else bad "policy prove 無法執行:$pv"; fi

# T6 — prove 決定性(同政策跑兩次,gap 數應一致)
g2=$(openshell policy prove --policy "$PF" --credentials "$CRED" --compact 2>&1 | grep -oE '[0-9]+ critical/high gaps' | grep -oE '^[0-9]+' | head -1)
[ "${gaps:-0}" = "${g2:-x}" ] && ok "policy prove 決定性一致(${gaps:-0} == ${g2:-?})" || bad "policy prove 不決定性(${gaps:-?} vs ${g2:-?})"

# T7 — policy set 冪等回灌(回灌現行政策本身 = Policy unchanged,安全)
si=$(openshell policy set --policy "$PF" "$SB" --wait --timeout 40 2>&1)
ver2=$(openshell policy get "$SB" --full 2>/dev/null | grep -oE '^Version:[[:space:]]+[0-9]+' | grep -oE '[0-9]+' | head -1)
if echo "$si" | grep -qiE "unchanged|loaded|applied|version" && [ "${ver2:-0}" -ge "${ver:-0}" ]; then
  ok "policy set 冪等回灌成功(version ${ver} → ${ver2})"; else bad "policy set 回灌異常:$si"; fi

hr "OpenShell 結果:PASS=$PASS  FAIL=$FAIL"
exit $FAIL
