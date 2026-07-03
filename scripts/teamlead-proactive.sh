#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# teamlead-proactive.sh — makes team-lead an ACTIVE agent, not a passive front desk.
#   Heartbeat loop (host-side, like the dashboard loops):
#     ① drive worker scans (hybrid: read self-scheduled results; force a rescan on staleness/anomaly)
#     ② detect fleet status / error DELTAS vs the last snapshot (device up↔down, remediation ok/fail,
#        new Jira, new CVE / cert findings, worker endpoint down)
#     ③ ALL-AGENTIC push: wake team-lead via its email channel so *it* composes + sends the report in
#        its own voice (that turn has the send_message tool). Critical → immediate; routine → hourly digest.
#   Respects settings: proactive_enabled / patrol_interval_sec / digest_interval_sec / quiet hours /
#   recipients / notify_channels (all live in the worker settings, editable from the dashboard).
set -uo pipefail
DIR=$NEMOFLEET_ROOT
SNAP="$DATA_DIR/proactive-snapshot.json"
DIGEST_STAMP="$DATA_DIR/proactive-last-digest"
TOKEN_FILE="$BRIDGE_TOKEN_FILE"
NOTIFY_SENDER="${NOTIFY_SENDER:-tony@demo.local}"   # authorized sender that wakes team-lead's email turn
log(){ printf '[proactive %s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

wk(){ # $1 = worker fragment, $2 = endpoint path → raw JSON (empty on failure)
  local c; c=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -m1 "openshell-$1-") || true
  [ -n "$c" ] || { echo ""; return 0; }
  local tok=""; [ -s "$TOKEN_FILE" ] && tok=$(cat "$TOKEN_FILE")
  docker exec "$c" sh -c "curl -s -m20 -H 'X-Bridge-Token: $tok' http://127.0.0.1:9099$2" 2>/dev/null || echo ""
}

