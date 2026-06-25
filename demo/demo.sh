#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# demo.sh — one-shot demo runbook for the OpenClaw × Hermes combined setup.
# Safe + cost-light: runs verifiable/cheap steps live; prints expensive ones as guided commands.
# Usage: bash demo.sh
set -uo pipefail
export PATH="$NEMOFLEET_NODE_BIN:$PATH"
DIR=$NEMOFLEET_ROOT
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

hr "0. 開場:真人經 Telegram 跟 harness agent(Hermes 前台)對話"
CT_HD=$(docker ps -qf name=hermes-demo)
if [ -n "$CT_HD" ]; then
  echo "已核准的 Telegram 用戶:"
  docker exec -e HOME=/sandbox -u 998 "$CT_HD" sh -lc 'hermes pairing list 2>&1' \
    | grep -A3 -i 'approved' | sed 's/^/   /'
  echo "bridge 在線檢查(近期 getUpdates 長輪詢;token 已遮成 [CREDENTIAL]):"
  nemoclaw hermes-demo logs 2>&1 | grep -i 'getUpdates' \
    | sed -E 's#bot[^/]*/#bot[CREDENTIAL]/#' | tail -2 | sed 's/^/   /' \
    || echo "   (暫無;demo 前先發一句暖機觸發輪詢)"
else
  echo "   (hermes-demo 容器未在跑)"
fi
cat <<'TGGUIDE'
  現場操作(投影手機 + 桌面 log 併排):
    1) demo 前先私下發一句「暖機」避開 Azure 首 token 延遲。
    2) 桌面開:  nemoclaw hermes-demo logs | grep --line-buffered getUpdates
    3) 手機在 bot 對話框發:「幫我規劃下週的客戶進度報告」
    4) 觀眾同時看到:手機收到 Hermes 回覆 + log 滾出 ALLOWED POST api.telegram.org/.../getUpdates
  講點:推理走 Azure Kimi-K2.5,但所有出站(含 Telegram bridge)都受 OpenShell egress policy 治理——治理是 code 不是 prompt;token 連 log 都遮罩;新用戶需 pairing 核准(白名單 user ID)。
TGGUIDE

hr "0c. Email 通道(另一個對人入口):客戶寄信 → Hermes 反應"
if docker ps --format '{{.Names}}' | grep -q '^greenmail-demo$'; then
  echo "GreenMail 本地信箱在線(IMAPS 3993 / SMTP STARTTLS shim 3587 / plain 3025):"
  ss -tln 2>/dev/null | grep -E ':(3993|3587|3025) ' | sed 's/^/   /'
  echo "egress 治理佐證(email 流量受自訂 greenmail_mail preset 逐條放行):"
  nemoclaw hermes-demo logs 2>&1 | grep -i 'greenmail_mail' \
    | sed -E 's#bot[^/]*/#bot[CREDENTIAL]/#' | tail -2 | sed 's/^/   /' \
    || echo "   (暫無;送一封信後會出現 ALLOWED ... [policy:greenmail_mail engine:opa])"
else
  echo "   (greenmail-demo 未在跑;先 bash scripts/boot-stack.sh 或 bash $MAIL_DIR/up.sh)"
fi
cat <<'MAILGUIDE'
  現場操作(投影 read-inbox 視窗;一次 Azure turn):
    1) bash $MAIL_DIR/send-customer-mail.sh "客戶詢問：API 整合時程"   # 當客戶寄信
    2) 等 ≤10s(Hermes 輪詢抓信 → Azure Kimi 生成 → SMTP 回信)
    3) bash $MAIL_DIR/read-inbox.sh                                  # 看 Hermes 的 Re: 回信
  講點:email 是 Hermes 原生 platform、另一個對人入口;同一套治理——收發信的 IMAPS/SMTP 流量
        在 OPA log 是 ALLOWED ... [policy:greenmail_mail engine:opa];全本地 GreenMail、零外部信箱帳號。
MAILGUIDE

hr "0b. 依 harness 能力分流(同一顆 Kimi,OpenClaw vs Hermes)"
echo "dispatch.sh 會用 route_decide 自動選 harness 並無人值守執行;這裡先看分流決策:"
"$DIR/scripts/route.sh" "幫我診斷服務 log 並修復連線 bug"
echo
"$DIR/scripts/route.sh" "幫我設計一個自動產報表的技能"
echo
echo "→ 實跑(各一次 Azure turn,見第 6 段指引):dispatch.sh \"<IT/修復類>\" 走 openclaw 腿、\"<規劃/產技能類>\" 走 hermes 腿。"

