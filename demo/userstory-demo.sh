#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# userstory-demo.sh — 主題3「實用性」:一個完整 user story,跨 mail + telegram 展示整個系統服務真人。
# MAIL 版可端到端跑(客戶 email 報 bug → Hermes 接待回覆 → OpenClaw 修 → 客戶收結案信)。
# TELEGRAM 版為 runbook(需真手機),印在最後。
# 用法:bash userstory-demo.sh          # 跑 MAIL user story(數個 Azure turn)
set -uo pipefail
cd "$(dirname "$0")/.."
:
MAIL=$MAIL_DIR
CT="$CT_H"
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
step(){ printf '\n\033[1;33m▸ %s\033[0m\n' "$*"; }
say(){ printf '  %s\n' "$*"; }
[ -n "$CT" ] || { echo "hermes 容器未跑,先 bash scripts/boot-stack.sh" >&2; exit 1; }

echo "############ 主題 3:實用性 — 完整 user story(MAIL 版,端到端) ############"
say "劇情:客戶 Tony 用 email 回報 AiMesh 路由器『顯示已是最新韌體卻裝不到更新』→ Hermes(前台)接待並回覆"
say "      → 這是 IT bug,經委派鏈交 OpenClaw(ASUS 網路設備 IT 機隊,現一台 sample:監控+修復+修不了開 Jira 升級)實修(韌體版本比較→UPDATE_AVAILABLE)→ 客戶收到結案。"

# ── Step 1:客戶寄 bug 報告 ──────────────────────────────
hr "Step 1 · 客戶用 email 報問題(真人入口)"
base=$(docker logs greenmail-demo 2>&1 | grep -ac 'mail from:<hermes@demo.local>')
bash "$MAIL/send-customer-mail.sh" "客戶回報：路由器韌體更新檢查異常" "Hermes 你好，我是客戶 Tony。我的 ASUS AiMesh 路由器後台一直顯示「已是最新韌體」,但我知道雲端其實有新版,結果一直裝不到更新。麻煩工程端協助查修,謝謝。"
step "等 Hermes(前台)email 回覆(接待/確認)…"
for i in $(seq 40); do [ "$(docker logs greenmail-demo 2>&1 | grep -ac 'mail from:<hermes@demo.local>')" -gt "$base" ] && break; sleep 3; done
sleep 6   # 多等內容回覆完成(避免只抓到先送出的系統提示)
say "Hermes 給客戶的接待回覆:"; bash "$MAIL/read-inbox.sh" 1 | sed 's/^/    /'

# ── Step 2:委派 OpenClaw 實修(可驗收) ──────────────────
hr "Step 2 · 委派鏈:Hermes 指派 → OpenClaw(IT)實修 → Hermes 結案"
say "(主線:Hermes 已可自委派——經唯一 scoped bridge POST :9099/fix〔/32 + X-Bridge-Token〕,live 實測委派→修復完成 44 秒,見 demo_telegram.md A1;此 MAIL 腳本用 it-collab.sh 走確定性的腳本版,方便無人值守重現)"
bash demo/it-collab.sh "客戶回報 AiMesh 路由器韌體檢查顯示『已是最新』卻裝不到更新,請修正。" 2>&1 | sed 's/^/    /'
say "(若 OpenClaw 修不了 / 需人工核准,會自動開 Jira 升級工程師——人在迴路;CVE 監控同理,見 scripts/cve-scan.sh)"

# ── Step 3:客戶收到結案(治理佐證) ─────────────────────
hr "Step 3 · 系統運作全程受治理(可稽核)"
say "本 story 期間的治理足跡(email 收發 + inference,全 ALLOWED + 受 policy):"
docker logs --since 4m "$CT" 2>&1 | grep -aE 'greenmail_mail|ALLOWED.*engine:opa' | grep -aiv getUpdates | tail -3 | sed 's/^/    /'

echo
echo "############ TELEGRAM 版 user story(runbook,需真手機) ############"
cat <<'TG'
  劇情:經理用手機 Telegram 對 Hermes 下達工作 → 規劃 + 觸發 IT 修復 + 跨通道回報。
  B0  (彩排)demo 前發一句「暖機」;桌面開 nemoclaw hermes-demo logs | grep getUpdates
  B1  手機發:「幫我規劃下週的客戶進度報告,列出要追蹤的項目」
        → Hermes(前台)回結構化規劃;桌面 log 同步 ALLOWED getUpdates(token 遮罩)
  B2  手機發:「RT-AX89X 設定被改過,SSH 密碼登入被打開、遠端 logging 被關,請比對核准基準處理」
        → Hermes 確認+自委派(經 scoped bridge POST /fix)回「已接手修復」;桌面佐證
          nemoclaw hermes-demo logs | grep 9099 → ALLOWED POST .../9099/fix [policy:openclaw_bridge engine:opa]
        → OpenClaw 修回 5 處安全退化(REGRESSIONS=0)、3 處漂移列待審+自動開 Jira 升級工程師
          (逐條腳本見 demo_telegram.md A1;一鍵回歸 bash tests/bridge-regress.sh drift)
  B3  (可選)跨通道:bash demo/control-demo.sh --live
        → email 進來、Hermes 同時推 Telegram(你手機收到通知)
  治理講點:全程 api.telegram.org 受 OpenShell L7 policy 治理、token 遮成 [CREDENTIAL]、
            新用戶需 hermes pairing approve(白名單)。同一套治理,換通道不換模型。
TG