# one patrol: gather → (hybrid) confirm-scan → diff snapshot → emit critical/routine/summary + new snapshot.
# Python does the JSON diff and prints a single JSON control object on stdout.
patrol(){
  local MON JIRA LAST CVE CERT
  MON=$(wk "$WORKERA_CT_NAME" /monitor)          # device status + regressions (worker-a self-scheduled)
  JIRA=$(wk "$WORKERA_CT_NAME" /jira)             # open escalation queue
  LAST=$(wk "$WORKERA_CT_NAME" /last)             # last remediation result
  CVE=$(wk "$WORKERB_CT_NAME" /cve)               # fleet CVE (worker-b self-scheduled)
  CERT=$(wk "$WORKERA_CT_NAME" /cert-scan 2>/dev/null || echo "")  # cert posture
  # hybrid: if worker-a is unreachable OR /monitor shows an offline/alert device, force a fresh scan once
  if [ -z "$MON" ] || printf '%s' "$MON" | grep -q '"status": *"\(ALERT\|offline\)"'; then
    log "anomaly/stale → forcing worker-a /monitor-scan (hybrid confirm)"
    wk "$WORKERA_CT_NAME" /monitor-scan >/dev/null 2>&1
    MON=$(wk "$WORKERA_CT_NAME" /monitor)
  fi
  MON="$MON" JIRA="$JIRA" LAST="$LAST" CVE="$CVE" CERT="$CERT" SNAP="$SNAP" \
  DIGEST_STAMP="$DIGEST_STAMP" DIGEST_IV="$DIGEST_IV" python3 - <<'PY'
import os, json, time
def load(env):
    try: return json.loads(os.environ.get(env) or "{}")
    except Exception: return {}
mon, jira, last, cve, cert = load("MON"), load("JIRA"), load("LAST"), load("CVE"), load("CERT")
snap_path = os.environ["SNAP"]
try: old = json.load(open(snap_path))
except Exception: old = {}

# --- build current compact fleet state ---
devices = {}
for d in (mon.get("devices") or []):
    devices[d.get("asset", "?")] = {
        "status": d.get("status"), "regressions": sorted(d.get("regressions") or []),
        "cpu": d.get("cpu"), "offline": bool(d.get("offline")),
    }
cur = {
    "devices": devices,
    "jira_open": sorted([t.get("id") for t in (jira.get("tickets") or []) if t.get("id")]),
    "cve_affected": (cve.get("counts") or {}).get("affected", cve.get("affected")),
    "cert_high": (cert.get("counts") or {}).get("high"),
    "last_fix": {"bug": last.get("bug"), "ok": last.get("ok"), "asset": last.get("asset"), "ts": last.get("ts")},
    "worker_a_up": bool(mon), "worker_b_up": bool(cve),
}

crit, routine = [], []
od = old.get("devices") or {}
for a, dv in devices.items():
    ov = od.get(a) or {}
    if dv["offline"] and not ov.get("offline"):
        crit.append(f"設備 {a} 離線(前一輪還在)")
    elif not dv["offline"] and ov.get("offline"):
        routine.append(f"設備 {a} 已恢復上線")
    new_reg = set(dv["regressions"]) - set(ov.get("regressions") or [])
    if new_reg:
        crit.append(f"{a} 新增安全退化:{', '.join(sorted(new_reg))}")
    cleared = set(ov.get("regressions") or []) - set(dv["regressions"])
    if cleared:
        routine.append(f"{a} 安全退化已修回:{', '.join(sorted(cleared))}")
# remediation result change
lf, olf = cur["last_fix"], (old.get("last_fix") or {})
if lf.get("ts") and lf.get("ts") != olf.get("ts"):
    (crit if lf.get("ok") is False else routine).append(
        f"remediation {lf.get('bug')} on {lf.get('asset')} → {'成功' if lf.get('ok') else '失敗'}")
# new Jira tickets
new_tix = set(cur["jira_open"]) - set(old.get("jira_open") or [])
for t in sorted(new_tix):
    crit.append(f"新開 Jira 工單 {t}")
# CVE / cert deltas
if cur["cve_affected"] is not None and cur["cve_affected"] != old.get("cve_affected"):
    routine.append(f"CVE affected 數變化 {old.get('cve_affected')} → {cur['cve_affected']}")
if cur["cert_high"] is not None and cur["cert_high"] != old.get("cert_high"):
    routine.append(f"憑證高風險數變化 {old.get('cert_high')} → {cur['cert_high']}")
# worker/endpoint down
for w, up in (("worker-a", cur["worker_a_up"]), ("worker-b", cur["worker_b_up"])):
    was = old.get(w.replace("-", "_") + "_up", True)
    if was and not up:
        crit.append(f"{w} IT-ops 端點沒回應")

# digest cadence
stampf = os.environ["DIGEST_STAMP"]; iv = int(os.environ.get("DIGEST_IV") or "3600")
try: last_digest = float(open(stampf).read().strip())
except Exception: last_digest = 0.0
digest_due = (time.time() - last_digest) >= iv

summary_lines = []
for a, dv in devices.items():
    summary_lines.append(f"- {a}: {dv.get('status') or ('offline' if dv['offline'] else 'online')}"
                         + (f" · 退化 {len(dv['regressions'])}" if dv['regressions'] else ""))
summary = ("機隊 %d 台;開單 %d;CVE affected %s;憑證高風險 %s\n" % (
    len(devices), len(cur["jira_open"]), cur["cve_affected"], cur["cert_high"])) + "\n".join(summary_lines)

print(json.dumps({"critical": crit, "routine": routine, "digest_due": digest_due,
                  "summary": summary, "snapshot": cur}, ensure_ascii=False))
PY
}

