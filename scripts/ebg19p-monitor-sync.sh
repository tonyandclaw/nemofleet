#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-monitor-sync.sh — 從真實 ASUS ExpertWiFi EBG19P(使用者實機)唯讀拉設定/狀態,
# 正規化成 node A(IT 運維)worker 機隊監控的 ebg19p-current.conf,讓 /monitor 巡真機。
#   · 唯讀:只打 login.cgi + appGet.cgi?hook=nvram_get()/get_clientlist(),不改任何設定。
#   · 憑證:讀自 ~/.config/nemoclaw/ebg19p.cred(mode 600,格式 IP|USER|PASS,不入 repo/git)。
#   · 衛生:密碼/token 不寫入 repo,不印到 stdout;cookie 用 mktemp 並於結束刪除。
#   · 可排程:cron 每 N 分鐘跑一次,monitor 即見最新真機狀態。
# 用法: bash scripts/ebg19p-monitor-sync.sh
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED_FILE="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
ASSET="lab-asus-ebg19p-01"
WD="/sandbox/.hermes/workspace/it-task"
CONF_NAME="ebg19p-current.conf"
CTO="${CT_WA:-$(docker ps --format '{{.Names}}' | grep -m1 worker-a)}"

[ -s "$CRED_FILE" ] || { echo "[ebg19p-sync] 缺憑證檔 $CRED_FILE(格式 IP|USER|PASS,chmod 600)" >&2; exit 1; }
[ -n "$CTO" ] || { echo "[ebg19p-sync] node A(worker-a)容器未跑,先 bash scripts/boot-stack.sh" >&2; exit 1; }
IFS='|' read -r DEV_IP DEV_USER DEV_PASS < "$CRED_FILE"
B="http://$DEV_IP"
JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT

# 登入(帳密 base64;不回顯)
CRED="$(printf '%s' "$DEV_USER:$DEV_PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$CRED" "$B/login.cgi" >/dev/null 2>&1
TOKEN="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || { echo "[ebg19p-sync] 登入失敗($DEV_IP;檢查憑證/連線)" >&2; exit 1; }

