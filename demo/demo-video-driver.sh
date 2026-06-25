#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# demo-video-driver.sh — 10 分鐘 demo 影片的「現場驅動」:分段印大字幕、跑該段指令、段尾暫停等旁白。
# 搭配腳本:nemoclaw-enterprise-deck/ASUS-NemoClaw-Competition-2026-10min-demo-script.md
# 全程不出現投影片;畫面=主終端機(本腳本輸出)+ log 視窗 + 手機鏡像。
#
# 模式:
#   DRIVER_MODE=phone  (預設) 手機段會暫停,提示你用 Telegram 發訊,發完按 Enter 繼續
#   DRIVER_MODE=auto          手機段改用 bridge-regress.sh 從終端走相同委派路徑(免手機)
# 節奏:段尾預設等你按 Enter(唸完旁白再繼續);設 AUTO_ADVANCE=<秒> 改為自動前進(無人值守錄製)。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
cd "$DIR"; :
MODE="${DRIVER_MODE:-phone}"
TOKEN=$(cat $BRIDGE_DIR/.bridge-token 2>/dev/null)
OCIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CT_O" 2>/dev/null)

C1=$'\033[1;36m'; C2=$'\033[1;33m'; CG=$'\033[1;32m'; CD=$'\033[1;35m'; R=$'\033[0m'
banner(){ printf '\n%s' "$C1"; printf '═%.0s' $(seq 1 78); printf '\n  %s\n' "$1"; printf '═%.0s' $(seq 1 78); printf '%s\n' "$R"; }
say(){ printf '  %s\n' "$*"; }
shot(){ printf '%s▶ 畫面:%s%s\n' "$C2" "$*" "$R"; }
proof(){ printf '%s📜 鐵證:%s%s\n' "$CG" "$*" "$R"; }
phone(){ printf '%s📱 手機發:%s%s\n' "$CD" "$*" "$R"; }
run(){ printf '%s$ %s%s\n' "$C2" "$*" "$R"; eval "$@"; }
pause(){ if [ -n "${AUTO_ADVANCE:-}" ]; then sleep "$AUTO_ADVANCE"; else printf '\n%s…唸完旁白按 Enter 進下一段%s ' "$C1" "$R"; read -r _; fi; }
hermes_api(){ # $1 prompt $2 maxtok  — 終端驅動 Hermes(auto 模式/無手機時用)
  python3 - "$1" "${2:-200}" <<'PY'
import json,sys,urllib.request
b=json.dumps({"model":"hermes-agent","stream":False,"max_tokens":int(sys.argv[2]),"messages":[{"role":"user","content":sys.argv[1]}]}).encode()
r=urllib.request.Request("http://127.0.0.1:8642/v1/chat/completions",data=b,headers={"Content-Type":"application/json"})
try: print(json.loads(urllib.request.urlopen(r,timeout=240).read())["choices"][0]["message"].get("content") or "(空)")
except Exception as e: print(f"(Hermes 呼叫失敗:{e})")
PY
}

[ -n "$CT_H" ] && [ -n "$CT_O" ] || { echo "容器未跑,先 bash scripts/boot-stack.sh" >&2; exit 1; }
clear
banner "10 分鐘 DEMO 影片驅動  ·  模式=$MODE  ·  Hermes=$CT_H  OpenClaw=$OCIP"
say "開錄前確認三視窗:① 本終端機 ② 治理 log ③ 端點 log;手機鏡像備用。"
say "建議另開 log 視窗:nemoclaw hermes-demo logs | grep --line-buffered -aE 'getUpdates|engine:opa|engine:l7|:9099|greenmail_mail|policy:jira'"
pause

# ── 0:00 開場 ───────────────────────────────────────────────
banner "0:00  開場:四個元件、一個畫面"
shot "nemoclaw list + healthcheck 全綠"
run "nemoclaw list 2>&1 | sed -n '1,14p'"
run "bash scripts/healthcheck.sh 2>&1 | sed -n '2,14p'"
proof "兩沙箱、:9099、greenmail、:3690 Jira 一排綠勾"
pause

# ── 0:40 NemoClaw ───────────────────────────────────────────
banner "0:40  NemoClaw:生命週期與復原"
shot "snapshot 清單 + boot-stack 一鍵復原(已全綠會秒回)"
run "nemoclaw hermes-demo snapshot list 2>&1 | sed -n '1,8p'"
run "bash scripts/boot-stack.sh 2>&1 | tail -8"
proof "具名快照存在;boot-stack 每步綠勾=代理可一鍵 recover"
pause

