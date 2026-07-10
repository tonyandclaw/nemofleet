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
#     ③ ALL-AGENTIC push: call team-lead's own Hermes chat API (:8642, gateway-token auth — same
#        mechanism as team-lead-console.sh's `chat` mode / eval.py) so *it* reasons over the state and
#        composes the report in its own voice; the host then delivers that text via the already-verified
#        Telegram Bot API. (2026-07-10: previously tried to "wake" team-lead through an email inbox it
#        never actually polled — TEAMLEAD_EMAIL was unset and no email adapter exists in its Hermes
#        config, so every wake silently failed and only the deterministic safety-net ever reached you.
#        Delivery no longer depends on team-lead successfully invoking a tool — just on it returning text.)
#        Critical → immediate; routine → hourly digest.
#     ④ 自主巡查(look-around, 2026-07-10 新增):若這輪沒有 critical/warning/digest 觸發,team-lead 仍然
#        每個 patrol_interval_sec 被喚醒一次 —— 但這次給的是完整現況 + 連續未解決問題(streak)+ 近期趨勢,
#        且**非強制發送**:由 team-lead 自己判斷值不值得留意/查證/通知。沒有這一輪的話,patrol_interval_sec
#        只等於「host script 又 diff 了一次」,team-lead 本身完全不會被叫醒 —— 這正是先前「設 5 分鐘卻像
#        在發呆」的根因(舊版只在 critical/warning/hourly digest 才喚醒 team-lead)。
#   Respects settings: proactive_enabled / patrol_interval_sec / digest_interval_sec / quiet hours /
#   recipients / notify_channels (all live in the worker settings, editable from the dashboard).
set -uo pipefail
DIR=$NEMOFLEET_ROOT
SNAP="$DATA_DIR/proactive-snapshot.json"
DIGEST_STAMP="$DATA_DIR/proactive-last-digest"
TOKEN_FILE="$BRIDGE_TOKEN_FILE"
log(){ printf '[proactive %s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }  # stderr — patrol()'s stdout is captured as JSON by OUT=$(patrol)

wk(){ # $1 = worker fragment, $2 = endpoint path → raw JSON (empty on failure)
  local c; c=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -m1 "openshell-$1-") || true
  [ -n "$c" ] || { echo ""; return 0; }
  local tok=""; [ -s "$TOKEN_FILE" ] && tok=$(cat "$TOKEN_FILE")
  docker exec "$c" sh -c "curl -s -m20 -H 'X-Bridge-Token: $tok' http://127.0.0.1:9099$2" 2>/dev/null || echo ""
}

