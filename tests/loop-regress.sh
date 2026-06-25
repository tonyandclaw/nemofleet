#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# loop-regress.sh — Phase 2 回歸守護:零成本確定性路徑逐項跑 + 已知坑監測,結果 append eval/ledgers/LOOP-LEDGER.md。
# 給 loop 守護階段每輪跑(零 Azure);bridge-regress drift(Azure 主鏈)每天另跑 1 次驗委派鏈。
# 抓 flaky:ledger 累積時間戳 + 各項 PASS/FAIL,看趨勢。連兩輪 fails>0 → 該還原 pre-loop 快照。
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"; :
TOKEN=$(cat $BRIDGE_DIR/.bridge-token 2>/dev/null)
LEDGER="$DIR/eval/ledgers/LOOP-LEDGER.md"
[ -f "$LEDGER" ] || printf '# LOOP-LEDGER — Phase 2 回歸守護紀錄(loop-regress.sh 每輪 append;一行一輪)\n\n' > "$LEDGER"
TS=$(date '+%F %H:%M'); res=""; fails=0
chk(){ if [ "$2" = "0" ]; then printf '  \033[32m✓\033[0m %-11s %s\n' "$1" "$3"; res="$res $1=OK"
       else printf '  \033[31m✗\033[0m %-11s %s\n' "$1" "$3"; res="$res $1=FAIL"; fails=$((fails+1)); fi; }
warn(){ printf '  \033[33m﹒\033[0m %-11s %s\n' "$1" "$2"; res="$res $1=$3"; }
jget(){ python3 -c "import json,sys;d=json.load(sys.stdin);print($1)" 2>/dev/null; }

echo "== loop-regress $TS(零成本守護)=="
[ -n "$CT_H" ] && [ -n "$CT_O" ]; rc=$?; chk containers $rc "hermes/openclaw 在跑"
CT_O2="$(docker ps --format '{{.Names}}' | grep -m1 openclaw-2 || true)"
[ -n "$CT_O2" ] && chk openclaw2 0 "第二台 OpenClaw 在跑(openclaw-2,UI :18790)" || warn openclaw2 "openclaw-2 不在(已 destroy?)" SKIP

H=$(docker exec "$CT_O" sh -c "curl -s -m6 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/health" 2>/dev/null)
{ echo "$H" | grep -q '"design": true' && echo "$H" | grep -q '"managed"' && echo "$H" | grep -q '"source": true'; }; rc=$?
chk health $rc "markers(design/source/managed=$(echo "$H" | jget 'd.get("managed")'))"

# 分區後:節點 A(zone A=1 rt-ax89x)+ 節點 B(zone B=2 openwrt+ebg19p)合計 3 台受管
nA=$(docker exec "$CT_O" sh -c "curl -s -m8 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/monitor" 2>/dev/null | jget 'd.get("managed_snapshots",0)')
if [ -n "$CT_O2" ]; then
  nB=$(docker exec "$CT_O2" sh -c "curl -s -m8 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/monitor" 2>/dev/null | jget 'd.get("managed_snapshots",0)')
  ntot=$(( ${nA:-0} + ${nB:-0} )); [ "$ntot" -ge 3 ]; rc=$?; chk monitor $rc "節點A=$nA + 節點B=$nB = $ntot 台受管"
else
  [ "${nA:-0}" -ge 1 ]; rc=$?; chk monitor $rc "單節點 managed=$nA(openclaw-2 不在)"
fi

# 分區後 affected 落在節點 B(openwrt 有 SBOM 在 zone B);兩節點合計應 2 affected
affA=$(docker exec "$CT_O" sh -c "curl -s -m12 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/cve" 2>/dev/null | jget 'd.get("counts",{}).get("affected",0)')
affB=0; [ -n "$CT_O2" ] && affB=$(docker exec "$CT_O2" sh -c "curl -s -m12 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/cve" 2>/dev/null | jget 'd.get("counts",{}).get("affected",0)')
afftot=$(( ${affA:-0} + ${affB:-0} )); [ "$afftot" = "2" ]; rc=$?
chk cve $rc "affected 合計=$afftot(節點A=$affA 節點B=$affB)"

# source(SBOM/SAST/設計文件)是資安節點(B)職責;對 B 檢查(B 不在退回 A)
SCT="${CT_O2:-$CT_O}"
S=$(docker exec "$SCT" sh -c "curl -s -m15 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/source-cve" 2>/dev/null)
sast=$(echo "$S" | jget 'len(d.get("sast_findings",[]))'); [ "${sast:-0}" -ge 2 ] 2>/dev/null; rc=$?
chk source $rc "sast=$sast(節點B 資安) patches_verified=$(echo "$S" | jget 'd.get("patches_verified")')"

timeout 40 bash demo/policy-prove-demo.sh >/dev/null 2>&1; rc=$?; chk prove $rc "policy prove 可執行"

# 已知坑監測(P2-2)
recent=$(docker logs --since 6m "$CT_H" 2>&1 | grep -ac getUpdates)
if [ "${recent:-0}" -gt 0 ]; then warn telegram "近6分 getUpdates×$recent(輪詢存活)" OK
else warn telegram "近6分無 getUpdates(留意 2h 靜默死,可 boot-stack 重拉)" WARN; fi
r429=$(docker logs --since 30m "$CT_H" 2>&1 | grep -aciE 'too many requests|rate.?limit|status[^0-9]{0,4}429|HTTP[^0-9]{0,5}429|429 (too|client|error)')  # 精確匹配 HTTP 429,不誤抓 socat PID(如 socat1(4295))
if [ "${r429:-0}" -gt 0 ]; then warn azure429 "近30分 429×$r429(冷卻一下)" WARN; else warn azure429 "近30分無 429" none; fi

echo "$TS |$res | fails=$fails" >> "$LEDGER"
echo; echo "→ ledger: eval/ledgers/LOOP-LEDGER.md  fails=$fails"
[ "$fails" -eq 0 ] && echo "✅ 守護全綠" || echo "⚠ 有 $fails 項 FAIL(連兩輪紅 → 還原 combine-pre-loop-0612)"
exit 0
