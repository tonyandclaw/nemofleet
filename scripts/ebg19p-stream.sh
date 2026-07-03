#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-stream.sh — EBG19P 即時串流 daemon:每 ~10 秒把真機 syslog + 健康(CPU/RAM/網口/溫度)
# 推進 worker-a 沙箱(/device-log、/monitor 即見),讓 GUI 近即時更新。
# 設計:登入一次、重用 token(autologout=0 不會過期);呼叫失敗才重登(連不到時 60s 退避)。
# 唯讀(只 login.cgi + appGet.cgi);憑證 ~/.config/nemoclaw/ebg19p.cred。背景跑:setsid。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
WD="/sandbox/.hermes/workspace/it-task"
INTERVAL="${EBG19P_STREAM_SEC:-5}"          # health 取樣間隔(秒)
SYSLOG_EVERY="${EBG19P_SYSLOG_EVERY:-6}"    # 每幾個 cycle 抓一次 syslog(755KB);5s×6≈30s
[ -s "$CRED" ] || { echo "[stream] 缺憑證 $CRED" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED"; B="http://$IP"
JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
TOK=""
ctn(){ docker ps --format '{{.Names}}' 2>/dev/null | grep -m1 worker-a; }

login(){
  local c; c="$(printf '%s' "$USER:$PASS" | base64)"
  curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
    -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$c" "$B/login.cgi" >/dev/null 2>&1
  TOK="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
  [ -n "$TOK" ]
}
gv(){ curl -s -m6 -b "$JAR" -H "Cookie: asus_token=$TOK" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=$1" 2>/dev/null; }

cycle(){
  local CTO; CTO="$(ctn)"; [ -n "$CTO" ] || return 1
  local CPU1 CPU2 MEM PORTS TEMP RAW
  CPU1="$(gv 'cpu_usage()')"; [ -n "$CPU1" ] || return 1
  # token 失效偵測:ASUS 是單一 session,別處登入會作廢本 token → 回應變登入轉址頁;偵測到就重登(自癒)
  case "$CPU1" in *Main_Login*|*"window.top.location"*) return 1;; esac
  sleep 1
  CPU2="$(gv 'cpu_usage()')"; MEM="$(gv 'memory_usage()')"; PORTS="$(gv 'get_wan_lan_status()')"; TEMP="$(gv 'get_cpu_temperature()')"
  # syslog 是 ~755KB 重物件,解耦:health 每 cycle(5s),syslog 每 SYSLOG_EVERY 個 cycle(預設 ~30s)才抓,免壓爆 httpd
  # 單引號內勿用反斜線:否則裝置收到 \"syslog.log\"(帶反斜線)→ nvram 名錯誤回空。要送字面雙引號給裝置。
  RAW=""; [ "${DO_SYSLOG:-1}" = "1" ] && RAW="$(gv 'nvram_dump("syslog.log","")')"
  # health
  H="$(CPU1="$CPU1" CPU2="$CPU2" MEM="$MEM" PORTS="$PORTS" TEMP="$TEMP" python3 <<'PY'
import os,re,json,time
def jl(s):
    try: return json.loads(s or "")
    except Exception: return {}
def n(x):
    try: return float(x)
    except Exception: return 0.0
c1=jl(os.environ.get("CPU1","")).get("cpu_usage",{}) or {}; c2=jl(os.environ.get("CPU2","")).get("cpu_usage",{}) or {}
du=dt=0.0
for k in c2:
    if k in c1: du+=n(c2[k].get("usage"))-n(c1[k].get("usage")); dt+=n(c2[k].get("total"))-n(c1[k].get("total"))
cpu=round(du/dt*100,1) if dt>0 else None
m=jl(os.environ.get("MEM","")).get("memory_usage",{}) or {}; mt,mu=n(m.get("total")),n(m.get("used")); ram=round(mu/mt*100,1) if mt>0 else None
SP={"G":"1G","Q":"2.5G","M":"100M","X":"down","":"down"}; ports=[]
for nm,code in (jl(os.environ.get("PORTS","")).get("get_wan_lan_status",{}).get("portSpeed",{}) or {}).items():
    ports.append({"port":nm,"state":("up" if code not in ("X","") else "down"),"speed":SP.get(code,code)})
mm=re.search(r'(\d+(?:\.\d+)?)', os.environ.get("TEMP","")); temp=round(float(mm.group(1)),1) if mm else None
import sys
# 負載下 EBG httpd 可能回壞值:cpu/ram/ports 全空 = 本 cycle 查詢失敗 → 不輸出,streamer 保留上一筆好值
# (避免寫出空 ports 清單,造成 WAN/LAN 埠被誤判反覆 up→down 觸發假 port-down 異常)
if cpu is None and ram is None and not ports:
    sys.exit(1)
print(json.dumps({"cpu_pct":cpu,"ram_pct":ram,"ram_total_kb":int(mt) if mt else None,"temp_c":temp,"ports":ports,"ts":time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False))
PY
)"
  [ -n "$H" ] && printf '%s\n' "$H" | docker exec -i "$CTO" sh -c "cat > $WD/ebg19p-health.json && chown 998:998 $WD/ebg19p-health.json" 2>/dev/null
  # syslog(寫暫存檔給 python 讀,避免 ARG_MAX);token 失效時 RAW 會是登入轉址頁 → 跳過不寫
  if [ -n "$RAW" ] && ! printf '%s' "$RAW" | grep -q "Main_Login"; then
    RAWF="$(mktemp)"; printf '%s' "$RAW" > "$RAWF"
    SJ="$(RAWF="$RAWF" python3 <<'PY'
import os,re,json
raw=open(os.environ["RAWF"],encoding="utf-8",errors="replace").read()
m=re.search(r'"nvram_dump-syslog\.log":\s*"?(.*?)"?\}\s*$', raw, re.S); body=m.group(1) if m else raw
lines=[l for l in body.replace("\\n","\n").splitlines() if l.strip()]
LINE=re.compile(r'^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+([\w./-]+(?:\[\d+\])?):?\s*(.*)$')
def cls(tag,msg):
    t=(tag+" "+msg).lower()
    cat=("wifi" if re.search(r'wlceventd|wlc|deauth|disassoc|wifi|wlan',t) else "firewall" if re.search(r'firewall|drop in=|dos|conntrack',t) else "auth" if re.search(r'httpd|login|auth|pam',t) else "dhcp" if re.search(r'dnsmasq|dhcp',t) else "vpn" if re.search(r'vpn|wireguard|ipsec',t) else "system" if re.search(r'kernel|usb|watchdog',t) else "service")
    sev=("high" if re.search(r'\b(attack|flood|intrus|unauthor|denied|refused|panic|fatal)\b',t) else "warn" if re.search(r'\b(fail|error|drop|timeout|reject|warn)\b',t) else "info")
    return cat,sev
out=[]
for l in lines[-150:]:
    mm=LINE.match(l.strip())
    ts,tag,msg=(mm.group(1),re.sub(r'\[\d+\]','',mm.group(2)),mm.group(3)) if mm else ("","",l.strip())
    cat,sev=cls(tag,msg); out.append({"t":ts,"tag":tag,"cat":cat,"sev":sev,"msg":msg[:200]})
print("\n".join(json.dumps(o,ensure_ascii=False) for o in out))
PY
)"
    rm -f "$RAWF"
    [ -n "$SJ" ] && printf '%s\n' "$SJ" | docker exec -i "$CTO" sh -c "cat > $WD/ebg19p-syslog.jsonl && chown 998:998 $WD/ebg19p-syslog.jsonl" 2>/dev/null
  fi
  return 0
}

echo "[stream] 啟動 EBG19P 即時串流(health 每 ${INTERVAL}s · syslog 每 $((INTERVAL*SYSLOG_EVERY))s)→ $IP"
login || echo "[stream] 初次登入失敗,進入重試迴圈"
N=0
while true; do
  # 第一輪抓 syslog,之後每 SYSLOG_EVERY 個 cycle 抓一次;其餘 cycle 只更新 health
  if [ $(( N % SYSLOG_EVERY )) -eq 0 ]; then DO_SYSLOG=1; else DO_SYSLOG=0; fi
  export DO_SYSLOG
  if ! cycle; then
    echo "[stream] $(date '+%H:%M:%S') 取數失敗 → 重登/退避" >&2
    login || { sleep 60; continue; }
  fi
  N=$((N+1)); sleep "$INTERVAL"
done