# one patrol: gather → (hybrid) confirm-scan → diff snapshot → emit critical/routine/summary + new snapshot.
# Python does the JSON diff and prints a single JSON control object on stdout.
patrol(){
  local MON JIRA LAST CVE CERT FIRM REV
  MON=$(wk "$WORKERA_CT_NAME" /monitor)          # device status + regressions (worker-a self-scheduled)
  JIRA=$(wk "$WORKERA_CT_NAME" /jira)             # open escalation queue
  LAST=$(wk "$WORKERA_CT_NAME" /last)             # last remediation result
  CVE=$(wk "$WORKERB_CT_NAME" /cve)               # fleet CVE (worker-b self-scheduled)
  CERT=$(wk "$WORKERA_CT_NAME" /cert-scan 2>/dev/null || echo "")  # cert posture
  FIRM=$(wk "$WORKERC_CT_NAME" /firmware 2>/dev/null || echo "")   # governance: firmware urgency
  REV=$(wk "$WORKERC_CT_NAME" /reviews 2>/dev/null || echo "")     # governance: QA verdict log
  # hybrid: if worker-a is unreachable OR /monitor shows an offline/alert device, force a fresh scan once
  if [ -z "$MON" ] || printf '%s' "$MON" | grep -q '"status": *"\(ALERT\|offline\)"'; then
    log "anomaly/stale → forcing worker-a /monitor-scan (hybrid confirm)"
    wk "$WORKERA_CT_NAME" /monitor-scan >/dev/null 2>&1
    MON=$(wk "$WORKERA_CT_NAME" /monitor)
  fi
  MON="$MON" JIRA="$JIRA" LAST="$LAST" CVE="$CVE" CERT="$CERT" FIRM="$FIRM" REV="$REV" SNAP="$SNAP" \
  DIGEST_STAMP="$DIGEST_STAMP" DIGEST_IV="$DIGEST_IV" python3 - <<'PY'
import os, json, time
def load(env):
    try: return json.loads(os.environ.get(env) or "{}")
    except Exception: return {}
mon, jira, last, cve, cert, firm, rev = load("MON"), load("JIRA"), load("LAST"), load("CVE"), load("CERT"), load("FIRM"), load("REV")
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
reviews = rev.get("reviews") or []
cur = {
    "devices": devices,
    "jira_open": sorted([t.get("id") for t in (jira.get("tickets") or []) if t.get("id")]),
    "cve_affected": (cve.get("counts") or {}).get("affected", cve.get("affected")),
    "cert_high": (cert.get("counts") or {}).get("high"),
    "last_fix": {"bug": last.get("bug"), "ok": last.get("ok"), "asset": last.get("asset"), "ts": last.get("ts")},
    "worker_a_up": bool(mon), "worker_b_up": bool(cve), "worker_c_up": bool(firm) or bool(rev),
    "firmware_urgency": firm.get("urgency"),
    "review_ts": [r.get("ts") for r in reviews if r.get("ts")],
}
# streak: 連續幾輪巡邏這台設備都還是離線的(上面的 delta 只在 online→offline 那一瞬間觸發一次 crit;
# 如果卡著離線好幾小時,舊版邏輯完全沒有新訊號 —— 這正是「看起來主動、其實在發呆」的另一個根因)。
offline_streak = {}
for a, dv in devices.items():
    prev = (old.get("offline_streak") or {}).get(a, 0)
    offline_streak[a] = (prev + 1) if dv["offline"] else 0
cur["offline_streak"] = offline_streak
stale = [f"{a} 已連續 {n} 輪巡邏仍離線,尚未解決" for a, n in offline_streak.items() if n >= 2]

crit, warn, routine = [], [], []
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
# CVE / cert deltas — a worsening count is a warning (immediate), an improving count is routine (digest)
old_cve, old_cert = old.get("cve_affected"), old.get("cert_high")
if cur["cve_affected"] is not None and cur["cve_affected"] != old_cve:
    msg = f"CVE affected 數變化 {old_cve} → {cur['cve_affected']}"
    (warn if old_cve is not None and cur["cve_affected"] > old_cve else routine).append(msg)
if cur["cert_high"] is not None and cur["cert_high"] != old_cert:
    msg = f"憑證高風險數變化 {old_cert} → {cur['cert_high']}"
    (warn if old_cert is not None and cur["cert_high"] > old_cert else routine).append(msg)
# worker/endpoint down
for w, up in (("worker-a", cur["worker_a_up"]), ("worker-b", cur["worker_b_up"]), ("worker-c", cur["worker_c_up"])):
    was = old.get(w.replace("-", "_") + "_up", True)
    if was and not up:
        crit.append(f"{w} IT-ops 端點沒回應")
# worker-c governance: firmware urgency escalation, new reject verdicts
old_urgency, new_urgency = old.get("firmware_urgency"), cur["firmware_urgency"]
_urg_rank = {"normal": 0, "low": 0, "medium": 1, "high": 2, "urgent": 3, "critical": 3}
if new_urgency is not None and new_urgency != old_urgency:
    msg = f"韌體緊急度變化 {old_urgency} → {new_urgency}"
    (warn if _urg_rank.get(str(new_urgency).lower(), 0) > _urg_rank.get(str(old_urgency).lower(), 0) else routine).append(msg)
new_review_ts = set(cur["review_ts"]) - set(old.get("review_ts") or [])
if new_review_ts:
    rejects = [r for r in reviews if r.get("ts") in new_review_ts and r.get("verdict") == "reject"]
    if rejects:
        warn.append(f"worker-c 覆核擋下 {len(rejects)} 筆(kind: {', '.join(sorted(set(r.get('kind','?') for r in rejects)))})")
    if len(rejects) < len(new_review_ts):
        routine.append(f"worker-c 新覆核 {len(new_review_ts) - len(rejects)} 筆通過")

# digest cadence
stampf = os.environ["DIGEST_STAMP"]; iv = int(os.environ.get("DIGEST_IV") or "3600")
try: last_digest = float(open(stampf).read().strip())
except Exception: last_digest = 0.0
digest_due = (time.time() - last_digest) >= iv

summary_lines, summary_lines_en = [], []
for a, dv in devices.items():
    st = dv.get('status') or ('offline' if dv['offline'] else 'online')
    summary_lines.append(f"- {a}: {st}" + (f" · 退化 {len(dv['regressions'])}" if dv['regressions'] else ""))
    summary_lines_en.append(f"- {a}: {st}" + (f" · {len(dv['regressions'])} regression(s)" if dv['regressions'] else ""))
summary = ("機隊 %d 台;開單 %d;CVE affected %s;憑證高風險 %s\n" % (
    len(devices), len(cur["jira_open"]), cur["cve_affected"], cur["cert_high"])) + "\n".join(summary_lines)
summary_en = ("Fleet: %d device(s); open tickets %d; CVE affected %s; cert high-risk %s\n" % (
    len(devices), len(cur["jira_open"]), cur["cve_affected"], cur["cert_high"])) + "\n".join(summary_lines_en)

print(json.dumps({"critical": crit, "warning": warn, "routine": routine, "digest_due": digest_due,
                  "stale": stale,
                  "summary": summary, "summary_en": summary_en, "snapshot": cur}, ensure_ascii=False))
PY
}

