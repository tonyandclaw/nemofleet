#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# bridge-regress.sh — 跨 agent 委派鏈一鍵回歸(錄影日早上跑這支)。
# 從 Hermes 沙箱「巢狀 netns」經 L7 proxy POST /fix —— 與 Hermes 實際委派走完全相同的路徑
# (CONNECT 10.200.0.1:3128 → worker_bridge policy → X-Bridge-Token → worker :9099),
# 然後等修復完成、驗收 marker、印出 OPA ALLOWED 治理 log。
# 成本:1 個 推理 turn(worker agent 實修)。
# 用法:bridge-regress.sh [fw|subnet|bandwidth|dhcp|drift]    預設 drift
set -uo pipefail
DIR=$NEMOFLEET_ROOT
:
BUG="${1:-drift}"
TOKEN_FILE="$BRIDGE_DIR/.bridge-token"
ok(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

[ -n "$CT_LEAD" ] && [ -n "$CT_WA" ] || bad "容器未找到(先 bash scripts/boot-stack.sh)"
[ -s "$TOKEN_FILE" ] || bad "缺 $TOKEN_FILE(先 bash scripts/boot-stack.sh 產生)"
TOKEN=$(cat "$TOKEN_FILE")
OCIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CT_WA")
[ -n "$OCIP" ] || bad "拿不到 worker-a IP"

echo "== bridge-regress $(date '+%F %H:%M %Z')  bug=$BUG  endpoint=$OCIP:9099 =="

# live netns(寫死必踩 stale-netns EINVAL)
NS="$(docker exec -u 0 "$CT_LEAD" sh -c 'pid=$(pgrep -f "^sleep infinity$"|head -1); [ -z "$pid" ] && exit 1; want=$(stat -Lc %i /proc/$pid/ns/net); for f in /var/run/netns/*; do [ "$(stat -Lc %i "$f" 2>/dev/null)" = "$want" ] && { basename "$f"; exit 0; }; done; exit 1')"
[ -n "$NS" ] || bad "找不到 hermes live netns(先 bash scripts/boot-stack.sh)"
ok "hermes netns: $NS"

last(){ docker exec "$CT_WA" sh -c "curl -s -m5 -H 'X-Bridge-Token: $TOKEN' http://127.0.0.1:9099/last" 2>/dev/null; }
PREV_TS=$(last | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("ts",""))
except Exception: print("")')

# 1) 從 Hermes netns 經 L7 proxy 委派(與 Hermes 同路徑、同 binary 白名單)
ACK=$(docker exec -u 0 "$CT_LEAD" ip netns exec "$NS" su -s /bin/bash -c \
  "curl -s -m10 -x http://10.200.0.1:3128 -X POST http://$OCIP:9099/fix \
   -H 'Content-Type: application/json' -H 'X-Bridge-Token: $TOKEN' -d '{\"bug\":\"$BUG\"}'" sandbox 2>/dev/null)
echo "$ACK" | grep -q '"accepted": true' || bad "委派未被接受:$ACK"
ok "POST /fix 已接受(經 proxy+policy+token):$(echo "$ACK" | head -c 100)…"

# 2) 等修復完成(drift 最長 ~6 分鐘;其餘 ~2 分鐘)
DEADLINE=$(( $(date +%s) + 420 ))
RES=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  RES=$(last)
  TS=$(echo "$RES" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("ts",""))
except Exception: print("")')
  [ -n "$TS" ] && [ "$TS" != "$PREV_TS" ] && break
  sleep 10
done
TS=$(echo "$RES" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("ts",""))
except Exception: print("")')
{ [ -n "$TS" ] && [ "$TS" != "$PREV_TS" ]; } || bad "等不到新修復結果(看 docker exec $CT_WA cat /tmp/worker-itops.log)"

# 3) 驗收
echo "$RES" | python3 -c '
import json,sys
r = json.load(sys.stdin)
print("  bug=%s ok=%s" % (r.get("bug"), r.get("ok")))
print("  before:", r.get("before"))
print("  after: ", r.get("after"))'
echo "$RES" | grep -q '"ok": true' && ok "修復驗收 PASS" || bad "修復未通過驗收"

# 4) 治理鐵證(OPA ALLOWED log)
echo "  OPA 治理 log:"
docker logs --since 10m "$CT_LEAD" 2>&1 | grep -a "$OCIP:9099" | tail -2 | sed 's/^/    /' || true
echo "[bridge-regress] ✅ 委派鏈端到端 PASS(bug=$BUG)"
