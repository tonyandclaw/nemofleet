#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-syslog-sync.sh — 從真機 EBG19P 唯讀拉系統日誌(nvram_dump syslog.log),
# 正規化成 OCSF-style 事件(category/severity)寫進 node A(運維)沙箱 ebg19p-syslog.jsonl,
# 讓 OpenClaw /device-log 做設備日誌集中 + 安全事件分類。把「無遠端 syslog」缺口轉成整合閉環。
#   · 唯讀:只打 login.cgi + appGet.cgi?hook=nvram_dump(...);不改設備、不需設備主動送(免跨網段)。
#   · 憑證:~/.config/nemoclaw/ebg19p.cred(600);密碼/token 不入 repo 不回顯;cookie mktemp 即刪。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED_FILE="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
WD="/sandbox/.openclaw/workspace/it-task"
CTO="${CT_O:-$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)}"
[ -s "$CRED_FILE" ] || { echo "[ebg19p-syslog] 缺憑證檔 $CRED_FILE" >&2; exit 1; }
[ -n "$CTO" ] || { echo "[ebg19p-syslog] node A(my-assistant)容器未跑" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED_FILE"
B="http://$IP"; JAR="$(mktemp)"; trap 'rm -f "$JAR" "${RAWF:-}"' EXIT
CRED="$(printf '%s' "$USER:$PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$CRED" "$B/login.cgi" >/dev/null 2>&1
TOKEN="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || { echo "[ebg19p-syslog] 登入失敗($IP)" >&2; exit 1; }
RAW="$(curl -s -m12 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" \
       "$B/appGet.cgi?hook=nvram_dump(\"syslog.log\",\"\")" 2>/dev/null)"
[ -n "$RAW" ] || { echo "[ebg19p-syslog] 取日誌失敗" >&2; exit 1; }

RAWF="$(mktemp)"; printf '%s' "$RAW" > "$RAWF"
JSONL="$(RAWF="$RAWF" python3 <<'PY'
import os, re, json
raw = open(os.environ["RAWF"], encoding="utf-8", errors="replace").read()
# 去 JSON 外殼: {"nvram_dump-syslog.log":<日誌>}
m = re.search(r'"nvram_dump-syslog\.log":\s*"?(.*?)"?\}\s*$', raw, re.S)
body = m.group(1) if m else raw
lines = [l for l in body.replace("\\n", "\n").splitlines() if l.strip()]

def classify(tag, msg):
    t = (tag + " " + msg).lower()
    # OCSF-ish category
    if re.search(r'wlceventd|wlc|deauth|disassoc|assoc|wifi|wlan', t): cat = "wifi"
    elif re.search(r'firewall|drop in=|iptables|dos|synflood|conntrack', t): cat = "firewall"
    elif re.search(r'httpd|login|auth|pam|session', t): cat = "auth"
    elif re.search(r'miniupnpd|upnp', t): cat = "upnp"
    elif re.search(r'dnsmasq|dhcp', t): cat = "dhcp"
    elif re.search(r'vpn|wireguard|openvpn|ipsec', t): cat = "vpn"
    elif re.search(r'kernel|modprobe|watchdog|psci|usb|hub', t): cat = "system"
    else: cat = "service"
    # severity
    if re.search(r'\b(attack|flood|intrus|unauthor|denied|refused|panic|fatal)\b', t): sev = "high"
    elif re.search(r'\b(fail|failed|error|drop|timed out|timeout|warn|reject)\b', t): sev = "warn"
    else: sev = "info"
    return cat, sev

LINE = re.compile(r'^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+([\w./-]+(?:\[\d+\])?):?\s*(.*)$')
out = []
for l in lines:
    mm = LINE.match(l.strip())
    if mm:
        ts, tag, msg = mm.group(1), re.sub(r'\[\d+\]', '', mm.group(2)), mm.group(3)
    else:
        ts, tag, msg = "", "", l.strip()
    cat, sev = classify(tag, msg)
    out.append({"t": ts, "tag": tag, "cat": cat, "sev": sev, "msg": msg[:200]})
# 只保留最近 150 行(syslog.log 已是時序;尾端最新)
out = out[-150:]
print("\n".join(json.dumps(o, ensure_ascii=False) for o in out))
PY
)"
[ -n "$JSONL" ] || { echo "[ebg19p-syslog] 正規化後為空" >&2; exit 1; }
printf '%s\n' "$JSONL" | docker exec -i "$CTO" sh -c "cat > $WD/ebg19p-syslog.jsonl && chown 998:998 $WD/ebg19p-syslog.jsonl"
N="$(printf '%s\n' "$JSONL" | wc -l)"
SEC="$(printf '%s\n' "$JSONL" | grep -Ec '"sev": ?"(high|warn)"' || true)"
echo "[ebg19p-syslog] ✓ 已更新 node A:$WD/ebg19p-syslog.jsonl($IP,$N 行,安全關注 ${SEC:-0})"