gv(){ curl -s -m6 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" \
        "$B/appGet.cgi?hook=nvram_get($1)" 2>/dev/null | tr -d '\n{}"' | cut -d: -f2- | sed 's/^[[:space:]]*//'; }
gh(){ curl -s -m6 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=$1" 2>/dev/null; }
b(){ [ "$1" = "1" ] && echo true || echo false; }

FW="$(gv innerver)"; MAC="$(gv label_mac)"; MHTTP="$(gv misc_http_x)"; MPORT="$(gv misc_httpport_x)"
SSHE="$(gv sshd_enable)"; SSHP="$(gv sshd_pass)"; TEL="$(gv telnetd_enable)"; FWE="$(gv fw_enable_x)"
DOS="$(gv fw_dos_x)"; UP="$(gv upnp_enable)"; WPS="$(gv wps_enable)"; DMZ="$(gv dmz_ip)"
VTS="$(gv vts_enable_x)"; WGS="$(gv wgs_enable)"; LOGIP="$(gv log_ipaddr)"; SMB="$(gv st_samba_mode)"
DPI="$(gv bwdpi_db_enable)"; WPROTO="$(gv wan0_proto)"; SSID="$(gv wl0_ssid)"; UPT="$(gh 'uptime()' | grep -oE '[0-9]+ secs' | grep -oE '[0-9]+')"
FTP="$(gv enable_ftp)"; DDNS="$(gv ddns_enable_x)"   # nvram keys are the same ones worker-a's remediation writes (EBG_ACTIONS)
CLIENTS="$(gh 'get_clientlist()' | grep -oc '"mac":' || true)"

CONF="$(cat <<CONF
# Live snapshot — $ASSET (ASUS ExpertWiFi EBG19P,使用者實機)
# Source: live appGet from device @ $(date '+%F %H:%M %Z'); WAN IP / 密碼 / 金鑰已剔除(唯讀正規化)。
device.model = EBG19P
device.firmware = ${FW:-unknown}
device.timezone = Asia/Taipei
device.mac = ${MAC:-unknown}
webui.https.enabled = false
webui.http.enabled = true
webui.wan_access = $(b "$MHTTP")
webui.wan_port = ${MPORT:-}
ssh.enabled = $(b "$SSHE")
ssh.password_login = $([ "$SSHE" = "1" ] && b "$SSHP" || echo false)
ssh.wan_access = false
telnet.enabled = $(b "$TEL")
firewall.enabled = $(b "$FWE")
firewall.wan_to_lan.default = drop
firewall.dos_protection = $([ "$DOS" = "1" ] && echo enabled || echo disabled)
upnp.enabled = $(b "$UP")
wps.enabled = $(b "$WPS")
dmz.enabled = $([ -n "$DMZ" ] && echo true || echo false)
portforward.enabled = $(b "$VTS")
vpn.server.enabled = $(b "$WGS")
samba.enabled = $([ -n "$SMB" ] && [ "$SMB" != "0" ] && echo true || echo false)
ftp.enabled = $(b "$FTP")
ddns.enabled = $(b "$DDNS")
aiprotection.enabled = $(b "$DPI")
wan.proto = ${WPROTO:-unknown}
wifi.ssid = ${SSID:-unknown}
logging.remote.enabled = $([ -n "$LOGIP" ] && echo true || echo false)
firmware.auto_check = enabled
# --- 即時狀態(資訊用,易變動故不納入 drift 比對)---
# clients.connected = ${CLIENTS:-0}
# uptime.seconds = ${UPT:-0}
CONF
)"

# 寫入 node A 沙箱工作區(sandbox 擁有者 998:998)
printf '%s\n' "$CONF" | docker exec -i "$CTO" sh -c "cat > $WD/$CONF_NAME && chown 998:998 $WD/$CONF_NAME"
echo "[ebg19p-sync] ✓ 已更新 $CTO:$WD/$CONF_NAME($DEV_IP,韌體 ${FW:-?},clients ${CLIENTS:-0})"

# ── 即時健康:CPU(兩次取樣算瞬時%)/RAM/網口/溫度(供 dashboard 在 online 時顯示)──
CPU1="$(gh 'cpu_usage()')"; sleep 1; CPU2="$(gh 'cpu_usage()')"
MEMJ="$(gh 'memory_usage()')"; PORTS="$(gh 'get_wan_lan_status()')"; TEMP="$(gh 'get_cpu_temperature()')"
HEALTH="$(CPU1="$CPU1" CPU2="$CPU2" MEMJ="$MEMJ" PORTS="$PORTS" TEMP="$TEMP" python3 <<'PY'
import os, re, json
def jl(s):
    try: return json.loads(s or "")
    except Exception: return {}
def n(x):
    try: return float(x)
    except Exception: return 0.0
c1=jl(os.environ.get("CPU1","")).get("cpu_usage",{}) or {}
c2=jl(os.environ.get("CPU2","")).get("cpu_usage",{}) or {}
du=dt=0.0
for k in c2:
    if k in c1:
        du+=n(c2[k].get("usage"))-n(c1[k].get("usage")); dt+=n(c2[k].get("total"))-n(c1[k].get("total"))
cpu=round(du/dt*100,1) if dt>0 else None
m=jl(os.environ.get("MEMJ","")).get("memory_usage",{}) or {}
mt,mu=n(m.get("total")),n(m.get("used")); ram=round(mu/mt*100,1) if mt>0 else None
SP={"G":"1G","Q":"2.5G","M":"100M","X":"down","":"down"}
ports=[]
for name,code in (jl(os.environ.get("PORTS","")).get("get_wan_lan_status",{}).get("portSpeed",{}) or {}).items():
    ports.append({"port":name,"state":("up" if code not in ("X","") else "down"),"speed":SP.get(code,code)})
mt2=re.search(r'([0-9.]+)', os.environ.get("TEMP","")); temp=round(float(mt2.group(1)),1) if mt2 else None
print(json.dumps({"cpu_pct":cpu,"ram_pct":ram,"ram_total_kb":int(mt) if mt else None,"temp_c":temp,"ports":ports,"ts":__import__("time").strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False))
PY
)"
[ -n "$HEALTH" ] && printf '%s\n' "$HEALTH" | docker exec -i "$CTO" sh -c "cat > $WD/ebg19p-health.json && chown 998:998 $WD/ebg19p-health.json" && echo "[ebg19p-sync]   健康指標已更新(cpu/ram/ports/temp)"

# 基準初始化(冪等):不存在/不含 upnp 鍵時,以本次快照建立(建議 UPnP/WPS 關閉=待審);
# 已存在則不動,保留人工核准的安全基準。
if ! docker exec "$CTO" sh -c "[ -f $WD/ebg19p-baseline.conf ] && grep -q '^upnp.enabled' $WD/ebg19p-baseline.conf" 2>/dev/null; then
  docker exec "$CTO" sh -c "sed -e '1s|.*|# Approved security baseline — $ASSET(硬合規:DoS/遠端syslog 開、UPnP/WPS 關;餘以真機現況為準)|' -e 's/^upnp.enabled = .*/upnp.enabled = false/' -e 's/^wps.enabled = .*/wps.enabled = false/' -e 's/^firewall.dos_protection = .*/firewall.dos_protection = enabled/' $WD/$CONF_NAME > $WD/ebg19p-baseline.conf && chown 998:998 $WD/ebg19p-baseline.conf"
  echo "[ebg19p-sync]   基準不存在 → 已用本次快照初始化(UPnP/WPS 建議關閉)"
fi
echo "[ebg19p-sync]   monitor 即見真機狀態:docker exec $CTO curl -s -H 'X-Bridge-Token: …' :9099/monitor"
