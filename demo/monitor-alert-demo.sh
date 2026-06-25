#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# monitor-alert-demo.sh — 「凌晨兩點」主動告警 use case:發現不靠運氣、通知不等人(對應 PPTX 痛點①)。
#   ① 模擬設備半夜被改壞:植入 RT-AX89X 漂移現況(素材取自 bridge endpoint 的 drift 場景,單一真相來源)
#   ② OpenClaw /monitor 巡檢「自己發現」安全退化(現況 vs 已核准 baseline;確定性、零 Azure)
#   ③ 告警交給 Hermes 對人前台 → Hermes 主動推 Telegram 給網管(send_message 工具;1 Azure turn)
#   ④ 網管手機回「修」→ 接 demo_telegram A1 報修主線(Hermes 自委派 POST /fix → 修退化 → 結案)
# 用法:bash demo/monitor-alert-demo.sh             # 全程(含 Telegram 推播,1 Azure turn)
#       bash demo/monitor-alert-demo.sh --no-push   # 只跑 ①②(零 Azure,彩排/健檢用)
set -uo pipefail
DIR=$NEMOFLEET_ROOT
cd "$DIR"; :
TOKEN_FILE="$BRIDGE_DIR/.bridge-token"
[ -n "$CT_O" ] && [ -n "$CT_H" ] || { echo "[monitor-alert] 容器未跑,先 bash scripts/boot-stack.sh" >&2; exit 1; }
[ -s "$TOKEN_FILE" ] || { echo "[monitor-alert] 缺 token,先 bash scripts/boot-stack.sh" >&2; exit 1; }
TOKEN=$(cat "$TOKEN_FILE")
CHAT_ID=5488297243
WD=/sandbox/.openclaw/workspace/it-task
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

hr "① 模擬「凌晨兩點」:lab RT-AX89X 設定被改了(SSH 密碼登入被開、遠端 syslog 被關)"
# 漂移素材直接取自 bridge endpoint 的 drift 場景常數(與 /fix 用同一份,單一真相來源)
seed_conf() {  # $1 = python 變數名, $2 = 容器內目的檔
  python3 -c "
import importlib.util as u
spec = u.spec_from_file_location('ep', '$BRIDGE_DIR/openclaw-fix-endpoint.py')
m = u.module_from_spec(spec); spec.loader.exec_module(m)
import sys; sys.stdout.write(getattr(m, '$1'))" | docker exec -i -u 0 "$CT_O" sh -c "cat > $WD/$2"
}
docker exec -u 0 "$CT_O" sh -c "mkdir -p $WD"
seed_conf BASELINE_CONF rt-ax89x-baseline.conf
seed_conf DRIFTED_CONF  rt-ax89x-current.conf
docker exec -u 0 "$CT_O" sh -c "chown -R 998:998 $WD"
echo "  已植入漂移現況(模擬設備端變更;baseline 為已核准基準)"

hr "② OpenClaw 監控巡檢:自己發現,不靠人巡(確定性、零 Azure)"
MON=$(docker exec "$CT_O" sh -c "curl -s -m10 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/monitor")
[ -n "$MON" ] || { echo "[monitor-alert] /monitor 無回應" >&2; exit 1; }
MON_JSON="$MON" python3 <<'PY'
import json, os
r = json.loads(os.environ["MON_JSON"])
print(f"  巡檢時間 {r['ts']} | 機隊 {r['fleet_size']} 台 | 告警 {r['alerts']} 台")
for d in r["devices"]:
    print(f"  [{d['status']}] {d['asset']}")
    if d.get("regressions"):
        print("    安全退化(必須修):" + ", ".join(d["regressions"]))
    if d.get("pending_review"):
        print("    一般漂移(留人審):" + ", ".join(d["pending_review"]))
PY
echo "  佐證(端點 log):"
docker exec "$CT_O" sh -c 'grep -a "MONITOR ALERT" /tmp/openclaw-fix-endpoint.log | tail -1' | sed 's/^/    /'

if [ "${1:-}" = "--no-push" ]; then
  hr "(--no-push)跳過 Telegram 推播。全流程:③ Hermes 推手機告警 ④ 回「修」接 A1 主線"
  echo "  還原/接續:bash tests/bridge-regress.sh drift(走完修復鏈,現況回到已修狀態)"
  exit 0
fi

hr "③ 告警進值班信箱 → Hermes 對人前台 → 主動推 Telegram 給網管(不是人來問,是系統去敲人)"
# 入口走 email 通道(API turn 沒有 channel 工具;email 通道的 turn 才有 send_message,control-demo (d) 已實證)
SM0=$(docker logs "$CT_H" 2>&1 | grep -ac 'sendMessage')
ALERT_BODY="OpenClaw 機隊監控告警:lab 設備 RT-AX89X(lab-asus-rt-ax89x-01)巡檢發現 5 處安全退化 — SSH 密碼登入被打開、遠端 syslog(enabled/host/port/protocol)全被關閉,設備暴露中。Hermes,請務必實際呼叫你的 send_message 工具,發 Telegram 訊息到 chat id ${CHAT_ID},內容:「⚠️ 監控告警(02:00):RT-AX89X 偵測到 5 處安全退化 — SSH 密碼登入被開啟、遠端 syslog 被關閉。已凍結現狀待指示,回覆『修』即委派 OpenClaw 修復。」不要只在回信說明,要真的呼叫工具發送。"
bash "$MAIL_DIR/send-mail-as.sh" "tony@demo.local" "【OpenClaw 監控告警】RT-AX89X 5 處安全退化" "$ALERT_BODY" >/dev/null
echo "  告警信已投遞值班信箱,等 Hermes 收信並推播(email 輪詢 + 1 Azure turn)…"
SM1="$SM0"
for i in $(seq 40); do
  SM1=$(docker logs "$CT_H" 2>&1 | grep -ac 'sendMessage')
  [ "$SM1" -gt "$SM0" ] && break
  sleep 3
done
if [ "$SM1" -gt "$SM0" ]; then
  printf '  \033[1;32m✓ Hermes 真的呼叫 send_message 推了 Telegram(看手機;OCSF log 佐證):\033[0m\n'
  docker logs --since 5m "$CT_H" 2>&1 | grep -a 'sendMessage' | tail -1 | sed 's/^/    /'
  echo "  治理足跡(收信也受治理):"
  docker logs "$CT_H" 2>&1 | grep -a 'greenmail_mail' | tail -1 | sed 's/^/    /'
else
  echo "  ⚠ 120s 內未偵測到 sendMessage(LLM 非確定性)。重跑本段或改口述;以 OCSF log 為準。"
fi

hr "④ 下一步(手機上演):網管回「修」→ Hermes 判型自委派 → A1 報修主線(44s 修復 → 結案)"
cat <<'EOF'
  【手機發】修
  【會看到】Hermes 委派 OpenClaw 修復(POST /fix drift)→ 修回 5 處安全退化、3 處漂移開 Jira 待審 → 結案回報
  佐證同 demo_telegram.md A1(ALLOWED [policy:openclaw_bridge] / FIX DONE / policy:jira)
  彩排還原:bash tests/bridge-regress.sh drift
EOF
echo
echo "🗣 講點:Part A 的報修是「人發現問題」;這一段是「系統自己發現、自己敲人」——"
echo "   發現靠監控(現況 vs 核准基準,確定性比對)、通知靠對人前台(Telegram 推播也走治理 egress)、"
echo "   修復靠同一條受治理委派鏈。凌晨兩點不再需要值班的人剛好醒著。"
