#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-traffic-sync.sh — 從真機 EBG19P 唯讀拉 WAN 流量計數(netdev),單次取兩樣本算瞬時
# Mbps,append 到 node A(運維)沙箱 ebg19p-traffic.jsonl(時序 ring,最近 60 筆),
# 讓 OpenClaw /traffic 建流量基線 + 突增異常偵測(外洩/DDoS/挖礦行為)。
#   · 唯讀:只打 login.cgi + appGet.cgi?hook=netdev(appobj);不改設備。
#   · 憑證:~/.config/nemoclaw/ebg19p.cred(600);密碼/token 不入 repo 不回顯;cookie mktemp 即刪。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED_FILE="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
WD="/sandbox/.openclaw/workspace/it-task"
CTO="${CT_O:-$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)}"
[ -s "$CRED_FILE" ] || { echo "[ebg19p-traffic] 缺憑證檔 $CRED_FILE" >&2; exit 1; }
[ -n "$CTO" ] || { echo "[ebg19p-traffic] node A 容器未跑" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED_FILE"
B="http://$IP"; JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
CRED="$(printf '%s' "$USER:$PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$CRED" "$B/login.cgi" >/dev/null 2>&1
TOKEN="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || { echo "[ebg19p-traffic] 登入失敗($IP)" >&2; exit 1; }
ND(){ curl -s -m6 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=netdev(appobj)" 2>/dev/null; }

# 取兩樣本(間隔 ~3s)算瞬時 Mbps。介面優先序:WAN(INTERNET)→ 有線(WIRED)→ 橋接(BRIDGE)。
# 此機 WAN 埠未接 → netdev 無 INTERNET,自動退回 WIRED(主機↔EBG 有線實流量)。
SAMPLE="$(ND="$(ND)" python3 - <<'PY'
import os, re, time
d = os.environ.get("ND","")
def g(iface):
    m = re.search(iface+r"':\{rx:(0x[0-9a-fA-F]+),tx:(0x[0-9a-fA-F]+)\}", d)
    return (int(m.group(1),16), int(m.group(2),16)) if m else None
iface, rx, tx = "-", 0, 0
for cand in ("INTERNET","WIRED","BRIDGE"):
    v = g(cand)
    if v: iface, rx, tx = cand, v[0], v[1]; break
print(f"{time.time():.3f} {rx} {tx} {iface}")
PY
)"
sleep 3
SAMPLE2="$(ND="$(ND)" python3 - <<'PY'
import os, re, time
d = os.environ.get("ND","")
def g(iface):
    m = re.search(iface+r"':\{rx:(0x[0-9a-fA-F]+),tx:(0x[0-9a-fA-F]+)\}", d)
    return (int(m.group(1),16), int(m.group(2),16)) if m else None
iface, rx, tx = "-", 0, 0
for cand in ("INTERNET","WIRED","BRIDGE"):
    v = g(cand)
    if v: iface, rx, tx = cand, v[0], v[1]; break
print(f"{time.time():.3f} {rx} {tx} {iface}")
PY
)"

ENTRY="$(S1="$SAMPLE" S2="$SAMPLE2" python3 - <<'PY'
import os, time, json
t1,rx1,tx1,if1 = os.environ["S1"].split()
t2,rx2,tx2,if2 = os.environ["S2"].split()
t1,rx1,tx1 = float(t1),int(rx1),int(tx1); t2,rx2,tx2 = float(t2),int(rx2),int(tx2)
dt = max(0.5, t2-t1); dbytes = (rx2+tx2)-(rx1+tx1)
mbps = round(dbytes*8/dt/1e6, 3) if dbytes >= 0 else 0.0   # counter 歸零→0
print(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "mbps": mbps, "iface": if2,
                  "rx_total": rx2, "tx_total": tx2}, ensure_ascii=False))
PY
)"

# append 到 node A 沙箱(ring 保留最近 60 筆)
docker exec -i "$CTO" sh -c "touch $WD/ebg19p-traffic.jsonl; printf '%s\n' '$ENTRY' >> $WD/ebg19p-traffic.jsonl; tail -n 60 $WD/ebg19p-traffic.jsonl > $WD/.t && mv $WD/.t $WD/ebg19p-traffic.jsonl; chown 998:998 $WD/ebg19p-traffic.jsonl"
read -r MB IFACE < <(printf '%s' "$ENTRY" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["mbps"],d.get("iface","-"))' 2>/dev/null)
echo "[ebg19p-traffic] ✓ 已更新 $WD/ebg19p-traffic.jsonl($IP,${IFACE:-?} ${MB:-?} Mbps)"
