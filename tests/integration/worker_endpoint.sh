#!/usr/bin/env bash
# tests/integration/worker_endpoint.sh — start the worker IT-ops endpoint standalone (plain python3,
# no docker / NIM / device) and verify the A2A adapter, the shared-knowledge endpoint, and the nuclei
# wiring + graceful degradation. CI-able: needs only python3 + curl. Fully isolated (temp WORKER_WD).
set -uo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0
ok(){ echo "  PASS: $*"; PASS=$((PASS + 1)); }
bad(){ echo "  FAIL: $*"; FAIL=$((FAIL + 1)); }
TOK=citok; WD=$(mktemp -d); DPID=""
cleanup(){ [ -n "$DPID" ] && { kill "$DPID" 2>/dev/null; wait "$DPID" 2>/dev/null; }; rm -rf "$WD"; }
trap cleanup EXIT
start(){ # $1=port $2=zone
  BRIDGE_TOKEN=$TOK ITOPS_PORT=$1 BRIDGE_ZONE=$2 WORKER_WD="$WD/$2" KNOWLEDGE_DIR="$R/knowledge" EBG19P_TARGET=10.0.0.1 \
    python3 "$R/services/bridge/worker-itops.py" >"/tmp/itops-ci-$2.log" 2>&1 &
  DPID=$!; for _ in $(seq 25); do curl -s -m1 -o /dev/null "http://127.0.0.1:$1/health" && break; sleep 0.4; done
}
g(){ curl -s -H "X-Bridge-Token: $TOK" "http://127.0.0.1:$1$2"; }
stop(){ kill "$DPID" 2>/dev/null; wait "$DPID" 2>/dev/null; DPID=""; }

# ---- zone A: A2A discovery + delegation + shared knowledge ----
PA=19191; start $PA A
CARD=$(g $PA /.well-known/agent-card.json)
echo "$CARD" | grep -q '"name": *"nemofleet-worker-a"' && ok "A2A Agent Card served (zone A)" || bad "card: ${CARD:0:100}"
echo "$CARD" | grep -q '"id": *"monitor"' && echo "$CARD" | grep -q '"id": *"knowledge"' && ok "zone-A skills + knowledge advertised" || bad "skills wrong"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PA/a2a" -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{}}')
[ "$code" = 403 ] && ok "/a2a requires token (403)" || bad "no-auth got $code"
T=$(curl -s -X POST "http://127.0.0.1:$PA/a2a" -H "X-Bridge-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"2","method":"message/send","params":{"message":{"parts":[{"kind":"text","text":"monitor"}],"metadata":{"skill":"monitor"}}}}')
echo "$T" | grep -q '"state": *"completed"' && ok "A2A message/send monitor -> completed task" || bad "task: ${T:0:120}"
K=$(g $PA /knowledge)
echo "$K" | grep -q '"version"' && echo "$K" | grep -q 'wps.enabled' && ok "GET /knowledge serves shared baseline + security-keys" || bad "knowledge: ${K:0:120}"
stop

# ---- zone B: nuclei wiring + graceful degradation (no nuclei binary in CI) ----
PB=19192; start $PB B
H=$(g $PB /health); echo "$H" | grep -q '"nuclei"' && ok "zone B advertises nuclei cap" || bad "caps: ${H:0:100}"
echo "$(g $PB /.well-known/agent-card.json)" | grep -q '"id": *"nuclei-scan"' && ok "Agent Card: nuclei-scan (zone B only)" || bad "no nuclei skill"
curl -s -X POST -H "X-Bridge-Token: $TOK" "http://127.0.0.1:$PB/nuclei-scan" | grep -q '"accepted": true' && ok "POST /nuclei-scan accepted (async)" || bad "trigger"
N=""; for _ in $(seq 12); do N=$(g $PB /nuclei); echo "$N" | grep -q '"available"' && break; sleep 0.3; done
echo "$N" | grep -q '"available": false' && ok "GET /nuclei degrades gracefully (no binary -> clear note)" || bad "nuclei: ${N:0:120}"
# every authed route is still wired (no-token -> 403, before any scan runs; guards refactors/modularization)
WIRED=1
for ep in /jira /assets /device-log /log-analysis /traffic /cve /monitor /source-cve /cert-scan /settings /recipients /last /knowledge /nuclei /flow /backup /firmware /skills /rollbacks; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PB$ep")
  [ "$code" = 403 ] || { WIRED=0; bad "route $ep not wired (got $code)"; }
done
[ "$WIRED" = 1 ] && ok "all 19 authed routes wired (no-token -> 403)"
stop

# ---- zone C: worker-c governance (review gates + lifecycle degrade) ----
PC=19193; start $PC C
echo "$(g $PC /.well-known/agent-card.json)" | grep -q '"id": *"review"' && ok "Agent Card advertises governance skills (zone C: review/backup/firmware/rollback)" || bad "no zone-C skills"
RV=$(curl -s -X POST "http://127.0.0.1:$PC/review" -H "X-Bridge-Token: $TOK" -H 'Content-Type: application/json' -d '{"kind":"remediation","subject":{"bug":"ebg-wps","ok":true,"after":{"wps.enabled":"true"}}}')
echo "$RV" | grep -q '"verdict": *"reject"' && ok "POST /review REJECTs a deviating remediation" || bad "review reject: ${RV:0:120}"
RV2=$(curl -s -X POST "http://127.0.0.1:$PC/review" -H "X-Bridge-Token: $TOK" -H 'Content-Type: application/json' -d '{"kind":"remediation","subject":{"bug":"ebg-wps","ok":true,"after":{"wps.enabled":"false"}}}')
echo "$RV2" | grep -q '"verdict": *"approve"' && ok "POST /review APPROVEs a compliant remediation" || bad "review approve: ${RV2:0:120}"
echo "$(curl -s -X POST -H "X-Bridge-Token: $TOK" "http://127.0.0.1:$PC/backup")" | grep -q '"available": false' && ok "POST /backup degrades gracefully (no device cred)" || bad "backup degrade"
SR=$(curl -s -X POST "http://127.0.0.1:$PC/skill-review" -H "X-Bridge-Token: $TOK" -H 'Content-Type: application/json' -d '{"op":"insert","text":"# no frontmatter, just a body long enough to pass the length gate here"}')
echo "$SR" | grep -q '"verdict": *"reject"' && ok "POST /skill-review (SkillOS curator) rejects a malformed skill" || bad "skill-review: ${SR:0:120}"
stop

echo "== worker_endpoint: $PASS pass, $FAIL fail =="
exit "$FAIL"