# wake team-lead's email turn so IT composes + sends the report in its own voice (all-agentic).
wake_teamlead(){ # $1 = kind (即時告警|巡邏日報), $2 = body context
  local to="${TEAMLEAD_EMAIL:-}"
  [ -n "$to" ] || { log "TEAMLEAD_EMAIL 未設,無法喚醒 team-lead(見 .env)"; return 1; }
  local chat="${TELEGRAM_CHAT_ID:-<你的 chat id>}"
  local prompt="你是主動巡邏的 team-lead。以下是我(巡邏排程)剛替你收集的機隊狀態與變化。請**務必實際呼叫你的 send_message 工具**,主動發 Telegram 給網管 chat id ${chat},用你自己的口吻總結:設備狀態、發生的錯誤、你叫 worker 掃到的結果、需不需要人動作;並回一封 email 摘要。不要只在回信說明,要真的呼叫工具發送。

【${1}】
${2}"
  bash "$MAIL_DIR/send-mail-as.sh" "$NOTIFY_SENDER" "NemoFleet 主動巡邏 · ${1}" "$prompt" >/dev/null 2>&1 \
    && log "已喚醒 team-lead 發送(${1})" || log "喚醒 team-lead 失敗(mail?)"
}

# 確定性安全網:critical 保證送達 recipients,不依賴 team-lead / agentic 路徑。
#   Email 走真實 SMTP(send-to.sh);Telegram 若 .env 設了 TELEGRAM_BOT_TOKEN 就走 Bot API 直送(host-side break-glass)。
deterministic_alert(){ # $1=subject $2=body ; 讀 $RECIPIENTS_JSON
  local subj="$1" body="$2" sent=0
  while IFS=$'\t' read -r email tg; do
    [ -n "$email" ] && { bash "$MAIL_DIR/send-to.sh" "$email" "$subj" "$body" >/dev/null 2>&1 && sent=$((sent+1)); }
    if [ -n "$tg" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
      curl -s -m10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=$tg" --data-urlencode "text=$subj\n$body" >/dev/null 2>&1 && sent=$((sent+1))
    fi
  done < <(printf '%s' "${RECIPIENTS_JSON:-[]}" | python3 -c 'import sys,json
try: rs=json.load(sys.stdin)
except Exception: rs=[]
for r in rs: print((r.get("email") or "")+"\t"+(r.get("telegram") or ""))' 2>/dev/null)
  # 個人 chat id(.env TELEGRAM_CHAT_ID)+ bot token → 直送(保底)
  if [ -n "${TELEGRAM_CHAT_ID:-}" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
    curl -s -m10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" --data-urlencode "text=$subj\n$body" >/dev/null 2>&1 && sent=$((sent+1))
  fi
  log "確定性安全網:critical 直送 $sent 則(email/SMTP + Telegram Bot API,不經 team-lead)"
}

run_cycle(){
  local S PROACTIVE PATROL_IV QUIET
  S=$(wk "$WORKERA_CT_NAME" /settings)
  PROACTIVE=$(printf '%s' "$S" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("proactive_enabled",True))' 2>/dev/null || echo True)
  PATROL_IV=$(printf '%s' "$S" | python3 -c 'import sys,json;print(int(json.load(sys.stdin).get("patrol_interval_sec",1200)))' 2>/dev/null || echo 1200)
  DIGEST_IV=$(printf '%s' "$S" | python3 -c 'import sys,json;print(int(json.load(sys.stdin).get("digest_interval_sec",3600)))' 2>/dev/null || echo 3600)
  RECIPIENTS_JSON=$(printf '%s' "$S" | python3 -c 'import sys,json;print(json.dumps(json.load(sys.stdin).get("recipients",[]),ensure_ascii=False))' 2>/dev/null || echo "[]")
  SAFETY_NET=$(printf '%s' "$S" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("proactive_safety_net",True))' 2>/dev/null || echo True)
  export DIGEST_IV RECIPIENTS_JSON SAFETY_NET
  if [ "$PROACTIVE" != "True" ]; then
    log "proactive_enabled=off,略過"; PATROL_INTERVAL=$PATROL_IV
    printf '{"enabled":false}' > "$DATA_DIR/proactive-status.json" 2>/dev/null || true
    return 0
  fi
  PATROL_INTERVAL=$PATROL_IV

  local OUT; OUT=$(patrol) || { log "patrol 失敗"; return 0; }
  local NCRIT NROUT DUE
  NCRIT=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["critical"]))' 2>/dev/null || echo 0)
  NROUT=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["routine"]))' 2>/dev/null || echo 0)
  DUE=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["digest_due"])' 2>/dev/null || echo False)
  log "patrol: critical=$NCRIT routine=$NROUT digest_due=$DUE"

  # persist snapshot for next diff
  printf '%s' "$OUT" | python3 -c 'import sys,json;json.dump(json.load(sys.stdin)["snapshot"],open(sys.argv[1],"w"),ensure_ascii=False)' "$SNAP" 2>/dev/null || true

  # ① critical → immediate agentic alert
  if [ "${NCRIT:-0}" -gt 0 ]; then
    local BODY; BODY=$(printf '%s' "$OUT" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("關鍵變化:\n- "+"\n- ".join(d["critical"])+"\n\n現況:\n"+d["summary"])')
    [ "${SAFETY_NET:-True}" = "True" ] && deterministic_alert "⚠️ NemoFleet critical" "$BODY"   # 保證送達(不依賴 team-lead)
    wake_teamlead "即時告警" "$BODY"   # 加值:team-lead 自然語言
  fi
  # ② digest cadence → agentic status report (even if all-green: proactive "我巡過了,沒事")
  if [ "$DUE" = "True" ]; then
    local BODY; BODY=$(printf '%s' "$OUT" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["summary"]+("\n\n本輪變化:\n- "+"\n- ".join(d["routine"]) if d["routine"] else "\n\n本輪無新變化,一切正常。"))')
    wake_teamlead "巡邏日報" "$BODY"
    date +%s > "$DIGEST_STAMP"
  fi

  # record status + rolling log for dashboard visibility (/api/status → proactive)
  OUT="$OUT" NCRIT="$NCRIT" NROUT="$NROUT" DUE="$DUE" SAFETY_NET="${SAFETY_NET:-True}" \
  PATROL_IV="$PATROL_IV" DIGEST_IV="$DIGEST_IV" STATUS="$DATA_DIR/proactive-status.json" \
  PLOG="$DATA_DIR/proactive-log.jsonl" python3 - <<'PYREC' 2>/dev/null || true
import os, json, time
try: out = json.loads(os.environ["OUT"])
except Exception: out = {"critical": [], "routine": [], "summary": ""}
now = time.strftime("%Y-%m-%d %H:%M:%S"); nc = int(os.environ.get("NCRIT") or 0)
json.dump({"enabled": True, "patrol_interval_sec": int(os.environ.get("PATROL_IV") or 1200),
           "digest_interval_sec": int(os.environ.get("DIGEST_IV") or 3600),
           "safety_net": os.environ.get("SAFETY_NET") == "True", "last_patrol": now,
           "last_critical": nc, "last_routine": int(os.environ.get("NROUT") or 0),
           "summary": out.get("summary", "")}, open(os.environ["STATUS"], "w"), ensure_ascii=False)
rec = {"ts": now, "critical": out.get("critical", []), "routine": out.get("routine", []),
       "digest_sent": os.environ.get("DUE") == "True",
       "safety_net_fired": nc > 0 and os.environ.get("SAFETY_NET") == "True"}
try: lines = [l for l in open(os.environ["PLOG"]) if l.strip()][-49:]
except Exception: lines = []
lines.append(json.dumps(rec, ensure_ascii=False))
open(os.environ["PLOG"], "w").write("\n".join(lines) + "\n")
PYREC
}

TRIGGER="$DATA_DIR/proactive-trigger"
log "team-lead 主動巡邏啟動(snapshot: $SNAP)"
PATROL_INTERVAL=1200
while true; do
  run_cycle || true
  # poll-sleep:每 20s 檢查手動觸發(dashboard「Patrol now」),否則睡滿 patrol_interval
  waited=0
  while [ "$waited" -lt "${PATROL_INTERVAL:-1200}" ]; do
    [ -f "$TRIGGER" ] && { rm -f "$TRIGGER"; log "手動觸發巡邏(dashboard)"; break; }
    sleep 20; waited=$((waited + 20))
  done
done