# ── 1:40 NemoClaw × NVIDIA 推理路由 ─────────────────────────
banner "1:40  NemoClaw × NVIDIA:推理路由(讓名字名副其實)"
shot "現況 inference + nvidia 治理 policy + 實打一通到 NVIDIA"
run "bash demo/nvidia-inference-demo.sh 2>&1"
proof "ALLOWED python3 -> integrate.api.nvidia.com [policy:nvidia opa] + POST /v1/chat/completions [policy:nvidia l7];NVIDIA 回 401=路徑通,等 key"
pause

# ── 2:30 OpenShell ──────────────────────────────────────────
banner "2:30  OpenShell:沙箱隔離 + OPA 安全策略"
shot "OPA log 樣式 + egress policy 條目"
run "nemoclaw my-assistant logs 2>/dev/null | grep -a 'engine:opa' | tail -4"
run "openshell policy get my-assistant --full 2>/dev/null | grep -E 'name:|host:' | head -16"
proof "ALLOWED/DENIED ... [policy:.. engine:opa];policy 逐條列出放行 host"
pause

# ── 2:40 正常主線:報修→自委派→修退化+待審開 Jira→結案 ──────────
banner "2:40  正常主線:Telegram 報修 → 自委派 → 修退化 + 待審開 Jira → 結案 ★"
TS0=$(docker exec "$CT_O" sh -c "curl -s -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/last" 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin).get("ts",""))' 2>/dev/null)
if [ "$MODE" = phone ]; then
  phone "我們 lab 那台 RT-AX89X 設定怪怪的:SSH 好像被打開了密碼登入,syslog 也收不到 log,請工程端比對核准基準處理,修好回報。"
  say "→ 切手機鏡像發出上句;Hermes 會回『已委派』。發完按 Enter,本腳本接著秀桌面鐵證。"
  pause
else
  shot "auto 模式:從終端走與 Hermes 完全相同的委派路徑(免手機)"
  run "bash tests/bridge-regress.sh drift 2>&1 | tail -10"
fi
sleep 2
proof "治理 log:ALLOWED POST $OCIP:9099/fix [policy:openclaw_bridge]"
run "nemoclaw hermes-demo logs 2>/dev/null | grep -a '$OCIP:9099' | tail -2"
proof "端點:[FIX DONE] drift  REGRESSIONS 5→0、3 處漂移列待審"
run "docker exec '$CT_O' sh -c 'grep \"FIX DONE\" /tmp/openclaw-fix-endpoint.log | tail -1'"
proof "OpenClaw 開 Jira 升級(待審 3 項)+ 開單也受治理 policy:jira"
run "docker exec '$CT_O' sh -c \"curl -s -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/jira\" | python3 -m json.tool 2>/dev/null | head -16"
run "nemoclaw my-assistant logs 2>/dev/null | grep -a 'policy:jira' | tail -1"
if [ "$MODE" = phone ]; then phone "修好了嗎?把修復前後、還有需要人工確認的項目回報給我。"; say "→ 手機追問,Hermes 回結案。"; fi
pause

# ── 4:30 CVE 掃描 ───────────────────────────────────────────
banner "4:30  OpenClaw 監控職責:機隊 CVE 掃描"
shot "對 5 台機隊逐台逐 CVE 分級;affected 自動開 Jira"
run "bash scripts/cve-scan.sh 2>&1"
proof "affected 2 / needs_review 1 / unknown_inventory_gap 12;開 Jira 受 policy:jira 治理"
pause

# ── 5:30 email 通道 ─────────────────────────────────────────
banner "5:30  換通道不換治理:email 也能報修"
shot "客戶寄信 → Hermes 回 Re: → greenmail_mail 治理 log"
run "bash $MAIL_DIR/send-customer-mail.sh '韌體更新檢查異常' '客戶的 AiMesh 路由器顯示已是最新韌體,但雲端有新版裝不到,請工程端處理。'"
say "…等 Hermes 收信生成回覆(約 ≤12s)…"; sleep 12
run "bash $MAIL_DIR/read-inbox.sh 1"
run "nemoclaw hermes-demo logs 2>/dev/null | grep -a greenmail_mail | tail -2"
proof "收件匣出現 Re: 回信;ALLOWED ... :3993 [policy:greenmail_mail]"
pause

# ── 6:30 自我進化 + 持久化 ──────────────────────────────────
banner "6:30  自我進化 + 持久化(NemoClaw 快照)"
if [ "$MODE" = phone ]; then
  phone "幫我建立一個可重用的「設定漂移結案通知」技能:固定整理已修復項、待審項、風險說明三段。"
  say "→ 手機發出;Hermes 產 SKILL.md。發完按 Enter 秀檔案。"; pause