hr "1. 現況:兩個沙箱(同一顆 Azure Kimi,差在 harness 角色)"
nemoclaw list 2>&1 | sed -n '1,14p'
echo "  ⚠ 註:nemoclaw list 的 agent 欄是建立時記錄的 metadata,多次 policy-add/重啟後可能顯示 openclaw 且漏列 telegram —"
echo "     這是顯示層 stale,非真相。hermes-demo 實跑的是 hermes gateway(見下方 dashboard :8642 與第 2 段 /v1/models 回 hermes-agent);"
echo "     live policy 仍含 telegram(實機對話正常)。demo 點角色請以 dashboard port + /v1/models 為準。"
nemoclaw inference get 2>&1 | head -4

hr "2. Hermes 在線(OpenAI 相容 API :8642)"
curl -sS -m 8 http://127.0.0.1:8642/v1/models | head -c 120; echo

hr "3. 雙向知識共享(已同步技能 + provenance)"
:
docker exec "$CT_O" sh -lc 'for s in customer-progress-report daily-standup-notes; do
  echo "OpenClaw 收到: $s"; cat /sandbox/.openclaw/workspace/skills/$s/.synced-from 2>/dev/null | sed "s/^/   /"; done'

hr "4. 任務轉派(小任務,驗證 dispatch 管線;完整 authoring 見下)"
"$DIR/scripts/dispatch.sh" "In one short sentence, define a daily standup." 24

hr "5. 技能持久化(快照)"
nemoclaw hermes-demo snapshot list 2>&1 | sed -n '1,8p'

hr "下列為現場展示用、較花時間/Azure 的步驟(手動執行)"
cat <<'GUIDE'
  # (A0) dispatch 自動分流雙腿(無人值守):
  bash scripts/dispatch.sh "幫我診斷服務 log 並修復 bug"       # route→openclaw 腿(put→nsenter 觸發→取回 bus-result)
  bash scripts/dispatch.sh "設計一個自動產週報的技能"          # route→hermes 腿(API 解→新技能→sync 回 OpenClaw)
  # (A2) 跨 agent 真委派(Hermes 自委派 OpenClaw,經唯一 scoped openclaw_bridge 通道):
  #   Telegram/mail 發「請委派 OpenClaw 修韌體版本問題」→ Hermes 同一 turn 內 POST <OpenClaw容器IP>:9099/fix
  #     (帶 X-Bridge-Token,403 否則)→ 輪詢 GET /last → 對人結案回報(06-09 起 live 實測;委派→修復完成 44 秒,追問僅備援)
  #   佐證:nemoclaw hermes-demo logs | grep ':9099'   # ALLOWED POST http://<OpenClaw容器IP>:9099/fix [policy:openclaw_bridge engine:opa](IP 由 boot-stack 動態渲染,勿寫死)
  #   競賽主打場景 drift(真實 RT-AX89X 設定漂移;多檔場景,僅 bridge 路徑,it-collab/it-fix 單檔流程不支援):
  #     發「RT-AX89X 設定被改過,SSH 密碼登入被打開、遠端 logging 被關,請比對核准基準處理」
  #     → 修回 5 處安全退化(REGRESSIONS=0)、3 處漂移列待審、並自動開 Jira 工單升級工程師
  #   bash tests/bridge-regress.sh         # 委派鏈一鍵回歸(Hermes netns 經 L7 proxy 同路徑;預設 drift,可帶 fw|subnet|bandwidth|dhcp)
  #   逐條 Telegram 演法見 demo_telegram.md 主題2-b / 主題3
  # (A) 完整自我進化轉派:Hermes 真的新寫一個技能 → 自動分享給 OpenClaw
  bash scripts/dispatch.sh "Create a reusable skill named 'X' with sections ... and reply the path." 200
  # (A1) 協作鏈(一任務用兩 harness):Hermes 產技能 → 自動 sync → OpenClaw 用它
  bash scripts/collab.sh "一個叫 meeting-action-items 的技能:會議記錄→負責人|行動項|期限 表格" "用該技能整理:Alice 下週五交文件;Bob 修 bug"
  # (B) Hermes 現場產架構圖(展示自我進化技能):
  curl -s http://127.0.0.1:8642/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"model":"hermes-agent","stream":false,"messages":[{"role":"user","content":"用 architecture-diagram 技能畫 OpenClaw×Hermes 結合架構"}]}'
  # (C) 技能持久化還原驗證:
  #   刪掉某技能後  ->  nemoclaw hermes-demo snapshot restore <name>  -> 技能回來
GUIDE
echo
echo "詳見 design/architecture.md 與 DEMO_MATERIALS.md"
