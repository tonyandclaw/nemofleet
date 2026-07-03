#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# boot-stack.sh — WSL 重開機後一鍵拉起整個 stack(Token_Hunter 除外,那是獨立 app)。
# 依 2026-06-07 實測復原順序(memory: reference_nemoclaw_reboot_recovery):
#   1. host openshell gateway 必須在 :18080(recover 預設起 8080 → 容器永遠連不上)
#   2. worker-a(worker)容器會自癒,recover 只補 UI :18789 forward
#   3. team-lead 不自癒,且 gateway 沒起時跑 recover 會 pkill+拒絕重啟(#2478 反殺)
#      → 必須手動在「巢狀 netns」+ SSL_CERT_FILE 下跑 nemoclaw-start,health 200 後才能 recover
# 冪等:已健康的步驟自動跳過,可重複執行。
set -uo pipefail
cd "$(dirname "$0")/.."
:

LOG=/tmp/boot-stack.$$.log
GW_PORT=18080
MAIL_DIR="$NEMOFLEET_ROOT/services/mail"
# Real SMTP/IMAP: the team-lead's email adapter reaches the real mail server over
# governed OpenShell egress (allow the SMTP/IMAP host in a mail egress preset).
# Outbound notifications from the dashboard go host-side via services/mail/send.py
# using SMTP_* from .env. The gateway trusts the standard MITM CA bundle — no
# demo-CA merge and no in-sandbox socat bridges (only needed for the old mock mail server).
CA_BUNDLE=/etc/openshell-tls/ca-bundle.pem
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
step() { printf '\033[1m[%s]\033[0m %s\n' "$1" "$2"; }
die()  { bad "$1"; echo "  log: $LOG"; tail -5 "$LOG" 2>/dev/null | sed 's/^/  | /'; exit 1; }

port_up()      { ss -tln 2>/dev/null | grep -q ":$1 "; }
hermes_host()  { [ "$(curl -so /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8642/health 2>/dev/null)" = 200 ]; }

# hermes 容器內、巢狀 netns 裡的 health(recover 的 probe 看的就是這個)
hermes_in_ns() {
  local ns="$1"
  [ "$(docker exec -u 0 "$CT_LEAD" ip netns exec "$ns" \
        curl -so /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8642/health 2>/dev/null)" = 200 ]
}

