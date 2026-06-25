#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# ebg19p-set-autologout.sh — 設定真機 EBG19P 網頁閒置自動登出時間(分鐘;0=永不登出)。
# 這是「寫入」設備設定(非唯讀同步),經 ASUS applyapp.cgi。會重啟 web 服務數秒。
# 憑證:~/.config/nemoclaw/ebg19p.cred(IP|USER|PASS,600)。需電腦連得到 EBG19P LAN。
# 用法:bash scripts/ebg19p-set-autologout.sh [分鐘]   省略=0(不登出)
set -uo pipefail
MIN="${1:-0}"
[[ "$MIN" =~ ^[0-9]+$ ]] || { echo "分鐘需為數字(0=不登出)" >&2; exit 1; }
CRED="${EBG19P_CRED:-$HOME/.config/nemoclaw/ebg19p.cred}"
[ -s "$CRED" ] || { echo "缺憑證 $CRED" >&2; exit 1; }
IFS='|' read -r IP USER PASS < "$CRED"; B="http://$IP"; JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
C="$(printf '%s' "$USER:$PASS" | base64)"
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' \
  -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$C" "$B/login.cgi" >/dev/null 2>&1
TOK="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
[ -n "$TOK" ] || { echo "登入失敗($IP;檢查憑證/連線)" >&2; exit 1; }
R="$(curl -s -m15 -b "$JAR" -H "Cookie: asus_token=$TOK" -H "Referer: $B/Advanced_System_Content.asp" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data "action_mode=apply&action_script=restart_httpd&http_autologout=$MIN" "$B/applyapp.cgi" 2>/dev/null)"
echo "apply 回應: $R"
# 等 web 重啟回來再驗證
i=0; until curl -s -m3 -o /dev/null "$B/Main_Login.asp" || [ $i -ge 15 ]; do i=$((i+1)); sleep 2; done
curl -s -m10 -c "$JAR" -H 'Content-Type: application/x-www-form-urlencoded' -H "Referer: $B/Main_Login.asp" --data-urlencode "login_authorization=$C" "$B/login.cgi" >/dev/null 2>&1
TOK="$(awk '/asus_token/{print $NF}' "$JAR" | tail -1)"
NOW="$(curl -s -m6 -b "$JAR" -H "Cookie: asus_token=$TOK" -H "Referer: $B/index.asp" "$B/appGet.cgi?hook=nvram_get(http_autologout)" 2>/dev/null | grep -oE '"[0-9]+"' | tr -d '"')"
echo "✓ http_autologout 現值 = ${NOW:-?} 分鐘 $([ "${NOW:-x}" = 0 ] && echo '(永不自動登出)')"
