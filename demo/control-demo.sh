#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# control-demo.sh — 主題2「Harness:透過 Telegram/mail 控制 Hermes 與 OpenClaw 的行為」。
# 四種控制面,每種標注由誰執行。06-09 起 Hermes 可經 bridge 自委派 OpenClaw
# (:9099 + scoped openclaw_bridge policy,見 $BRIDGE_DIR/);it-collab.sh 為 host 驅動的腳本版備援。
# 用法:
#   bash control-demo.sh           # 路由決策(即時) + 指引(委派/自我進化)
#   bash control-demo.sh --live    # 另加跨通道實測(email→Hermes 主動推 Telegram;1 Azure turn)
set -uo pipefail
cd "$(dirname "$0")/.."
:
MAIL=$MAIL_DIR
OCIP=$(docker inspect "$CT_O" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null); OCIP=${OCIP:-172.18.0.2}
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
ctl(){ printf '  \033[1;33m🎛 控制點:\033[0m %s\n' "$*"; }
runby(){ printf '  \033[1;35m▶ 由誰執行:\033[0m %s\n' "$*"; }
say(){ printf '  %s\n' "$*"; }

echo "############ 主題 2:Harness 控制 — 用訊息驅動 Hermes/OpenClaw 行為 ############"

# (a) 路由控制 ──────────────────────────────────────────────
hr "(a) 路由控制:同一個入口,訊息內容決定交給誰"
ctl "訊息含 IT/ops 字眼(修復/部署/重啟/診斷/bug…)→ OpenClaw(IT operator);規劃/技能/報告 → Hermes(前台)"
for t in "路由器韌體更新檢查壞了,請修好這個 bug" "幫我規劃下週的客戶進度報告" "重啟服務並看 log 診斷連線問題" "設計一個自動產週報的技能"; do
  printf '  「%s」\n      → \033[1m%s\033[0m\n' "$t" "$(route_decide "$t")"
done
runby "scripts/lib.sh route_decide()(dispatch.sh 用它自動分流)。訊息可來自 Telegram 或 mail。"

# (b) 委派控制 ──────────────────────────────────────────────
hr "(b) 委派控制:人報問題 → Hermes 指派 → OpenClaw 修 → Hermes 回報"
ctl "一句『路由器顯示已是最新韌體卻裝不到更新,請修』→ 觸發三段委派鏈(可驗收:STATUS UP_TO_DATE→UPDATE_AVAILABLE)"
say "實跑(主路徑,Hermes 自委派):Telegram/mail 發「請委派 OpenClaw 修韌體版本問題」"
say "  → Hermes POST http://$OCIP:9099/fix(it-delegate-openclaw 技能)→ OpenClaw 背景修 → Hermes 同一 turn 內輪詢 GET /last → 對人結案回報(實測委派→修復完成 44 秒)"
say "  佐證:nemoclaw hermes-demo logs | grep \"$OCIP:9099\"   # ALLOWED POST .../fix [policy:openclaw_bridge engine:opa]"
say "腳本版備援(host 一鍵):bash demo/it-collab.sh   (① Hermes 指派 ② OpenClaw nsenter+agent 修 ③ Hermes 結案;限單檔場景 fw|subnet|bandwidth|dhcp,drift 僅 bridge 路徑)"
runby "主路徑:Hermes 自委派,經唯一 scoped 跨 agent 通道 openclaw_bridge(僅放行 $OCIP:9099;POST /fix 與 GET /last 皆須 X-Bridge-Token,否則 403,token 在 $BRIDGE_DIR/.bridge-token、boot 時動態渲染進 SKILL;其餘互相隔離)。it-collab.sh 為中段 host 驅動的備援。"

