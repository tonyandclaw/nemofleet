#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-asset-sync.sh — 從真機 EBG19P 唯讀拉「已連線資產清單」,正規化成 node A 沙箱的
# ebg19p-assets.json,讓 OpenClaw /assets 做資產盤點 + 未授權接入偵測(對比已核准清單)。
#   · 唯讀:只打 login.cgi + appGet.cgi?hook=get_clientlist()/dhcpLeaseMacList()。
#   · 憑證:讀自 ~/.config/nemoclaw/ebg19p.cred(600,IP|USER|PASS,不入 repo)。
#   · 衛生:密碼/token 不入 repo 不回顯;cookie mktemp 即刪。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED_FILE="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
WD="/sandbox/.openclaw/workspace/it-task"
CTO="${CT_O:-$(docker ps --format '{{.Names}}' | grep -m1 my-assistant)}"
[ -s "$CRED_FILE" ] || { echo "[ebg19p-asset] 缺憑證檔 $CRED_FILE" >&2; exit 1; }
[ -n "$CTO" ] || { echo "[ebg19p-asset] node A 容器未跑" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED_FILE"
B="http://$IP"; JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
CRED="$(printf '%s' "$USER:$PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$CRED" "$B/login.cgi" >/dev/null 2>&1
TOKEN="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || { echo "[ebg19p-asset] 登入失敗($IP)" >&2; exit 1; }

CL="$(curl -s -m8 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=get_clientlist()" 2>/dev/null)"
DH="$(curl -s -m8 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=dhcpLeaseMacList()" 2>/dev/null)"

# 正規化成資產陣列(剔除空項;type 數字對應 ASUS 裝置類型,保留原值供分類)
ASSETS="$(CL="$CL" DH="$DH" python3 <<'PY'
import json, os, time
def safe(s):
    try: return json.loads(s)
    except Exception: return {}
cl = safe(os.environ.get("CL","")).get("get_clientlist", {})
dh = {m.lower(): n for m, n in safe(os.environ.get("DH","")).get("dhcpLeaseMacList", []) if m}
out = []
for mac, c in cl.items():
    if not isinstance(c, dict) or not c.get("mac"): continue
    out.append({
        "mac": c.get("mac", mac).upper(),
        "ip": c.get("ip", ""),
        "name": c.get("nickName") or c.get("name") or dh.get(mac.lower(), ""),
        "type": c.get("type", ""),
        "conn": "wired" if str(c.get("isWL", "0")) in ("0", "") else "wifi",
        "sdn": c.get("sdn_type", "DEFAULT"),
    })
out.sort(key=lambda x: x["ip"])
print(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(out), "assets": out}, ensure_ascii=False))
PY
)"
[ -n "$ASSETS" ] || { echo "[ebg19p-asset] 正規化失敗" >&2; exit 1; }
printf '%s\n' "$ASSETS" | docker exec -i "$CTO" sh -c "cat > $WD/ebg19p-assets.json && chown 998:998 $WD/ebg19p-assets.json"
N="$(printf '%s' "$ASSETS" | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])' 2>/dev/null)"

# 已核准資產清單(approved MAC):不存在則以本次初始化(首見即核准);之後新 MAC = 未授權接入
if ! docker exec "$CTO" sh -c "[ -f $WD/ebg19p-assets-approved.json ]" 2>/dev/null; then
  printf '%s\n' "$ASSETS" | docker exec -i "$CTO" python3 -c "
import json,sys
d=json.load(sys.stdin)
appr={'ts':d['ts'],'approved':[a['mac'] for a in d['assets']]}
open('$WD/ebg19p-assets-approved.json','w').write(json.dumps(appr,ensure_ascii=False))
" && docker exec "$CTO" sh -c "chown 998:998 $WD/ebg19p-assets-approved.json"
  echo "[ebg19p-asset]   已核准清單不存在 → 以本次 $N 台初始化(首見即核准)"
fi
echo "[ebg19p-asset] ✓ 已更新 $WD/ebg19p-assets.json($IP,資產 ${N:-?} 台)"
