#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# team-lead-console.sh — two things in one script, both write results to chats/ for later review:
#
#   gui-test  — drives every SAFE dashboard action by calling the exact same mechanism do_action()/
#               do_sys() in agent-dashboard.py use (worker :9099 endpoints via the bridge token,
#               or the same nemoclaw/openshell CLI commands) — no dashboard login needed, since we
#               don't have (and shouldn't ask for) your dashboard password. Destructive/high-impact
#               actions (freeze, rebuild, upgrade, gcrun, infset, chanstart/stop, hosts-add/rm,
#               forward start/stop, recover) are intentionally SKIPPED, not silently omitted —
#               they're listed in the summary so nothing is hidden.
#   chat      — talk to team-lead directly, case by case, bypassing Telegram entirely (same Hermes
#               API eval.py already uses: POST :8642/v1/chat/completions with a gateway token).
#               Each turn's prompt+response is saved as its own file so you can review one case at
#               a time instead of scrolling a terminal transcript.
#
# Usage:
#   bash scripts/team-lead-console.sh gui-test
#   bash scripts/team-lead-console.sh chat
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CHATS="$DIR/chats"
mkdir -p "$CHATS"

log(){ printf '[console %s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }

TOKEN_FILE="$BRIDGE_TOKEN_FILE"
[ -s "$TOKEN_FILE" ] || { echo "找不到 bridge token($TOKEN_FILE)— 先 make boot" >&2; exit 1; }
BTOK="$(cat "$TOKEN_FILE")"

worker_get(){ docker exec "$1" sh -c "curl -s -m20 -H 'X-Bridge-Token: $BTOK' http://127.0.0.1:9099$2" 2>/dev/null; }
worker_post(){ # $1=container $2=path $3=json body (optional)
  if [ -n "${3:-}" ]; then
    docker exec "$1" sh -c "curl -s -m25 -X POST -H 'X-Bridge-Token: $BTOK' -H 'Content-Type: application/json' -d '$3' http://127.0.0.1:9099$2" 2>/dev/null
  else
    docker exec "$1" sh -c "curl -s -m25 -X POST -H 'X-Bridge-Token: $BTOK' http://127.0.0.1:9099$2" 2>/dev/null
  fi
}
json_ok(){ printf '%s' "$1" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin); print("false" if d.get("ok") is False else "true")
except Exception:
    print("false")' 2>/dev/null || echo false; }

# ── gui-test ────────────────────────────────────────────────────────────────
gui_test(){
  local ts; ts=$(date '+%Y%m%d-%H%M%S')
  local OUT="$CHATS/gui-test-$ts"
  mkdir -p "$OUT"
  log "GUI 功能自動測試開始 → $OUT"
  local npass=0 nfail=0

  record(){ # $1=case name $2=json result
    printf '%s' "$2" > "$OUT/$1.json"
    if [ "$(json_ok "$2")" = "true" ]; then echo "  ✓ $1"; npass=$((npass+1))
    else echo "  ✗ $1"; nfail=$((nfail+1)); fi
  }

  echo "== worker-b: 資安掃描按鈕 (cve / source / nuclei) =="
  if [ -n "${CT_WB:-}" ]; then
    record "worker-b_cve-rescan" "$(worker_get "$CT_WB" /cve)"
    record "worker-b_source-rescan" "$(worker_get "$CT_WB" /source-cve)"
    record "worker-b_nuclei-scan" "$(worker_post "$CT_WB" /nuclei-scan)"
  else
    echo "  (worker-b 未部署,略過 3 項)"
  fi

  echo "== worker-a: 運維按鈕 (monitor-scan / cert-scan) =="
  if [ -n "${CT_WA:-}" ]; then
    record "worker-a_monitor-scan" "$(worker_post "$CT_WA" /monitor-scan)"
    record "worker-a_cert-scan" "$(worker_get "$CT_WA" /cert-scan)"
  else
    echo "  (worker-a 未部署,略過 2 項)"
  fi

  echo "== worker-c: 治理按鈕 (backup) =="
  if [ -n "${CT_WC:-}" ]; then
    record "worker-c_backup" "$(worker_post "$CT_WC" /backup)"
  else
    echo "  (worker-c 未部署,略過 1 項)"
  fi

  echo "== team-lead: 主動巡邏 / eval 觸發按鈕(host-side trigger file)=="
  touch "$DIR/data/proactive-trigger" 2>/dev/null
  record "patrol-trigger" '{"ok":true,"msg":"touched data/proactive-trigger — 排程 daemon 20s 內輪詢生效,不等它跑完(可能要好幾分鐘)"}'
  touch "$DIR/data/eval-trigger" 2>/dev/null
  record "eval-trigger" '{"ok":true,"msg":"touched data/eval-trigger — eval 排程 20s 內輪詢生效,eval.py 本身要 15-20 分鐘,這裡不等它跑完"}'

  echo "== 診斷類按鈕(唯讀,do_sys 同款 CLI 指令)=="
  record "sys_doctor" "$(python3 -c 'import json,subprocess; r=subprocess.run(["nemoclaw","team-lead","doctor"],capture_output=True,text=True,timeout=45); print(json.dumps({"ok": True, "out": (r.stdout+r.stderr)[-2000:]}))' 2>/dev/null || echo '{"ok":false}')"
  record "sys_gsettings" "$(python3 -c 'import json,subprocess; r=subprocess.run(["openshell","settings","get","--global"],capture_output=True,text=True,timeout=15); print(json.dumps({"ok": True, "out": (r.stdout+r.stderr)[-2000:]}))' 2>/dev/null || echo '{"ok":false}')"
  record "sys_gwhealth" "$(python3 -c 'import json,subprocess; a=subprocess.run(["openshell","status"],capture_output=True,text=True,timeout=20); b=subprocess.run(["openshell","doctor"],capture_output=True,text=True,timeout=45); print(json.dumps({"ok": True, "out": (a.stdout+a.stderr+b.stdout+b.stderr)[-2000:]}))' 2>/dev/null || echo '{"ok":false}')"
  record "sys_gc-dryrun" "$(python3 -c 'import json,subprocess; r=subprocess.run(["nemoclaw","gc","--dry-run"],capture_output=True,text=True,timeout=60); print(json.dumps({"ok": True, "out": (r.stdout+r.stderr)[-2000:]}))' 2>/dev/null || echo '{"ok":false}')"

  echo
  echo "== 略過(高衝擊/會改動狀態,不自動跑;要測請手動個別執行)=="
  for skip in "freeze/unfreeze(暫停整艦隊)" "rebuild(重建沙箱)" "upgrade(升級過時沙箱)" \
              "gcrun(真的清映像)" "infset(換生產推理路由)" "chanstart/chanstop(重建沙箱)" \
              "hosts-add/hosts-remove(改 host 別名)" "forward start/stop(開關 port forward)" \
              "recover(重啟 gateway)"; do
    echo "  ⊘ $skip"
  done

  echo
  echo "== 結果:$npass 過、$nfail 敗(明細在 $OUT/*.json)=="
  [ "$nfail" -eq 0 ]
}

# ── chat ────────────────────────────────────────────────────────────────────
chat(){
  local ts; ts=$(date '+%Y%m%d-%H%M%S')
  local OUT="$CHATS/chat-$ts"
  mkdir -p "$OUT"
  command -v openshell >/dev/null 2>&1 && openshell forward start --background 8642 team-lead >/dev/null 2>&1
  local gtok; gtok=$(nemoclaw team-lead gateway-token --quiet 2>/dev/null)
  if [ -z "$gtok" ]; then echo "拿不到 team-lead 的 gateway token — 確認 team-lead 沙箱已啟動" >&2; return 1; fi

  echo "跟 team-lead 直接對話(繞過 Telegram,走同一條 Hermes API)。每個 case 一個檔案存進 $OUT/"
  echo "輸入 exit 或 quit 結束。"
  local n=0
  while true; do
    n=$((n+1))
    printf '\n[case %02d] 你說: ' "$n"
    IFS= read -r line || break
    if [ "$line" = "exit" ] || [ "$line" = "quit" ]; then n=$((n-1)); break; fi
    [ -z "$line" ] && { n=$((n-1)); continue; }
    local t0 t1 resp content
    t0=$(date '+%Y-%m-%d %H:%M:%S')
    resp=$(python3 -c '
import sys, json, urllib.request
prompt = sys.argv[1]; token = sys.argv[2]
body = json.dumps({"model": "nemotron-super", "stream": False, "max_tokens": 800,
                   "messages": [{"role": "user", "content": prompt}]}).encode()
req = urllib.request.Request("http://127.0.0.1:8642/v1/chat/completions", data=body,
                             headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "content": d["choices"][0]["message"].get("content") or ""}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
' "$line" "$gtok" 2>/dev/null)
    t1=$(date '+%Y-%m-%d %H:%M:%S')
    content=$(printf '%s' "$resp" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("content") if d.get("ok") else ("[錯誤] " + d.get("error","")))
except Exception:
    print("[解析失敗]")' 2>/dev/null)
    echo "[case $(printf '%02d' "$n")] team-lead: $content"
    python3 -c '
import sys, json
case = {"case": int(sys.argv[1]), "ts_start": sys.argv[2], "ts_end": sys.argv[3],
        "prompt": sys.argv[4], "response": sys.argv[5]}
json.dump(case, open(sys.argv[6], "w"), ensure_ascii=False, indent=2)
' "$n" "$t0" "$t1" "$line" "$content" "$OUT/$(printf '%02d' "$n").json"
  done
  echo
  echo "對話紀錄已存:$OUT/(共 $((n)) 筆)"
}

case "${1:-}" in
  gui-test) gui_test ;;
  chat) chat ;;
  *) echo "用法:$0 gui-test | chat" >&2; exit 2 ;;
esac