# (c) 自我進化控制 ──────────────────────────────────────────
hr "(c) 自我進化控制:一句話讓 Hermes 長出新技能"
ctl "『建立一個 X 技能,含 Inputs/Steps/Output』→ Hermes 寫 SKILL.md → 自動 sync 給 OpenClaw"
say "實跑:bash scripts/dispatch.sh \"Create a reusable skill named '...' ...\" 200"
runby "Hermes 內建 skills toolset 寫檔;dispatch.sh 偵測新技能並 skill-sync 給 OpenClaw。"

# (d) 跨通道控制 ────────────────────────────────────────────
hr "(d) 跨通道控制:email 進來,要求 Hermes 同時用 Telegram 通知"
ctl "信件內文『請同時用 Telegram 通知我』→ Hermes 一個 turn 內既回 email 又主動推 Telegram"
if [ "${1:-}" = "--live" ]; then
  CT="$CT_H"
  [ -n "$CT" ] || { echo "  hermes 容器未跑"; exit 1; }
  sm0=$(docker logs "$CT" 2>&1 | grep -ac 'sendMessage')
  base=$(docker logs greenmail-demo 2>&1 | grep -ac 'mail from:<hermes@demo.local>')
  # 指示要明確(務必呼叫工具),否則 Hermes 可能只在回信『聲稱』送了卻沒真呼叫工具(LLM 非確定性)
  bash "$MAIL/send-mail-as.sh" "tony@demo.local" "請務必用工具發 Telegram" "Hermes，請務必實際呼叫你的 send_message 工具,發送一則 Telegram 訊息到 chat id 5488297243,內容為「你的郵件已處理完成」。不要只在回信說明,要真的呼叫工具發送。Email 也請回覆。" >/dev/null
  say "  已寄出,等 Hermes(同時推 Telegram + 回 email)…"
  for i in $(seq 40); do
    [ "$(docker logs "$CT" 2>&1 | grep -ac 'sendMessage')" -gt "$sm0" ] && break; sleep 3
  done
  if [ "$(docker logs "$CT" 2>&1 | grep -ac 'sendMessage')" -gt "$sm0" ]; then
    printf '  \033[1;32m✓ Hermes 真的呼叫 send_message 推了 Telegram(以 OCSF log 為準,你手機應收到):\033[0m\n'
    docker logs --since 3m "$CT" 2>&1 | grep -aE 'sendMessage' | tail -1 | sed 's/^/     /'
  else
    say "  ⚠ 此 turn 未偵測到 sendMessage。注意:Hermes 回信可能『聲稱』已通知卻沒真呼叫工具(LLM 非確定性)——"
    say "     一律以上面的 OCSF sendMessage log 為準,別信回信文字。指示講更白(務必呼叫工具)可提高可靠度。"
  fi
  for i in $(seq 20); do [ "$(docker logs greenmail-demo 2>&1 | grep -ac 'mail from:<hermes@demo.local>')" -gt "$base" ] && break; sleep 3; done
  say "  email 回覆:"; bash "$MAIL/read-inbox.sh" 1 | sed 's/^/     /'
else
  say "  實跑(1 Azure turn):bash demo/control-demo.sh --live"
fi
runby "Hermes 內建 send_message 工具(target=telegram:5488297243);email turn 內呼叫。出站 sendMessage 仍受 OpenShell L7 治理(policy:telegram,token 遮罩)。"

echo
echo "############ 控制面速查 ############"
cat <<'MAP'
  (a) 路由     訊息關鍵字 → OpenClaw(IT) / Hermes(前台)     | route_decide() ;訊息驅動
  (b) 委派     人→Hermes→OpenClaw→人;修得了實修回報,修不了/需人審→OpenClaw 開 Jira 升級工程師(人在迴路) | Hermes 自委派(POST :9099/fix,scoped openclaw_bridge);備援 it-collab.sh(host 驅動)
  (c) 自我進化 一句話 → 新 SKILL.md → sync OpenClaw           | dispatch.sh + skills toolset
  (d) 跨通道   email → Hermes 同時推 Telegram                 | send_message 工具;受 OpenShell L7 治理
MAP
