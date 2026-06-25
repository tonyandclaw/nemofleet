#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# boot-stack.sh — WSL 重開機後一鍵拉起整個 stack(Token_Hunter 除外,那是獨立 app)。
# 依 2026-06-07 實測復原順序(memory: reference_nemoclaw_reboot_recovery):
#   1. host openshell gateway 必須在 :18080(recover 預設起 8080 → 容器永遠連不上)
#   2. my-assistant(OpenClaw)容器會自癒,recover 只補 UI :18789 forward
#   3. hermes-demo 不自癒,且 gateway 沒起時跑 recover 會 pkill+拒絕重啟(#2478 反殺)
#      → 必須手動在「巢狀 netns」+ SSL_CERT_FILE 下跑 nemoclaw-start,health 200 後才能 recover
# 冪等:已健康的步驟自動跳過,可重複執行。
set -uo pipefail
cd "$(dirname "$0")/.."
:

LOG=/tmp/boot-stack.$$.log
GW_PORT=18080
MAIL_DIR="$NEMOFLEET_ROOT/services/mail"
# email channel demo 是否已配置(up.sh 在 + 沙箱 .env 有 EMAIL_ADDRESS)
mail_configured() { [ -x "$MAIL_DIR/up.sh" ] && docker exec "$CT_H" sh -c 'grep -q "^EMAIL_ADDRESS=" /sandbox/.hermes/.env' 2>/dev/null; }
# 預設 CA bundle(Telegram 的 L7 MITM CA);mail 模式改用合併過 demo CA 的 bundle
ca_bundle() { if mail_configured; then echo /sandbox/.hermes/ca-mail-bundle.pem; else echo /etc/openshell-tls/ca-bundle.pem; fi; }
# 每次 boot 都用「當前」OpenShell MITM CA 重建 ca-mail-bundle = live ca-bundle + demo mail CA。
# MITM CA 會隨容器/openshell 重啟輪替;沿用舊的 bundle 會讓 Telegram(走 L7 MITM)TLS 驗不過,
# gateway 重連 ~20 次後放棄(實測 2026-06-11)。mail 走 demo CA 不受影響,故兩者都要在。
rebuild_mail_ca_bundle() {
  docker exec "$CT_H" test -f /etc/openshell-tls/ca-bundle.pem || return 1
  docker cp "$MAIL_DIR/ca.pem" "$CT_H:/tmp/demo-mail-ca.pem" >>"$LOG" 2>&1 || return 1
  docker exec -u 0 "$CT_H" sh -c '
    b=/sandbox/.hermes/ca-mail-bundle.pem
    [ -f "$b" ] && cp -a "$b" "$b.bak" 2>/dev/null
    cat /etc/openshell-tls/ca-bundle.pem /tmp/demo-mail-ca.pem > "$b"
    chown sandbox:sandbox "$b" 2>/dev/null || true; chmod 644 "$b"'
}

# 沙箱內 CONNECT 橋:imaplib/smtplib 不會講 HTTP proxy,故在巢狀 netns 用 socat
# 把 127.0.0.1:{3993,3587} 經 L7 proxy CONNECT 到 host.openshell.internal(受 greenmail_mail policy 治理)
ensure_bridges() {  # $1 = netns
  local ns="$1" p
  for p in 3993 3587; do
    docker exec -u 0 "$CT_H" ip netns exec "$ns" sh -c "ss -tln 2>/dev/null | grep -q ':$p '" && continue
    docker exec -d -u 0 "$CT_H" ip netns exec "$ns" su -s /bin/bash -c \
      "socat TCP-LISTEN:$p,bind=127.0.0.1,fork,reuseaddr PROXY:10.200.0.1:host.openshell.internal:$p,proxyport=3128" sandbox
  done
  sleep 1
}
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
step() { printf '\033[1m[%s]\033[0m %s\n' "$1" "$2"; }
die()  { bad "$1"; echo "  log: $LOG"; tail -5 "$LOG" 2>/dev/null | sed 's/^/  | /'; exit 1; }