# 喚醒 team-lead:直接打它自己的 Hermes chat API 取得推理/文字(同 team-lead-console.sh 的 chat 模式 /
# eval.py 用的機制:gateway-token 認證),host 再用已驗證可用的 Telegram Bot API 送出 —— 送達不依賴
# team-lead 是否真的成功呼叫工具,只依賴它有沒有回文字。
wake_teamlead(){ # $1 = kind (即時告警|警告|巡邏日報|自主巡查), $2 = body context
  local chat="${TELEGRAM_CHAT_ID:-}"
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "$chat" ]; then
    log "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 未設,無法喚醒 team-lead(見 ~/.config/nemoclaw/nemofleet-notify.env)"
    return 1
  fi
  command -v openshell >/dev/null 2>&1 && openshell forward start --background 8642 team-lead >/dev/null 2>&1
  local gtok; gtok=$(nemoclaw team-lead gateway-token --quiet 2>/dev/null)
  if [ -z "$gtok" ]; then log "拿不到 team-lead gateway token,無法喚醒(${1})"; return 1; fi

  local instr
  if [ "$1" = "自主巡查" ]; then
    # 非強制發送:給 team-lead 真正的自主判斷回合,不是又一個門檻觸發的罐頭訊息。
    instr="你是主動巡邏的 team-lead,這是你自己的自主巡查回合(不是被 critical/warning 門檻觸發,是每輪
patrol_interval_sec 都給你的「看一眼」機會)。以下是目前機隊完整現況、連續未解決的問題、和近期巡邏趨勢。

像真的在值班的人一樣自己判斷:如果有什麼值得留意(例如某個問題卡了好幾輪都沒解決、有異常趨勢、該主動跟催),
就直接回覆要發給網管的 Telegram 訊息內容本身(純文字,不要加引號或任何額外說明,你的回覆會被原封不動發出去)。
如果看過之後一切正常、沒有新資訊,不用勉強發送——只回覆英文單字 NOTHING(整個回覆只有這個字),不要輸出其他任何文字。"
  else
    instr="你是主動巡邏的 team-lead。以下是我(巡邏排程)剛替你收集的機隊狀態與變化。請用你自己的口吻總結:
設備狀態、發生的錯誤、你叫 worker 掃到的結果、需不需要人動作。直接回覆要發給網管的 Telegram 訊息內容本身
(純文字,不要加引號或任何額外說明、不要重複這段指示——你的回覆會被原封不動發出去給網管)。"
  fi
  local prompt="${instr}

