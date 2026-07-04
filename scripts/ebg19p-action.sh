#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-action.sh — EBG19P 運維「快速處置」executor(受控寫入 + 稽核)。
# 由 dashboard 後端(localhost)或人手呼叫;host 端執行(host 可達 192.168.50.1、讀 600 cred)。
#   動作:
#     sync            唯讀:立即同步設定/資產/流量/日誌 + 合規巡檢(免確認;走 compliance-cron 流水線)
#     harden          寫入:套用安全基準(關 UPnP/WPS、開 DoS)— 冪等、安全方向
#     restart         寫入:重啟防火牆/無線服務(WiFi 短暫斷)
#     block <MAC>     寫入:對未授權 MAC 加入無線封鎖清單
#   安全:憑證讀自 ~/.config/nemoclaw/ebg19p.cred(600,不入 repo);token 即用即棄;
#         每次 append 稽核 ~/.config/nemoclaw/ebg19p-audit.jsonl;寫入類由呼叫端(dashboard)二次確認。
set -uo pipefail
DIR=$NEMOFLEET_ROOT
CRED_FILE="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
AUDIT="${EBG19P_AUDIT:-$HOME/.config/nemoclaw/ebg19p-audit.jsonl}"
ACTION="${1:-}"; ARG="${2:-}"
audit(){ # $1=action $2=result $3=detail
  python3 - "$1" "$2" "$3" <<PY >> "$AUDIT" 2>/dev/null
import json,sys,time
print(json.dumps({"ts":time.strftime("%Y-%m-%d %H:%M:%S"),"action":sys.argv[1],
  "result":sys.argv[2],"detail":sys.argv[3][:200],"by":"worker-A/ops"},ensure_ascii=False))
PY
}
fail(){ echo "[ebg19p-action] $1" >&2; echo "RESULT=failed"; audit "$ACTION" "failed" "$1"; exit 1; }
logout(){ [ -n "${TOKEN:-}" ] && curl -s -m4 -b "$JAR" -H "Cookie: asus_token=$TOKEN" "$B/Logout.asp" >/dev/null 2>&1 || true; }

[ -n "$ACTION" ] || fail "缺動作(sync|harden|restart|block)"
# sync 唯讀,直接走流水線
if [ "$ACTION" = "sync" ]; then
  bash "$DIR/scripts/ebg19p-compliance-cron.sh" >/dev/null 2>&1 && r=ok || r=failed
  audit sync "$r" "強制同步 設定/資產/流量/日誌 + 合規巡檢"
  echo "[ebg19p-action] sync $r"; echo "RESULT=$r"; [ "$r" = ok ]; exit $?
fi

[ -s "$CRED_FILE" ] || fail "缺憑證檔 $CRED_FILE"
IFS='|' read -r IP USER PASS < "$CRED_FILE"
B="http://$IP"; JAR="$(mktemp)"; trap 'logout; rm -f "$JAR"' EXIT  # 結束時登出,釋放 httpd session
CRED="$(printf '%s' "$USER:$PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$CRED" "$B/login.cgi" >/dev/null 2>&1
TOKEN="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || fail "登入失敗($IP)"
apply(){ curl -s -m30 -b "$JAR" -H "Cookie: asus_token=$TOKEN" -H "Referer: $B/Advanced_BasicFirewall_Content.asp" "$@" "$B/applyapp.cgi" 2>/dev/null; }

case "$ACTION" in
  harden)
    R="$(apply --data-urlencode "action_mode=apply" --data-urlencode "action_script=restart_firewall;restart_wireless" \
               --data-urlencode "action_wait=10" --data-urlencode "fw_dos_x=1" \
               --data-urlencode "upnp_enable=0" --data-urlencode "wps_enable=0")"
    echo "$R" | grep -q 'modify' && { audit harden ok "套用安全基準:wps=0,upnp=0,dos=1"; echo "[ebg19p-action] harden ok"; echo "RESULT=ok"; } \
                                  || fail "harden apply 無回應確認:$(printf '%.80s' "$R")" ;;
  restart)
    R="$(apply --data-urlencode "action_mode=apply" --data-urlencode "action_script=restart_firewall;restart_wireless" \
               --data-urlencode "action_wait=10")"
    audit restart ok "重啟 firewall+wireless 服務"; echo "[ebg19p-action] restart sent"; echo "RESULT=ok" ;;
  block)
    [ -n "$ARG" ] || { audit block skipped "無未授權 MAC,略過"; echo "[ebg19p-action] block: 無對象(無未授權設備)"; echo "RESULT=skipped"; exit 0; }
    MAC="$(printf '%s' "$ARG" | tr 'a-f' 'A-F')"
    R="$(apply --data-urlencode "action_mode=apply" --data-urlencode "action_script=restart_wireless" \
               --data-urlencode "wl_macmode=deny" --data-urlencode "wl_maclist_x=$MAC")"
    audit block ok "封鎖未授權 MAC $MAC(wl_macmode=deny)"; echo "[ebg19p-action] block $MAC sent"; echo "RESULT=ok" ;;
  *) fail "未知動作 $ACTION" ;;
esac