# 找 agent 的巢狀 netns:sandbox user 的 `sleep infinity` 的 ns inode 對 /var/run/netns/*
find_agent_ns() {
  docker exec -u 0 "$CT_LEAD" sh -c '
    pid=$(pgrep -f "^sleep infinity$" | head -1); [ -z "$pid" ] && exit 1
    want=$(stat -Lc %i /proc/$pid/ns/net)
    for f in /var/run/netns/*; do
      [ "$(stat -Lc %i "$f" 2>/dev/null)" = "$want" ] && { basename "$f"; exit 0; }
    done; exit 1'
}

BRIDGE="$BRIDGE_DIR"
TOKEN_FILE="$BRIDGE/.bridge-token"
endpoint_up() { docker exec "$CT_WA" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200; }
endpoint_health() { docker exec "$CT_WA" sh -c 'curl -s -m3 http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null; }
oc_ip() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CT_WA" 2>/dev/null; }
oc2_ip() { local ct; ct=$(docker ps --format '{{.Names}}' | grep -m1 worker-b || true); [ -n "$ct" ] && docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$ct" 2>/dev/null; }
# 部署單台 worker zone 端點(冪等):$1=容器名 $2=zone(A/B)。health 對得上 zone+markers 才算當前版,否則重部署。
deploy_oc_endpoint() {
  local ct="$1" zone="$2" h
  h=$(docker exec "$ct" sh -c 'curl -s -m3 http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null)
  if echo "$h" | grep -q "\"zone\": \"$zone\"" && echo "$h" | grep -q '"design": true' && echo "$h" | grep -q '"source": true' && echo "$h" | grep -q '"cert": true' && echo "$h" | grep -q '"managed":'; then
    ok "worker 端點 :9099 已當前版(zone $zone @ ${ct##*openshell-})"
  else
    docker cp "$BRIDGE/worker-itops.py" "$ct:/usr/local/bin/worker-itops.py" >>"$LOG" 2>&1
    docker cp "$BRIDGE/ebg19p.py" "$ct:/usr/local/bin/ebg19p.py" >>"$LOG" 2>&1   # shared device client (imported by worker-itops)
    docker exec -u 0 "$ct" sh -c 'pkill -f worker-itops; true' >>"$LOG" 2>&1; sleep 1
    local NVDK=""; [ -s "$BRIDGE/.nvd-api-key" ] && NVDK="$(tr -d ' \n\r' < "$BRIDGE/.nvd-api-key")"
    # EBG19P 設定 remediation cred:僅注入運維節點 A(A 管 ebg19p);格式 ip|user|pass
    local EBGC=""; [ "$zone" = "A" ] && [ -s "$HOME/.config/nemoclaw/ebg19p.cred" ] && EBGC="$(tr -d '\n\r' < "$HOME/.config/nemoclaw/ebg19p.cred")"
    # nuclei 目標:僅 zone B 注入裝置 IP(只給 target,不含 cred;nuclei 打 HTTP 表面)
    local EBGT=""; [ "$zone" = "B" ] && [ -s "$HOME/.config/nemoclaw/ebg19p.cred" ] && EBGT="$(cut -d'|' -f1 "$HOME/.config/nemoclaw/ebg19p.cred" 2>/dev/null | tr -d ' \n\r')"
    docker exec -d -u 0 -e BRIDGE_TOKEN="$TOKEN" -e BRIDGE_ZONE="$zone" -e NVD_API_KEY="$NVDK" -e EBG19P_CRED="$EBGC" -e EBG19P_TARGET="$EBGT" -e KNOWLEDGE_DIR=/usr/local/share/nemofleet-knowledge "$ct" sh -c 'cd /tmp && python3 /usr/local/bin/worker-itops.py >>/tmp/worker-itops.log 2>&1'
    sleep 2
    docker exec "$ct" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200 \
      && ok "worker 端點 :9099 已部署(zone $zone @ ${ct##*openshell-})" || bad "端點未起($ct;cat /tmp/worker-itops.log)"
  fi
}
# 跨 agent 通道:worker 入站修復端點 + scoped worker_bridge policy(讓 Telegram→Hermes 委派→worker 真修)。
# IP 與 token 每次 boot 動態渲染(容器 rebuild 換 IP 不再靜默斷鏈;端點有最小認證)。
ensure_xagent() {
  [ -f "$BRIDGE/worker-itops.py" ] && [ -n "$CT_WA" ] || return 0
  step "x-agent" "worker 修復端點 + worker_bridge policy(IP/token 動態渲染)"
  [ -s "$TOKEN_FILE" ] || { (openssl rand -hex 16 2>/dev/null || head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n') > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"; }
  local TOKEN OCIP H
  TOKEN=$(cat "$TOKEN_FILE"); OCIP=$(oc_ip)
  [ -n "$OCIP" ] || { bad "拿不到 worker-a 容器 IP"; return 1; }
  # 兩節點端點:節點 A=worker-a(zone A 無線線)、節點 B=worker-b(zone B 基礎設施線),各帶 BRIDGE_ZONE
  deploy_oc_endpoint "$CT_WA" A
  # worker-a 的 EBG19P 操作知識庫
  [ -f "$NEMOFLEET_ROOT/docs/ebg19p-operations.md" ] && docker cp "$NEMOFLEET_ROOT/docs/ebg19p-operations.md" "$CT_WA:/sandbox/.hermes/workspace/it-task/ebg19p-operations.md" >>"$LOG" 2>&1 \
    && docker exec -u 0 "$CT_WA" sh -c 'chown 998:998 /sandbox/.hermes/workspace/it-task/ebg19p-operations.md' >>"$LOG" 2>&1
  local CT_O2 OC2IP=""
  CT_O2=$(docker ps --format '{{.Names}}' | grep -m1 worker-b || true)
  [ -n "$CT_O2" ] && { OC2IP=$(oc2_ip); deploy_oc_endpoint "$CT_O2" B; }
  # worker-b 自主抽 SBOM/SAST/上游 advisory 需經受治理 egress 連 github(scoped allow,非全開)。重建後重套。
  local ALLOW_GH="$(dirname "$BRIDGE")/scripts/worker-b-allow-github.sh"
  [ -n "$CT_O2" ] && [ -x "$ALLOW_GH" ] && \
    { bash "$ALLOW_GH" >>"$LOG" 2>&1 && ok "worker-b github allow 已套用(治理 egress)" || bad "github allow 套用失敗(看 $LOG)"; }
  # worker-b nuclei 主動掃描:允許連 EBG19P 裝置 + nuclei binary(scoped)。重建後重套。
  local ALLOW_DEV="$(dirname "$BRIDGE")/scripts/worker-b-allow-device.sh"
  [ -n "$CT_O2" ] && [ -x "$ALLOW_DEV" ] && \
    { bash "$ALLOW_DEV" >>"$LOG" 2>&1 && ok "worker-b nuclei egress 已套用(裝置 + nuclei binary)" || bad "nuclei egress 套用失敗(看 $LOG)"; }
  # policy:渲染兩節點 IP + /32 收斂(節點 A + 節點 B);兩個 /32 都在才算當前版(同名 preset 升級替換)
  if [ -f "$CONFIG_DIR/presets/worker-bridge-preset.yaml" ]; then
    local P; P=$(openshell policy get team-lead --full 2>/dev/null)
    if echo "$P" | grep -q "$OCIP/32" && { [ -z "$OC2IP" ] || echo "$P" | grep -q "$OC2IP/32"; }; then
      ok "worker_bridge policy 已在($OCIP/32${OC2IP:+ + $OC2IP/32})"
    else
      sed -e "s/172\.18\.0\.2/$OCIP/g" -e "s/172\.18\.0\.4/${OC2IP:-172.18.0.4}/g" \
          -e "s#172\.16\.0\.0/12#$OCIP/32#g" -e "s#172\.17\.0\.0/12#${OC2IP:-172.18.0.4}/32#g" \
        "$CONFIG_DIR/presets/worker-bridge-preset.yaml" > /tmp/worker-bridge-rendered.yaml
      nemoclaw team-lead policy-add --from-file /tmp/worker-bridge-rendered.yaml --yes >>"$LOG" 2>&1 \
        && ok "worker_bridge policy 已套用($OCIP/32${OC2IP:+ + $OC2IP/32})" || bad "policy-add 失敗(看 $LOG)"
    fi
  fi
  # Hermes 端 SKILL:渲染 IP+token,內容變了才重裝(docker cp + chown 998)
  if [ -n "$CT_LEAD" ] && [ -f "$SKILLS_DIR/hermes/it-delegate-worker/SKILL.md" ]; then
    local SK=/sandbox/.hermes/skills/devops/it-delegate-worker/SKILL.md
    sed -e "s/172\.18\.0\.2/$OCIP/g" -e "s/172\.18\.0\.4/${OC2IP:-172.18.0.4}/g" -e "s/BRIDGETOKEN/$TOKEN/g" \
      "$SKILLS_DIR/hermes/it-delegate-worker/SKILL.md" > /tmp/it-delegate-rendered.md
    if docker exec "$CT_LEAD" sh -c "cat $SK 2>/dev/null" | cmp -s - /tmp/it-delegate-rendered.md; then
      ok "it-delegate-worker SKILL 已是當前 IP/token"
    else
      docker exec -u 0 "$CT_LEAD" sh -c "mkdir -p $(dirname $SK)" >>"$LOG" 2>&1
      docker cp /tmp/it-delegate-rendered.md "$CT_LEAD:$SK" >>"$LOG" 2>&1
      docker exec -u 0 "$CT_LEAD" sh -c "chown -R 998:998 $(dirname $SK); chmod 644 $SK" >>"$LOG" 2>&1 \
        && ok "it-delegate-worker SKILL 已渲染部署(IP/token)" || bad "SKILL 部署失敗(看 $LOG)"
    fi
    rm -f /tmp/it-delegate-rendered.md
  fi
  ensure_jira "$OCIP"
}

# 受治理的 Jira egress:真實 Jira(JIRA_URL,見 .env)+ worker jira egress policy
# → worker「修不了/需人審→開單」會在 OPA log 留 ALLOWED <jira-host> [policy:jira]
ensure_jira() {
  if [ -z "${JIRA_URL:-}" ]; then
    ok "未設 JIRA_URL(見 .env)→ 略過 Jira egress(升級改只在儀表板提醒)"; return 0
  fi
  curl -s -m4 -o /dev/null -w '%{http_code}' "$JIRA_URL" 2>/dev/null | grep -qE '^[234]' \
    && ok "真實 Jira 可達($JIRA_URL)" || bad "Jira 不可達($JIRA_URL;檢查 .env/連線,非致命)"
  if [ -f "$CONFIG_DIR/presets/worker-jira-preset.yaml" ]; then
    # 從 JIRA_URL 取出 host,渲染進 preset 的 __JIRA_HOST__(egress policy 需具體 host)
    local JHOST; JHOST=$(printf '%s' "$JIRA_URL" | sed -E 's#^https?://##; s#/.*$##')
    if openshell policy get worker-a --full 2>/dev/null | grep -q "host: $JHOST"; then
      ok "jira egress policy(worker → $JHOST)已在"
    else
      sed "s/__JIRA_HOST__/$JHOST/g" "$CONFIG_DIR/presets/worker-jira-preset.yaml" > /tmp/worker-jira-rendered.yaml
      nemoclaw worker-a policy-add --from-file /tmp/worker-jira-rendered.yaml --yes >>"$LOG" 2>&1 \
        && ok "jira egress policy 已套用(worker → $JHOST)" || bad "jira policy-add 失敗(看 $LOG)"
    fi
  fi
}

# Agent Status Dashboard(host web :8899;唯讀彙整 stack 狀態,非致命)
ensure_ebg_stream() {
  [ -f scripts/ebg19p-stream.sh ] || return 0
  pgrep -f "scripts/ebg19p-stream.sh" >/dev/null 2>&1 && { ok "EBG19P 即時串流已在跑"; return 0; }
  local ip; ip="$(cut -d'|' -f1 "$HOME/.config/nemoclaw/ebg19p.cred" 2>/dev/null)"
  if [ -n "$ip" ] && curl -s -m3 -o /dev/null "http://$ip/" 2>/dev/null; then
    setsid bash scripts/ebg19p-stream.sh >/tmp/ebg19p-stream.log 2>&1 </dev/null &
    ok "EBG19P 即時串流已啟動(每10s syslog/health)"
  else
    ok "EBG19P 不可達 → 略過串流(cron 仍每5分同步)"
  fi
}
ensure_proactive() {  # team-lead 主動巡邏 loop(積極 agent:主動叫 worker 掃 + 主動回報)
  [ -f scripts/teamlead-proactive.sh ] || return 0
  pgrep -f "scripts/teamlead-proactive.sh" >/dev/null 2>&1 && { ok "team-lead 主動巡邏已在跑"; return 0; }
  setsid bash scripts/teamlead-proactive.sh >/tmp/teamlead-proactive.log 2>&1 </dev/null &
  ok "team-lead 主動巡邏已啟動(依 patrol_interval_sec 巡邏 + digest)"
}
dashboard_up() { curl -sk -m3 -o /dev/null -w '%{http_code}' "https://127.0.0.1:$DASH_PORT/login" 2>/dev/null | grep -q 200 || curl -s -m3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$DASH_PORT/login" 2>/dev/null | grep -q 200; }
ensure_dashboard() {
  [ -f "$BRIDGE/agent-dashboard.py" ] || return 0
  if dashboard_up; then ok "Agent Dashboard :$DASH_PORT 已在跑"; else
    pkill -f "$BRIDGE_DIR/agent-dashboard.py" >/dev/null 2>&1
    # 用「目前 IP」重簽 CA 憑證(WiFi DHCP 重開機常變;重用既有 CA → 裝置不必重裝根憑證)
    [ -f scripts/gen-dash-ca.sh ] && { bash scripts/gen-dash-ca.sh >>"$LOG" 2>&1 && ok "儀表板 TLS 憑證已對齊目前 IP" || echo "  ⚠ 憑證重簽略過(openssl?)"; }
    # 對網路開放 + TLS(LAN 存取;憑證見 $BRIDGE_DIR/dash-*.pem,IP 白名單在設定頁控管)
    DASH_BIND=0.0.0.0 DASH_TLS=1 DASHBOARD_PORT="$DASH_PORT" DASH_TRUST_XFF="${DASH_TRUST_XFF:-}" \
      setsid python3 "$BRIDGE/agent-dashboard.py" >/tmp/agent-dashboard.log 2>&1 < /dev/null &
    for i in $(seq 8); do dashboard_up && break; sleep 1; done
    dashboard_up && ok "Agent Dashboard :$DASH_PORT 已啟動(https · bind 0.0.0.0)" || bad "Dashboard 未起(cat /tmp/agent-dashboard.log)"
  fi
}

echo "== boot-stack $(date '+%F %H:%M %Z') =="

# ── 0. 全綠就提前收工(仍確保跨 agent 端點/policy 在位)──────────────
if port_up $GW_PORT && port_up 18789 && hermes_host; then
  ok "核心已全部在線(gateway :$GW_PORT / worker UI :18789 / hermes API :8642)"
  ensure_xagent
  ensure_dashboard
  ensure_ebg_stream
  ensure_proactive
  exit 0
fi

# ── 1. host gateway :18080 + worker-a(自癒 + UI forward)─────
step 1/4 "openshell gateway :$GW_PORT + worker-a recover"
require_ct CT_WA worker-a || die "worker-a 容器不存在(docker ps 查無)"
# 不可 pipe recover 的 stdout:它的 ssh -f forward 會 hold pipe 造成假 hang;導檔即可
NEMOCLAW_GATEWAY_PORT=$GW_PORT nemoclaw worker-a recover >"$LOG" 2>&1 \
  || die "worker-a recover 失敗"
port_up $GW_PORT || die "gateway :$GW_PORT 沒起來"
ok "gateway :$GW_PORT"
for i in $(seq 60); do port_up 18789 && break; sleep 2; done
port_up 18789 && ok "worker UI :18789" || die "worker UI :18789 沒起來"

# ── 1b. worker-b(第二台機隊代理,06-13 以 snapshot restore --to 建;非致命—失敗不擋主 stack)──
CT_O2_ANY="$(docker ps -a --format '{{.Names}}' | grep -m1 worker-b || true)"
if [ -n "$CT_O2_ANY" ]; then
  step "1b" "worker-b 第二台機隊代理 recover(UI :18790)"
  docker start "$CT_O2_ANY" >>"$LOG" 2>&1 || true; sleep 3
  if NEMOCLAW_GATEWAY_PORT=$GW_PORT nemoclaw worker-b recover >>"$LOG" 2>&1; then
    for i in $(seq 30); do port_up 18790 && break; sleep 2; done
    port_up 18790 && ok "worker-b UI :18790(第二台機隊)" || bad "worker-b UI :18790 未起(非致命)"
  else
    bad "worker-b recover 失敗(非致命,主 stack 不受影響)"
  fi
fi

# ── 2. 等 hermes 容器穩定(policy fetch 成功後巢狀 netns 才會出現)──
step 2/4 "等 team-lead 容器穩定"
CT_LEAD="$(resolve_ct team-lead)"
require_ct CT_LEAD team-lead || die "team-lead 容器不存在"
NS=""
for i in $(seq 60); do NS="$(find_agent_ns)" && [ -n "$NS" ] && break; sleep 3; done
[ -n "$NS" ] || die "等不到 hermes 巢狀 netns(容器還在 crash-loop?看 docker logs $CT_LEAD)"
ok "agent netns: $NS"

# ── 3. hermes gateway:在巢狀 netns + SSL_CERT_FILE 下手動拉起 ────
step 3/4 "hermes gateway(in-netns)"
CA="$CA_BUNDLE"
if hermes_in_ns "$NS"; then
  ok "hermes 已在 netns 內健康,跳過重啟"
else
  # 清掉跑錯 netns / 殘留的舊進程,避免 pkill 誤殺新進程或 port 衝突
  docker exec -u 0 "$CT_LEAD" sh -c '
    pkill -f "hermes gateway run"; pkill -f "socat TCP-LISTEN:8642"
    pkill -f "tail -n +1 -F /tmp/gateway.log"; rm -f /sandbox/.hermes/gateway.pid; true' >>"$LOG" 2>&1
  sleep 1
  # SSL_CERT_FILE:OpenShell 原生啟動才會注入;漏掉 → Telegram 過 L7 MITM proxy 必掛。
  # 用標準 MITM CA bundle($CA);真實 SMTP/IMAP 走公信 CA,無需額外合併。
  docker exec -d -u 0 "$CT_LEAD" ip netns exec "$NS" su -s /bin/bash -c \
    "HOME=/sandbox SSL_CERT_FILE=$CA /usr/local/bin/nemoclaw-start" sandbox
  for i in $(seq 60); do hermes_in_ns "$NS" && break; sleep 3; done
  hermes_in_ns "$NS" || die "hermes health 等不到 200(docker exec $CT_LEAD cat /tmp/nemoclaw-start.log)"
  ok "hermes gateway 在 netns 內 health 200（CA: $CA）"
fi

# ── 4. hermes host forward(此時 probe 必回 ALREADY_RUNNING,安全)──
step 4/4 "team-lead recover(host :8642 forward)"
if hermes_host; then
  ok "host :8642 已通,跳過"
else
  NEMOCLAW_GATEWAY_PORT=$GW_PORT nemoclaw team-lead recover >>"$LOG" 2>&1 \
    || die "team-lead recover 失敗"
  for i in $(seq 20); do hermes_host && break; sleep 2; done
  if ! hermes_host; then
    # fallback:recover 不一定建 8642 forward;gRPC service forward 直連 netns 內 18642(實測可用)
    nohup openshell forward service --target-port 18642 --local 127.0.0.1:8642 team-lead \
      >>"$LOG" 2>&1 & disown
    for i in $(seq 10); do hermes_host && break; sleep 2; done
  fi
  hermes_host && ok "hermes API http://127.0.0.1:8642/v1" || die "host :8642 還是不通"
fi

# ── 5. 跨 agent 通道:worker 入站修復端點 + scoped policy ──
ensure_xagent
ensure_dashboard
ensure_ebg_stream
ensure_proactive

echo
bash scripts/healthcheck.sh
rm -f "$LOG"
