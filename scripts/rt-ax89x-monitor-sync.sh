#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# rt-ax89x-monitor-sync.sh — 從真實 ASUS RT-AX89X(使用者實機)唯讀拉設定,正規化成 node A 機隊監控的
# rt-ax89x-current.conf,讓 /monitor 巡真機(與 ebg19p-monitor-sync 同做法)。
#   · 唯讀:只打 login.cgi + appGet.cgi?hook=nvram_get(),不改任何設定。
#   · 憑證:讀自 ~/.config/nemoclaw/rt-ax89x.cred(mode 600,格式 IP|USER|PASS,不入 repo)。
#   · schema 對齊:以容器內「已核准 baseline」為骨架,只用真機值覆寫安全/可監控鍵 → drift 比對乾淨。
#   · 衛生:密碼/token 不入 repo、不回顯;cookie mktemp 並於結束刪除。可 cron。
# 用法: bash scripts/rt-ax89x-monitor-sync.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED_FILE="${RTAX89X_CRED:-$HOME/.config/nemoclaw/rt-ax89x.cred}"
ASSET="lab-asus-rt-ax89x-01"
WD="/sandbox/.openclaw/workspace/it-task"
CONF_NAME="rt-ax89x-current.conf"
BASE_NAME="rt-ax89x-baseline.conf"
CTO="${CT_O:-$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)}"

[ -s "$CRED_FILE" ] || { echo "[rt-ax89x-sync] 缺憑證檔 $CRED_FILE(格式 IP|USER|PASS,chmod 600)" >&2; exit 1; }
[ -n "$CTO" ] || { echo "[rt-ax89x-sync] node A(my-assistant)容器未跑,先 bash scripts/boot-stack.sh" >&2; exit 1; }
IFS='|' read -r DEV_IP DEV_USER DEV_PASS < "$CRED_FILE"
B="http://$DEV_IP"
JAR="$(mktemp)"; trap 'rm -f "$JAR" /tmp/rtax-base.$$ ' EXIT

# 登入(帳密 base64;不回顯)
CRED="$(printf '%s' "$DEV_USER:$DEV_PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$CRED" "$B/login.cgi" >/dev/null 2>&1
TOKEN="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || { echo "[rt-ax89x-sync] 登入失敗($DEV_IP;檢查憑證/連線)" >&2; exit 1; }

gv(){ curl -s -m6 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" \
        "$B/appGet.cgi?hook=nvram_get($1)" 2>/dev/null | tr -d '\n{}"' | cut -d: -f2- | sed 's/^[[:space:]]*//'; }

FW="$(gv innerver)"; SSHE="$(gv sshd_enable)"; SSHP="$(gv sshd_pass)"; SSHPORT="$(gv sshd_port)"
LOGIP="$(gv log_ipaddr)"; LOGPORT="$(gv log_port)"

# 真機推算的安全/可監控鍵(對齊 baseline schema)
PWLOGIN="$([ "$SSHE" = "1" ] && [ "$SSHP" = "1" ] && echo true || echo false)"
SPORT="${SSHPORT:-22}"
LOGEN="$([ -n "$LOGIP" ] && echo true || echo false)"

# 取容器內已核准 baseline 當骨架(schema 對齊;若不存在則 seeder 應已建)
docker exec "$CTO" sh -c "cat $WD/$BASE_NAME 2>/dev/null" > "/tmp/rtax-base.$$" || true
[ -s "/tmp/rtax-base.$$" ] || { echo "[rt-ax89x-sync] 容器內無 $BASE_NAME(端點需先 seed)" >&2; exit 1; }

# 以真機值覆寫安全/可監控鍵,其餘維持 baseline → /monitor 只對「真機實際漂移」報警
CONF="$(FW="$FW" PWLOGIN="$PWLOGIN" SPORT="$SPORT" LOGEN="$LOGEN" LOGIP="$LOGIP" LOGPORT="${LOGPORT:-514}" \
  python3 - "/tmp/rtax-base.$$" <<'PY'
import os, sys, re
ov = {
  "ssh.password_login": os.environ["PWLOGIN"],
  "ssh.port": os.environ["SPORT"],
  "logging.remote.enabled": os.environ["LOGEN"],
}
if os.environ.get("LOGIP"): ov["logging.remote.host"] = os.environ["LOGIP"]
if os.environ.get("LOGPORT"): ov["logging.remote.port"] = os.environ["LOGPORT"]
if os.environ.get("FW"): ov["device.firmware"] = os.environ["FW"]
out = []
seen = set()
out.append("# Live snapshot — lab-asus-rt-ax89x-01 (ASUS RT-AX89X,使用者實機)")
out.append("# Source: live appGet from device; 安全鍵以真機現況覆寫,WAN IP/密碼/金鑰未取(唯讀)。")
for line in open(sys.argv[1], encoding="utf-8"):
    s = line.rstrip("\n")
    m = re.match(r"^([a-z0-9_.]+)\s*=\s*(.*)$", s)
    if m and m.group(1) in ov:
        k = m.group(1); out.append(f"{k} = {ov[k]}"); seen.add(k)
    elif s.startswith("#") and ("baseline" in s.lower() or "source:" in s.lower()):
        continue
    else:
        out.append(s)
print("\n".join(out))
PY
)"

printf '%s\n' "$CONF" | docker exec -i "$CTO" sh -c "cat > $WD/$CONF_NAME && chown 998:998 $WD/$CONF_NAME"
echo "[rt-ax89x-sync] ✓ 已更新 $CTO:$WD/$CONF_NAME($DEV_IP,韌體 ${FW:-?},ssh_pw=$PWLOGIN,remote_log=$LOGEN)"
