#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# rotate-bridge-token.sh — 輪替跨 agent bridge token(P1/B7)。
# 重生 token → 用新 token 重啟兩個 :9099 端點(env)→ 重渲染 Hermes 委派 SKILL → 重啟 dashboard。
# 舊 token 立即失效;policy(openclaw_bridge)用 IP 不含 token,故不需重渲染。
# 用法:bash scripts/rotate-bridge-token.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT; cd "$DIR"; :
BRIDGE="$BRIDGE_DIR"; TOKEN_FILE="$BRIDGE/.bridge-token"
ok(){ printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad(){ printf '  \033[31m✗\033[0m %s\n' "$*"; }
ocip(){ docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(docker ps --format '{{.Names}}'|grep -m1 "$1")" 2>/dev/null; }

# 1) 備份 + 重生(0600)
cp "$TOKEN_FILE" "$TOKEN_FILE.prev" 2>/dev/null || true
NEW=$(openssl rand -hex 16 2>/dev/null || head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '%s' "$NEW" > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"
ok "新 token 已產生(舊的備份於 .bridge-token.prev)"

# 2) 用新 token 重啟兩端點
for entry in "my-assistant:A" "openclaw-2:B"; do
  frag=${entry%%:*}; zone=${entry##*:}
  ct=$(docker ps --format '{{.Names}}'|grep -m1 "$frag"); [ -z "$ct" ] && { bad "$frag 容器不在,略過"; continue; }
  docker exec -u 0 "$ct" sh -c 'pkill -f openclaw-fix-endpoint; true' >/dev/null 2>&1; sleep 1
  docker exec -d -u 0 -e BRIDGE_TOKEN="$NEW" -e BRIDGE_ZONE="$zone" "$ct" sh -c 'cd /tmp && python3 /usr/local/bin/openclaw-fix-endpoint.py >>/tmp/openclaw-fix-endpoint.log 2>&1'
  sleep 2
  c=$(docker exec "$ct" sh -c "curl -s -m4 -o /dev/null -w '%{http_code}' -H 'X-Bridge-Token: $NEW' http://127.0.0.1:9099/health" 2>/dev/null)
  c0=$(docker exec "$ct" sh -c "curl -s -m4 -o /dev/null -w '%{http_code}' http://127.0.0.1:9099/monitor" 2>/dev/null)
  [ "$c" = 200 ] && [ "$c0" = 403 ] && ok "$frag 端點已換新 token(zone $zone;無 token=403)" || bad "$frag 端點異常(health=$c noauth=$c0)"
done

# 3) 重渲染 Hermes 委派 SKILL(IP + 新 token)
CT_H=$(resolve_ct hermes-demo); OCIP=$(ocip my-assistant); OC2IP=$(ocip openclaw-2)
if [ -n "$CT_H" ] && [ -f "$SKILLS_DIR/hermes/it-delegate-openclaw/SKILL.md" ]; then
  SK=/sandbox/.hermes/skills/devops/it-delegate-openclaw/SKILL.md
  sed -e "s/172\.18\.0\.2/${OCIP:-172.18.0.2}/g" -e "s/172\.18\.0\.4/${OC2IP:-172.18.0.4}/g" -e "s/BRIDGETOKEN/$NEW/g" \
    "$SKILLS_DIR/hermes/it-delegate-openclaw/SKILL.md" > /tmp/it-del-rot.md
  docker cp /tmp/it-del-rot.md "$CT_H:$SK" >/dev/null 2>&1 \
    && docker exec -u 0 "$CT_H" sh -c "chown 998:998 $SK" >/dev/null 2>&1 \
    && ok "Hermes 委派 SKILL 已換新 token" || bad "Hermes SKILL 渲染失敗"
  rm -f /tmp/it-del-rot.md
else
  bad "找不到 Hermes 容器或 SKILL 範本,跳過(委派功能可能需手動補)"
fi

# 4) 重啟 dashboard(啟動時讀新 .bridge-token)
fuser -k 8899/tcp 2>/dev/null; sleep 2
setsid python3 "$BRIDGE/agent-dashboard.py" >/tmp/agent-dashboard.log 2>&1 < /dev/null & disown 2>/dev/null
sleep 8
c=$(curl -s -m4 -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/login)
[ "$c" = 200 ] && ok "dashboard 已重啟(用新 token)" || bad "dashboard 異常($c)"
echo "  完成。建議排程定期輪替(cron),demo 中如有委派請以新 token 重試。"
