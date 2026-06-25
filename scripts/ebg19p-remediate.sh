#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-remediate.sh — 對 EBG19P 真實設定 remediation(OpenClaw A 維運動作),目前支援:wps-off / upnp-off。
# 流程:login.cgi 取 token → applyapp.cgi(action_mode=apply)寫 nvram + 套用 → 重讀驗證。可逆、可稽核。
# 用法:bash scripts/ebg19p-remediate.sh wps-off   # 或 upnp-off
set -uo pipefail
ACTION="${1:?用法: ebg19p-remediate.sh wps-off|upnp-off}"
CRED="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
[ -s "$CRED" ] || { echo "[remediate] 缺憑證 $CRED" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED"; B="http://$IP"
JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
C="$(printf '%s' "$USER:$PASS" | base64)"
curl -s -m12 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$C" "$B/login.cgi" >/dev/null 2>&1
TOK="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOK" ] || { echo "[remediate] 登入失敗($IP)" >&2; exit 1; }
gv(){ curl -s -m8 -b "$JAR" -H "Cookie: asus_token=$TOK" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=nvram_get($1)" 2>/dev/null | python3 -c "import sys,json;print(list(json.load(sys.stdin).values())[0])" 2>/dev/null; }

case "$ACTION" in
  wps-off)  KEY="wps_enable"; VAL="0"; SCRIPT="restart_wireless" ;;
  wps-on)   KEY="wps_enable"; VAL="1"; SCRIPT="restart_wireless" ;;
  upnp-off) KEY="upnp_enable"; VAL="0"; SCRIPT="restart_upnp" ;;
  upnp-on)  KEY="upnp_enable"; VAL="1"; SCRIPT="restart_upnp" ;;
  *) echo "[remediate] 不支援的動作:$ACTION" >&2; exit 2 ;;
esac

BEFORE="$(gv "$KEY")"
echo "[remediate] $KEY 目前 = ${BEFORE:-?} → 套用 $VAL(action_script=$SCRIPT)"
# applyapp.cgi:寫 nvram + 套用(ASUS 標準 apply)
curl -s -m20 -b "$JAR" -H "Cookie: asus_token=$TOK" -H "Referer: $B/Advanced_WWPS_Content.asp" \
  --data-urlencode "action_mode=apply" \
  --data-urlencode "action_script=$SCRIPT" \
  --data-urlencode "action_wait=10" \
  --data-urlencode "$KEY=$VAL" \
  "$B/applyapp.cgi" >/dev/null 2>&1
# 等套用完成後重讀驗證(restart_wireless 期間裝置會短暫無回應且 token 失效 → 重登再讀)
relogin(){ curl -s -m12 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$C" "$B/login.cgi" >/dev/null 2>&1
  TOK="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"; }
AFTER=""
for i in $(seq 12); do sleep 5; AFTER="$(gv "$KEY")"; [ -n "$AFTER" ] && break; relogin; done
echo "[remediate] $KEY 驗證 = ${AFTER:-讀取失敗}"
if [ "$AFTER" = "$VAL" ]; then echo "[remediate] ✓ $ACTION 成功($KEY=$AFTER)"; exit 0
else echo "[remediate] ✗ $ACTION 未生效($KEY=${AFTER:-?},預期 $VAL)" >&2; exit 3; fi