【${1}】
${2}"

  local content; content=$(GTOK="$gtok" PROMPT="$prompt" python3 -c '
import os, json, urllib.request
token = os.environ["GTOK"]; prompt = os.environ["PROMPT"]
body = json.dumps({"model": "nemotron-super", "stream": False, "max_tokens": 500,
                   "messages": [{"role": "user", "content": prompt}]}).encode()
req = urllib.request.Request("http://127.0.0.1:8642/v1/chat/completions", data=body,
                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
try:
    with urllib.request.urlopen(req, timeout=240) as r:
        d = json.loads(r.read())
    print((d["choices"][0]["message"].get("content") or "").strip())
except Exception as e:
    print("__ERR__ " + str(e))
' 2>/dev/null)

  if [ -z "$content" ]; then log "喚醒 team-lead 失敗(Hermes 無回應,${1})"; return 1; fi
  case "$content" in
    __ERR__*) log "喚醒 team-lead 失敗(${content#__ERR__ },${1})"; return 1 ;;
  esac
  if [ "$1" = "自主巡查" ] && printf '%s' "$content" | grep -qix 'NOTHING'; then
    log "自主巡查:team-lead 判斷無需通知(靜默)"
    return 0
  fi
  curl -s -m10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=$chat" --data-urlencode "text=$content" >/dev/null 2>&1 \
    && log "team-lead 已回覆並送出 Telegram(${1})" || log "team-lead 已回覆但 Telegram 送出失敗(${1})"
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
  SNOOZE_UNTIL=$(printf '%s' "$S" | python3 -c 'import sys,json;print(int(json.load(sys.stdin).get("proactive_snooze_until",0)))' 2>/dev/null || echo 0)
  export DIGEST_IV RECIPIENTS_JSON SAFETY_NET SNOOZE_UNTIL
  if [ "$PROACTIVE" != "True" ]; then
    log "proactive_enabled=off,略過"; PATROL_INTERVAL=$PATROL_IV
    printf '{"enabled":false}' > "$DATA_DIR/proactive-status.json" 2>/dev/null || true
    return 0
  fi
  PATROL_INTERVAL=$PATROL_IV

  local OUT; OUT=$(patrol) || {
    log "patrol 失敗"
    local now last_alert; now=$(date +%s)
    last_alert=$(cat "$DATA_DIR/proactive-fail-last-alert" 2>/dev/null || echo 0)
    if [ $((now - last_alert)) -ge 3600 ]; then
      deterministic_alert "⚠️ NemoFleet patrol error" "巡邏排程本身執行失敗(worker 端點無回應或掃描腳本錯誤)。請檢查 team-lead 主機的 scripts/teamlead-proactive.sh 日誌;此告警每小時最多發一次,直到巡邏恢復正常。"
      echo "$now" > "$DATA_DIR/proactive-fail-last-alert"
    fi
    return 0
  }
  rm -f "$DATA_DIR/proactive-fail-last-alert" 2>/dev/null || true
  local NCRIT NWARN NROUT DUE
  NCRIT=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["critical"]))' 2>/dev/null || echo 0)
  NWARN=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["warning"]))' 2>/dev/null || echo 0)
  NROUT=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["routine"]))' 2>/dev/null || echo 0)
  DUE=$(printf '%s' "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["digest_due"])' 2>/dev/null || echo False)
  log "patrol: critical=$NCRIT warning=$NWARN routine=$NROUT digest_due=$DUE"

  # persist snapshot for next diff
  printf '%s' "$OUT" | python3 -c 'import sys,json;json.dump(json.load(sys.stdin)["snapshot"],open(sys.argv[1],"w"),ensure_ascii=False)' "$SNAP" 2>/dev/null || true

  local IN_QUIET=0
  [ "${SNOOZE_UNTIL:-0}" -gt "$(date +%s)" ] && IN_QUIET=1
  local ANY_WAKE=0

  # ① critical → immediate agentic alert + deterministic safety net
  if [ "${NCRIT:-0}" -gt 0 ]; then
    local BODY; BODY=$(printf '%s' "$OUT" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("關鍵變化:\n- "+"\n- ".join(d["critical"])+"\n\n現況:\n"+d["summary"])')
    if [ "$IN_QUIET" = 1 ]; then
      log "critical $NCRIT 筆,但在維護靜音期 → 不打斷(仍巡邏+記錄)"
    else
      [ "${SAFETY_NET:-True}" = "True" ] && deterministic_alert "⚠️ NemoFleet critical" "$BODY"   # 保證送達(不依賴 team-lead)
      wake_teamlead "即時告警" "$BODY"   # 加值:team-lead 自然語言
      ANY_WAKE=1
    fi
  fi
  # ①b warning → same immediate treatment as critical, distinct label, no need to wait for the hourly digest
  if [ "${NWARN:-0}" -gt 0 ]; then
    local WBODY; WBODY=$(printf '%s' "$OUT" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("需留意的變化:\n- "+"\n- ".join(d["warning"])+"\n\n現況:\n"+d["summary"])')
    if [ "$IN_QUIET" = 1 ]; then
      log "warning $NWARN 筆,但在維護靜音期 → 不打斷(仍巡邏+記錄)"
    else
      [ "${SAFETY_NET:-True}" = "True" ] && deterministic_alert "🔔 NemoFleet warning" "$WBODY"   # 保證送達,不等 team-lead 的 LLM turn
      wake_teamlead "警告" "$WBODY"
      ANY_WAKE=1
    fi
  fi
  # ② digest cadence → agentic status report (even if all-green: proactive "我巡過了,沒事")
  if [ "$DUE" = "True" ]; then
    local BODY; BODY=$(printf '%s' "$OUT" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["summary"]+("\n\n本輪變化:\n- "+"\n- ".join(d["routine"]) if d["routine"] else "\n\n本輪無新變化,一切正常。"))')
    wake_teamlead "巡邏日報" "$BODY"
    date +%s > "$DIGEST_STAMP"
    ANY_WAKE=1
  fi
  # ④ 自主巡查:這輪沒有 critical/warning/digest → team-lead 仍然真的被叫醒一次,拿到完整現況 + 連續未
  # 解決問題(stale)+ 近期趨勢,自己判斷值不值得動作。這是讓 patrol_interval_sec 對應到「team-lead 真的
  # 想了一次」,不只是「host script 又 diff 了一次」。
  local LOOKAROUND_SENT=0
  if [ "$ANY_WAKE" -eq 0 ] && [ "$IN_QUIET" -eq 0 ]; then
    local TREND; TREND=$(tail -n 5 "$DATA_DIR/proactive-log.jsonl" 2>/dev/null | python3 -c 'import sys,json
for l in sys.stdin:
    l = l.strip()
    if not l: continue
    try: r = json.loads(l)
    except Exception: continue
    print(f"- {r.get(\"ts\")}: critical {len(r.get(\"critical\") or [])}、warning {len(r.get(\"warning\") or [])}、routine {len(r.get(\"routine\") or [])}")' 2>/dev/null)
    [ -n "$TREND" ] || TREND="(無歷史紀錄,可能是第一輪)"
    local LBODY; LBODY=$(printf '%s' "$OUT" | STALE_TREND="$TREND" python3 -c 'import sys,json,os
d=json.load(sys.stdin)
stale = d.get("stale") or []
parts = [d["summary"]]
if stale:
    parts.append("連續未解決:\n- " + "\n- ".join(stale))
else:
    parts.append("目前沒有連續未解決的項目。")
parts.append("近期巡邏趨勢(最近 5 輪):\n" + os.environ.get("STALE_TREND",""))
print("\n\n".join(parts))')
    wake_teamlead "自主巡查" "$LBODY"
    LOOKAROUND_SENT=1
  elif [ "$ANY_WAKE" -eq 0 ] && [ "$IN_QUIET" -eq 1 ]; then
    log "無 critical/warning/digest,但在維護靜音期 → 自主巡查也不打斷"
  fi

  # record status + rolling log for dashboard visibility (/api/status → proactive)
  OUT="$OUT" NCRIT="$NCRIT" NWARN="$NWARN" NROUT="$NROUT" DUE="$DUE" SAFETY_NET="${SAFETY_NET:-True}" \
  PATROL_IV="$PATROL_IV" DIGEST_IV="$DIGEST_IV" SNOOZE_UNTIL="${SNOOZE_UNTIL:-0}" STATUS="$DATA_DIR/proactive-status.json" \
  LOOKAROUND_SENT="$LOOKAROUND_SENT" PLOG="$DATA_DIR/proactive-log.jsonl" python3 - <<'PYREC' 2>/dev/null || true
import os, json, time
try: out = json.loads(os.environ["OUT"])
except Exception: out = {"critical": [], "warning": [], "routine": [], "stale": [], "summary": "", "summary_en": ""}
now = time.strftime("%Y-%m-%d %H:%M:%S"); nc = int(os.environ.get("NCRIT") or 0); nw = int(os.environ.get("NWARN") or 0)
lookaround = os.environ.get("LOOKAROUND_SENT") == "1"
json.dump({"enabled": True, "patrol_interval_sec": int(os.environ.get("PATROL_IV") or 1200),
           "digest_interval_sec": int(os.environ.get("DIGEST_IV") or 3600),
           "safety_net": os.environ.get("SAFETY_NET") == "True", "last_patrol": now,
           "last_critical": nc, "last_warning": nw, "last_routine": int(os.environ.get("NROUT") or 0), "snooze_until": int(os.environ.get("SNOOZE_UNTIL") or 0),
           "last_lookaround": lookaround, "stale": out.get("stale", []),
           "summary": out.get("summary", ""), "summary_en": out.get("summary_en", "")}, open(os.environ["STATUS"], "w"), ensure_ascii=False)
rec = {"ts": now, "critical": out.get("critical", []), "warning": out.get("warning", []), "routine": out.get("routine", []),
       "stale": out.get("stale", []),
       "digest_sent": os.environ.get("DUE") == "True", "lookaround_sent": lookaround,
       "safety_net_fired": (nc > 0 or nw > 0) and os.environ.get("SAFETY_NET") == "True"}
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
