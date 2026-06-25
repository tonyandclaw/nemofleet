#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-traffic-loadtest.sh — 對 EBG19P 製造一段「不小的流量」並寫進流量 ring,讓儀表板流量圖出現尖峰(demo 用)。
# 為什麼要這樣做(踩過的坑,全內建處理):
#   · 這台 WAN 埠未接 → netdev 無 INTERNET,實際在動的是 WIRED(主機↔EBG 有線);sync 已自動落 WIRED。
#   · ASUS 有「登入頻率鎖定」+「單一 session」:每次重登/多 worker 會把 httpd 灌爆、觸發鎖定,且新登入會作廢舊 token。
#     對策:① 暫停 fleet-compliance cron ② 停 ebg19p-stream.sh ③ 單一登入、全程重用 token、絕不重登
#           ④ worker 數預設 2(httpd 很弱,>2 會把量測用的 netdev 也卡到回空)⑤ trap EXIT 一定復原 cron + 重啟 streamer。
# 唯讀 + 自家設備自家網路的授權壓測。用法:bash scripts/ebg19p-traffic-loadtest.sh [秒數] [worker數] [取樣次數]
set -uo pipefail
DUR="${1:-40}"; WORKERS="${2:-2}"; SAMPLES="${3:-7}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
CRED="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
WD="/sandbox/.openclaw/workspace/it-task"
[ -s "$CRED" ] || { echo "缺憑證 $CRED" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED"; B="http://$IP"
CTO="$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)"
[ -n "$CTO" ] || { echo "node A(my-assistant)容器未跑" >&2; exit 1; }

CRONBAK="$(mktemp)"; crontab -l 2>/dev/null > "$CRONBAK"
STREAM_WAS=0; pgrep -f "ebg19p-stream.sh" >/dev/null 2>&1 && STREAM_WAS=1

restore() {
  crontab "$CRONBAK" 2>/dev/null && echo "[loadtest] cron 已復原"
  rm -f "$CRONBAK"
  if [ "$STREAM_WAS" = 1 ] && ! pgrep -f "ebg19p-stream.sh" >/dev/null 2>&1; then
    ( cd "$DIR" && setsid bash scripts/ebg19p-stream.sh >/tmp/ebg19p-stream.log 2>&1 < /dev/null & )
    echo "[loadtest] streamer 已重啟"
  fi
}
trap restore EXIT

# 1) 暫停會自動登入 EBG 的來源(cron + streamer),讓單一 token 不被作廢
grep -v "fleet-compliance" "$CRONBAK" | crontab - 2>/dev/null
echo "[loadtest] fleet-compliance cron 已暫停"
for p in $(pgrep -f "ebg19p-stream.sh" 2>/dev/null); do kill "$p" 2>/dev/null; done
[ "$STREAM_WAS" = 1 ] && echo "[loadtest] ebg19p-stream.sh 已暫停"

# 2) 單一登入(鎖定時不硬試:最多 2 次、每次間隔 20s)
C="$(printf '%s' "$USER:$PASS" | base64)"; TOK=""
for try in 1 2; do
  JAR="$(mktemp)"
  curl -s -m12 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
    -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$C" "$B/login.cgi" >/dev/null 2>&1
  TOK="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"; rm -f "$JAR"
  [ -n "$TOK" ] && break
  echo "[loadtest] 第 $try 次登入失敗(可能被鎖),等 20s…"; for i in $(seq 20); do sleep 1; done
done
[ -n "$TOK" ] || { echo "[loadtest] 登入仍失敗 — EBG 可能仍在登入鎖定,請等 1-2 分鐘再跑(期間勿其他工具登入)" >&2; exit 1; }
echo "[loadtest] ✓ token 取得,全程重用(不重登)"

ND(){ local r a; for a in 1 2 3 4; do r="$(curl -s -m12 -H "Cookie: asus_token=$TOK" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=netdev(appobj)" 2>/dev/null)"; echo "$r" | grep -q WIRED && { echo "$r"; return; }; done; echo "$r"; }
URL="$B/appGet.cgi?hook=nvram_dump(\"syslog.log\",\"\")"

# 3) 啟動 worker 灌流量(重用 token)
END=$(( $(date +%s) + DUR )); PIDS=""
echo "[loadtest] 啟動 $WORKERS 個 worker,持續 ~${DUR}s …"
for w in $(seq "$WORKERS"); do
  ( while [ "$(date +%s)" -lt "$END" ]; do curl -s -m12 -H "Cookie: asus_token=$TOK" -H "Referer: $B/index.asp" -o /dev/null "$URL" 2>/dev/null; done ) & PIDS="$PIDS $!"
done

# 4) 內聯取樣寫 ring(同 token)
echo "[loadtest] 取樣 $SAMPLES 次寫入流量 ring …"
for i in $(seq "$SAMPLES"); do
  S1="$(ND)"; t1=$(date +%s.%N); sleep 3; S2="$(ND)"; t2=$(date +%s.%N)
  ENTRY="$(S1="$S1" S2="$S2" T1="$t1" T2="$t2" python3 - <<'PY'
import os,re,time,json
def pick(d):
    for c in ("INTERNET","WIRED","BRIDGE"):
        m=re.search(c+r"':\{rx:(0x[0-9a-fA-F]+),tx:(0x[0-9a-fA-F]+)\}",d)
        if m: return c,int(m.group(1),16),int(m.group(2),16)
    return "-",0,0
i1,r1,x1=pick(os.environ["S1"]); i2,r2,x2=pick(os.environ["S2"])
dt=max(0.5,float(os.environ["T2"])-float(os.environ["T1"])); db=(r2+x2)-(r1+x1)
mbps=round(db*8/dt/1e6,3) if (db>=0 and i1!="-" and i2!="-") else 0.0
print(json.dumps({"ts":time.strftime("%Y-%m-%d %H:%M:%S"),"mbps":mbps,"iface":i2,"rx_total":r2,"tx_total":x2},ensure_ascii=False))
PY
)"
  echo "   $ENTRY"
  docker exec -i "$CTO" sh -c "printf '%s\n' '$ENTRY' >> $WD/ebg19p-traffic.jsonl; tail -n 60 $WD/ebg19p-traffic.jsonl > $WD/.t && mv $WD/.t $WD/ebg19p-traffic.jsonl; chown 998:998 $WD/ebg19p-traffic.jsonl"
done
for p in $PIDS; do kill "$p" 2>/dev/null; done; wait 2>/dev/null
echo "[loadtest] 完成。儀表板『設備監控』EBG19P 流量圖即見尖峰(超基線會標紅『流量突增異常』)。"