port_up()      { ss -tln 2>/dev/null | grep -q ":$1 "; }
hermes_host()  { [ "$(curl -so /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8642/health 2>/dev/null)" = 200 ]; }

# hermes 容器內、巢狀 netns 裡的 health(recover 的 probe 看的就是這個)
hermes_in_ns() {
  local ns="$1"
  [ "$(docker exec -u 0 "$CT_H" ip netns exec "$ns" \
        curl -so /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8642/health 2>/dev/null)" = 200 ]
}

# 找 agent 的巢狀 netns:sandbox user 的 `sleep infinity` 的 ns inode 對 /var/run/netns/*
find_agent_ns() {
  docker exec -u 0 "$CT_H" sh -c '
    pid=$(pgrep -f "^sleep infinity$" | head -1); [ -z "$pid" ] && exit 1
    want=$(stat -Lc %i /proc/$pid/ns/net)
    for f in /var/run/netns/*; do
      [ "$(stat -Lc %i "$f" 2>/dev/null)" = "$want" ] && { basename "$f"; exit 0; }
    done; exit 1'
}

BRIDGE="$BRIDGE_DIR"
TOKEN_FILE="$BRIDGE/.bridge-token"
endpoint_up() { docker exec "$CT_O" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200; }
endpoint_health() { docker exec "$CT_O" sh -c 'curl -s -m3 http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null; }
oc_ip() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CT_O" 2>/dev/null; }
oc2_ip() { local ct; ct=$(docker ps --format '{{.Names}}' | grep -m1 openclaw-2 || true); [ -n "$ct" ] && docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$ct" 2>/dev/null; }
# 部署單台 OpenClaw zone 端點(冪等):$1=容器名 $2=zone(A/B)。health 對得上 zone+markers 才算當前版,否則重部署。
deploy_oc_endpoint() {
  local ct="$1" zone="$2" h
  h=$(docker exec "$ct" sh -c 'curl -s -m3 http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null)
  if echo "$h" | grep -q "\"zone\": \"$zone\"" && echo "$h" | grep -q '"design": true' && echo "$h" | grep -q '"source": true' && echo "$h" | grep -q '"cert": true' && echo "$h" | grep -q '"managed":'; then
    ok "OpenClaw 端點 :9099 已當前版(zone $zone @ ${ct##*openshell-})"
  else
    docker cp "$BRIDGE/openclaw-fix-endpoint.py" "$ct:/usr/local/bin/openclaw-fix-endpoint.py" >>"$LOG" 2>&1
    docker exec -u 0 "$ct" sh -c 'pkill -f openclaw-fix-endpoint; true' >>"$LOG" 2>&1; sleep 1
    local NVDK=""; [ -s "$BRIDGE/.nvd-api-key" ] && NVDK="$(tr -d ' \n\r' < "$BRIDGE/.nvd-api-key")"
    # EBG19P 設定 remediation cred:僅注入運維節點 A(A 管 ebg19p);格式 ip|user|pass
    local EBGC=""; [ "$zone" = "A" ] && [ -s "$HOME/.config/nemoclaw/ebg19p.cred" ] && EBGC="$(tr -d '\n\r' < "$HOME/.config/nemoclaw/ebg19p.cred")"
    docker exec -d -u 0 -e BRIDGE_TOKEN="$TOKEN" -e BRIDGE_ZONE="$zone" -e NVD_API_KEY="$NVDK" -e EBG19P_CRED="$EBGC" "$ct" sh -c 'cd /tmp && python3 /usr/local/bin/openclaw-fix-endpoint.py >>/tmp/openclaw-fix-endpoint.log 2>&1'
    sleep 2
    docker exec "$ct" sh -c 'curl -s -m3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9099/health 2>/dev/null' 2>/dev/null | grep -q 200 \
      && ok "OpenClaw 端點 :9099 已部署(zone $zone @ ${ct##*openshell-})" || bad "端點未起($ct;cat /tmp/openclaw-fix-endpoint.log)"
  fi
}
# 跨 agent 通道:OpenClaw 入站修復端點 + scoped openclaw_bridge policy(讓 Telegram→Hermes 委派→OpenClaw 真修)。
# IP 與 token 每次 boot 動態渲染(容器 rebuild 換 IP 不再靜默斷鏈;端點有最小認證)。
ensure_xagent() {
  [ -f "$BRIDGE/openclaw-fix-endpoint.py" ] && [ -n "$CT_O" ] || return 0
  step "x-agent" "OpenClaw 修復端點 + openclaw_bridge policy(IP/token 動態渲染)"
  [ -s "$TOKEN_FILE" ] || { (openssl rand -hex 16 2>/dev/null || head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n') > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"; }
  local TOKEN OCIP H
  TOKEN=$(cat "$TOKEN_FILE"); OCIP=$(oc_ip)
  [ -n "$OCIP" ] || { bad "拿不到 my-assistant 容器 IP"; return 1; }
  # 兩節點端點:節點 A=my-assistant(zone A 無線線)、節點 B=openclaw-2(zone B 基礎設施線),各帶 BRIDGE_ZONE
  deploy_oc_endpoint "$CT_O" A
  # OpenClaw A 的 EBG19P 操作知識庫
  [ -f "$NEMOFLEET_ROOT/docs/ebg19p-operations.md" ] && docker cp "$NEMOFLEET_ROOT/docs/ebg19p-operations.md" "$CT_O:/sandbox/.openclaw/workspace/it-task/ebg19p-operations.md" >>"$LOG" 2>&1 \
    && docker exec -u 0 "$CT_O" sh -c 'chown 998:998 /sandbox/.openclaw/workspace/it-task/ebg19p-operations.md' >>"$LOG" 2>&1
  local CT_O2 OC2IP=""
  CT_O2=$(docker ps --format '{{.Names}}' | grep -m1 openclaw-2 || true)
  [ -n "$CT_O2" ] && { OC2IP=$(oc2_ip); deploy_oc_endpoint "$CT_O2" B; }
  # OpenClaw B 自主抽 SBOM/SAST/上游 advisory 需經受治理 egress 連 github(scoped allow,非全開)。重建後重套。
  local ALLOW_GH="$(dirname "$BRIDGE")/scripts/openclaw-b-allow-github.sh"
  [ -n "$CT_O2" ] && [ -x "$ALLOW_GH" ] && \
    { bash "$ALLOW_GH" >>"$LOG" 2>&1 && ok "OpenClaw B github allow 已套用(治理 egress)" || bad "github allow 套用失敗(看 $LOG)"; }
  # policy:渲染兩節點 IP + /32 收斂(節點 A + 節點 B);兩個 /32 都在才算當前版(同名 preset 升級替換)
  if [ -f "$CONFIG_DIR/presets/openclaw-bridge-preset.yaml" ]; then
    local P; P=$(openshell policy get hermes-demo --full 2>/dev/null)
    if echo "$P" | grep -q "$OCIP/32" && { [ -z "$OC2IP" ] || echo "$P" | grep -q "$OC2IP/32"; }; then
      ok "openclaw_bridge policy 已在($OCIP/32${OC2IP:+ + $OC2IP/32})"
    else
      sed -e "s/172\.18\.0\.2/$OCIP/g" -e "s/172\.18\.0\.4/${OC2IP:-172.18.0.4}/g" \
          -e "s#172\.16\.0\.0/12#$OCIP/32#g" -e "s#172\.17\.0\.0/12#${OC2IP:-172.18.0.4}/32#g" \
        "$CONFIG_DIR/presets/openclaw-bridge-preset.yaml" > /tmp/openclaw-bridge-rendered.yaml
      nemoclaw hermes-demo policy-add --from-file /tmp/openclaw-bridge-rendered.yaml --yes >>"$LOG" 2>&1 \
        && ok "openclaw_bridge policy 已套用($OCIP/32${OC2IP:+ + $OC2IP/32})" || bad "policy-add 失敗(看 $LOG)"
    fi
  fi
  # Hermes 端 SKILL:渲染 IP+token,內容變了才重裝(docker cp + chown 998)
  if [ -n "$CT_H" ] && [ -f "$SKILLS_DIR/hermes/it-delegate-openclaw/SKILL.md" ]; then
    local SK=/sandbox/.hermes/skills/devops/it-delegate-openclaw/SKILL.md
    sed -e "s/172\.18\.0\.2/$OCIP/g" -e "s/172\.18\.0\.4/${OC2IP:-172.18.0.4}/g" -e "s/BRIDGETOKEN/$TOKEN/g" \
      "$SKILLS_DIR/hermes/it-delegate-openclaw/SKILL.md" > /tmp/it-delegate-rendered.md
    if docker exec "$CT_H" sh -c "cat $SK 2>/dev/null" | cmp -s - /tmp/it-delegate-rendered.md; then
      ok "it-delegate-openclaw SKILL 已是當前 IP/token"
    else
      docker exec -u 0 "$CT_H" sh -c "mkdir -p $(dirname $SK)" >>"$LOG" 2>&1
      docker cp /tmp/it-delegate-rendered.md "$CT_H:$SK" >>"$LOG" 2>&1
      docker exec -u 0 "$CT_H" sh -c "chown -R 998:998 $(dirname $SK); chmod 644 $SK" >>"$LOG" 2>&1 \
        && ok "it-delegate-openclaw SKILL 已渲染部署(IP/token)" || bad "SKILL 部署失敗(看 $LOG)"
    fi
    rm -f /tmp/it-delegate-rendered.md
  fi
  ensure_jira "$OCIP"
}

# 受治理的 Jira egress:host 上 mock Jira(:3690)+ OpenClaw jira egress policy
# → OpenClaw「修不了/需人審→開單」會在 OPA log 留 ALLOWED host.openshell.internal:3690 [policy:jira]
jira_mock_up() { curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:3690/health 2>/dev/null | grep -q 200; }
ensure_jira() {
  local OCIP="$1"
  [ -f "$BRIDGE/jira-mock.py" ] || return 0
  if jira_mock_up; then ok "mock Jira :3690 已在跑"; else
    pkill -f "$BRIDGE_DIR/jira-mock.py" >/dev/null 2>&1
    nohup python3 "$BRIDGE/jira-mock.py" >/tmp/jira-mock.log 2>&1 & disown
    for i in $(seq 8); do jira_mock_up && break; sleep 1; done
    jira_mock_up && ok "mock Jira :3690 已啟動(host)" || bad "mock Jira 未起(cat /tmp/jira-mock.log)"
  fi
  if [ -f "$CONFIG_DIR/presets/openclaw-jira-preset.yaml" ]; then
    if openshell policy get my-assistant --full 2>/dev/null | grep -q 'name: jira'; then ok "jira egress policy(OpenClaw)已在"; else
      nemoclaw my-assistant policy-add --from-file "$CONFIG_DIR/presets/openclaw-jira-preset.yaml" --yes >>"$LOG" 2>&1 \
        && ok "jira egress policy 已套用(OpenClaw)" || bad "jira policy-add 失敗(看 $LOG)"
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
dashboard_up() { curl -sk -m3 -o /dev/null -w '%{http_code}' https://127.0.0.1:8899/login 2>/dev/null | grep -q 200 || curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/login 2>/dev/null | grep -q 200; }
ensure_dashboard() {
  [ -f "$BRIDGE/agent-dashboard.py" ] || return 0
  if dashboard_up; then ok "Agent Dashboard :8899 已在跑"; else
    pkill -f "$BRIDGE_DIR/agent-dashboard.py" >/dev/null 2>&1
    # 用「目前 IP」重簽 CA 憑證(WiFi DHCP 重開機常變;重用既有 CA → 裝置不必重裝根憑證)
    [ -f scripts/gen-dash-ca.sh ] && { bash scripts/gen-dash-ca.sh >>"$LOG" 2>&1 && ok "儀表板 TLS 憑證已對齊目前 IP" || echo "  ⚠ 憑證重簽略過(openssl?)"; }
    # 對網路開放 + TLS(LAN 存取;憑證見 $BRIDGE_DIR/dash-*.pem,IP 白名單在設定頁控管)
    DASH_BIND=0.0.0.0 DASH_TLS=1 setsid python3 "$BRIDGE/agent-dashboard.py" >/tmp/agent-dashboard.log 2>&1 < /dev/null &
    for i in $(seq 8); do dashboard_up && break; sleep 1; done
    dashboard_up && ok "Agent Dashboard :8899 已啟動(https · bind 0.0.0.0)" || bad "Dashboard 未起(cat /tmp/agent-dashboard.log)"
  fi
}

echo "== boot-stack $(date '+%F %H:%M %Z') =="

# ── 0. 全綠就提前收工(仍確保跨 agent 端點/policy 在位)──────────────
if port_up $GW_PORT && port_up 18789 && hermes_host; then
  ok "核心已全部在線(gateway :$GW_PORT / openclaw UI :18789 / hermes API :8642)"
  ensure_xagent
  ensure_dashboard
  ensure_ebg_stream
  exit 0
fi

# ── 1. host gateway :18080 + my-assistant(自癒 + UI forward)─────
step 1/4 "openshell gateway :$GW_PORT + my-assistant recover"
require_ct CT_O my-assistant || die "my-assistant 容器不存在(docker ps 查無)"
# 不可 pipe recover 的 stdout:它的 ssh -f forward 會 hold pipe 造成假 hang;導檔即可
NEMOCLAW_GATEWAY_PORT=$GW_PORT nemoclaw my-assistant recover >"$LOG" 2>&1 \
  || die "my-assistant recover 失敗"
port_up $GW_PORT || die "gateway :$GW_PORT 沒起來"
ok "gateway :$GW_PORT"
for i in $(seq 60); do port_up 18789 && break; sleep 2; done
port_up 18789 && ok "openclaw UI :18789" || die "openclaw UI :18789 沒起來"

# ── 1b. openclaw-2(第二台機隊代理,06-13 以 snapshot restore --to 建;非致命—失敗不擋主 stack)──
CT_O2_ANY="$(docker ps -a --format '{{.Names}}' | grep -m1 openclaw-2 || true)"
if [ -n "$CT_O2_ANY" ]; then
  step "1b" "openclaw-2 第二台機隊代理 recover(UI :18790)"
  docker start "$CT_O2_ANY" >>"$LOG" 2>&1 || true; sleep 3
  if NEMOCLAW_GATEWAY_PORT=$GW_PORT nemoclaw openclaw-2 recover >>"$LOG" 2>&1; then
    for i in $(seq 30); do port_up 18790 && break; sleep 2; done
    port_up 18790 && ok "openclaw-2 UI :18790(第二台機隊)" || bad "openclaw-2 UI :18790 未起(非致命)"
  else
    bad "openclaw-2 recover 失敗(非致命,主 stack 不受影響)"
  fi
fi

# ── 2. 等 hermes 容器穩定(policy fetch 成功後巢狀 netns 才會出現)──
step 2/4 "等 hermes-demo 容器穩定"
CT_H="$(resolve_ct hermes-demo)"
require_ct CT_H hermes-demo || die "hermes-demo 容器不存在"
NS=""
for i in $(seq 60); do NS="$(find_agent_ns)" && [ -n "$NS" ] && break; sleep 3; done
[ -n "$NS" ] || die "等不到 hermes 巢狀 netns(容器還在 crash-loop?看 docker logs $CT_H)"
ok "agent netns: $NS"

# ── 2.5 email channel(若已配置):host 零件 + 沙箱內 CONNECT 橋 ──
if mail_configured; then
  step "mail" "email channel bring-up"
  bash "$MAIL_DIR/up.sh" >>"$LOG" 2>&1 && ok "GreenMail + SMTP shim(host)" || bad "mail host bring-up 有問題(看 $LOG)"
  # gateway 用的 CA bundle 必須含「當前」MITM CA,否則 Telegram TLS 驗不過(見 rebuild_mail_ca_bundle)
  rebuild_mail_ca_bundle && ok "ca-mail-bundle 以當前 MITM CA 重建(Telegram+mail 皆驗得過)" \
    || bad "ca-mail-bundle 重建失敗(Telegram 恐 TLS 驗不過,看 $LOG)"
  ensure_bridges "$NS"
  docker exec -u 0 "$CT_H" ip netns exec "$NS" sh -c 'ss -tln 2>/dev/null | grep -qE ":3993 " && ss -tln 2>/dev/null | grep -qE ":3587 "' \
    && ok "沙箱內 CONNECT 橋 3993/3587" || bad "CONNECT 橋未就緒"
fi

# ── 3. hermes gateway:在巢狀 netns + SSL_CERT_FILE 下手動拉起 ────
step 3/4 "hermes gateway(in-netns)"
CA="$(ca_bundle)"
if hermes_in_ns "$NS"; then
  ok "hermes 已在 netns 內健康,跳過重啟"
else
  # 清掉跑錯 netns / 殘留的舊進程,避免 pkill 誤殺新進程或 port 衝突
  docker exec -u 0 "$CT_H" sh -c '
    pkill -f "hermes gateway run"; pkill -f "socat TCP-LISTEN:8642"
    pkill -f "tail -n +1 -F /tmp/gateway.log"; rm -f /sandbox/.hermes/gateway.pid; true' >>"$LOG" 2>&1
  sleep 1
  # SSL_CERT_FILE:OpenShell 原生啟動才會注入;漏掉 → Telegram 過 L7 MITM proxy 必掛。
  # mail 模式用合併 demo CA 的 bundle($CA),IMAPS/STARTTLS 才驗得過。
  docker exec -d -u 0 "$CT_H" ip netns exec "$NS" su -s /bin/bash -c \
    "HOME=/sandbox SSL_CERT_FILE=$CA /usr/local/bin/nemoclaw-start" sandbox
  for i in $(seq 60); do hermes_in_ns "$NS" && break; sleep 3; done
  hermes_in_ns "$NS" || die "hermes health 等不到 200(docker exec $CT_H cat /tmp/nemoclaw-start.log)"
  ok "hermes gateway 在 netns 內 health 200（CA: $CA）"
fi

# ── 4. hermes host forward(此時 probe 必回 ALREADY_RUNNING,安全)──
step 4/4 "hermes-demo recover(host :8642 forward)"
if hermes_host; then
  ok "host :8642 已通,跳過"
else
  NEMOCLAW_GATEWAY_PORT=$GW_PORT nemoclaw hermes-demo recover >>"$LOG" 2>&1 \
    || die "hermes-demo recover 失敗"
  for i in $(seq 20); do hermes_host && break; sleep 2; done
  if ! hermes_host; then
    # fallback:recover 不一定建 8642 forward;gRPC service forward 直連 netns 內 18642(實測可用)
    nohup openshell forward service --target-port 18642 --local 127.0.0.1:8642 hermes-demo \
      >>"$LOG" 2>&1 & disown
    for i in $(seq 10); do hermes_host && break; sleep 2; done
  fi
  hermes_host && ok "hermes API http://127.0.0.1:8642/v1" || die "host :8642 還是不通"
fi

# ── 5. 跨 agent 通道:OpenClaw 入站修復端點 + scoped policy ──
ensure_xagent
ensure_dashboard
ensure_ebg_stream

echo
bash scripts/healthcheck.sh
rm -f "$LOG"