else
  shot "auto:用 dispatch 讓 Hermes 產一個技能"
  run "bash scripts/dispatch.sh '建立一個可重用的「設定漂移結案通知」技能,含已修復項/待審項/風險說明三段,回覆檔案路徑。' 220 2>&1 | tail -6"
fi
run "docker exec '$CT_H' sh -c 'ls -t /sandbox/.hermes/skills/*/ | head -5'"
run "nemoclaw hermes-demo snapshot list 2>&1 | grep -aE 'Version|v[0-9]' | head -5"
proof "新 SKILL.md 出現;NemoClaw 快照讓它跨重建存活"
pause

# ── 7:20 攻擊對照 ───────────────────────────────────────────
banner "7:20  攻擊對照:同一套系統,越權就被擋"
shot "security-demo 逐條觸發:S8 端點 token / S1 外連 / S4 binary / S7 遮罩 / S2 寄件者"
run "bash demo/security-demo.sh 2>&1"
proof "403 / DENIED / [CREDENTIAL] / Unauthorized — 每條都有 log"
pause

# ── 9:00 治理全景 ───────────────────────────────────────────
banner "9:00  治理全景:正常與攻擊,同一面 log 牆"
# 近期 log 被輪詢的 ALLOWED(getUpdates/greenmail)洗版,先即時觸發攻擊探針製造新鮮 DENIED
shot "即時觸發攻擊探針(host 層外連 + binary 層 curl)→ 製造新鮮 DENIED"
NS9=$(docker exec -u 0 "$CT_H" sh -c 'pid=$(pgrep -f "^sleep infinity$"|head -1); [ -z "$pid" ] && exit 1; want=$(stat -Lc %i /proc/$pid/ns/net); for f in /var/run/netns/*; do [ "$(stat -Lc %i "$f" 2>/dev/null)" = "$want" ] && { basename "$f"; exit 0; }; done' 2>/dev/null)
if [ -n "$NS9" ]; then
  say "✕ 外連非白名單主機(host 層)→ 應 403:"
  docker exec -u 0 "$CT_H" ip netns exec "$NS9" python3 -c "
import socket
for h in ('example.com','dns.google'):
    try:
        s=socket.create_connection(('10.200.0.1',3128),5)
        s.sendall(('CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n\r\n'%(h,h)).encode())
        print('    '+h+' -> '+s.recv(60).split(b'\r\n')[0].decode())
    except Exception as e: print('    '+h+' ERR '+str(e))
" 2>&1
  say "✕ 未授權 binary(curl)連白名單主機(binary 層)→ 應 403:"
  docker exec -u 0 "$CT_H" ip netns exec "$NS9" sh -c 'curl -sS -m6 -x http://10.200.0.1:3128 -p https://host.openshell.internal:3993 2>&1 | head -1' | sed 's/^/    /'
  sleep 2
else
  say "(找不到 hermes netns;先 bash scripts/boot-stack.sh)"
fi
printf '\n  \033[1;32m── ✓ 該放的:ALLOWED(過濾輪詢雜訊,留有意義的路徑)──\033[0m\n'
say "[Hermes 前台/委派/通道]"
nemoclaw hermes-demo logs 2>/dev/null | grep -a ALLOWED | grep -aE 'openclaw_bridge|greenmail_mail|telegram engine:l7' | tail -3 | sed 's/^/    /'
say "[OpenClaw 升級 Jira / NVIDIA 推理]"
nemoclaw my-assistant logs 2>/dev/null | grep -a ALLOWED | grep -aE 'policy:jira|policy:nvidia' | tail -2 | sed 's/^/    /'
printf '  \033[1;31m── ✕ 該擋的:DENIED(剛觸發的攻擊)──\033[0m\n'
nemoclaw hermes-demo logs 2>/dev/null | grep -a DENIED | tail -4 | sed 's/^/    /'
proof "同一面牆:ALLOWED 標放行的 policy 名;DENIED 標 policy:-(host 無匹配)或 binary 不在白名單"
pause

# ── 9:40 收尾 ───────────────────────────────────────────────
banner "9:40  收尾:全綠定格"
run "bash scripts/healthcheck.sh 2>&1 | sed -n '2,14p'"
say "旁白收尾後停錄。"
echo
printf '%s✅ 驅動結束。%s\n' "$CG" "$R"
