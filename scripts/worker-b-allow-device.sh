#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# worker-b-allow-device.sh — 讓 worker-b 經 OpenShell 受治理 egress 對 EBG19P 跑 nuclei 主動掃描。
# 背景:OPA deny-by-default。worker-b 用 nuclei-templates 主動掃 ASUS 裝置需:(1) egress 到「這一台」裝置
#       IP:80/443/8443,(2) 允許 nuclei binary 執行。scoped allow —— 只開這台裝置 + nuclei,非全開。
#       (nuclei-templates 從 github 拉 → 由 worker-b-allow-github.sh 已涵蓋。)
# idempotent:openshell policy update 合併語意,重跑安全。boot-stack 於 ensure_xagent 呼叫。
set -uo pipefail
SB="${WORKERB_SANDBOX:-worker-b}"
CRED="$HOME/.config/nemoclaw/ebg19p.cred"
command -v openshell >/dev/null 2>&1 || { echo "[allow-dev] 找不到 openshell CLI" >&2; exit 1; }
openshell policy get "$SB" >/dev/null 2>&1 || { echo "[allow-dev] 沙箱 $SB 未就緒(略過)"; exit 0; }
IP="$(cut -d'|' -f1 "$CRED" 2>/dev/null | tr -d ' \n\r')"
[ -n "$IP" ] || echo "[allow-dev] 無 EBG19P IP(缺 $CRED)→ 只允許 nuclei binary,無裝置 egress"
# array form (not a single unquoted-expansion command line) so each --add-endpoint flag/value pair
# is its own argv element without relying on word-splitting an unquoted "${IP:+...}" — same effect
# as the old form (endpoints omitted entirely when IP is empty), just not a semgrep/shellcheck
# unquoted-expansion finding to begin with.
args=(policy update "$SB")
if [ -n "$IP" ]; then
  args+=(--add-endpoint "$IP:80:full" --add-endpoint "$IP:443:full" --add-endpoint "$IP:8443:full")
fi
args+=(--binary /usr/local/bin/nuclei --binary /usr/bin/nuclei --wait --timeout 60)
openshell "${args[@]}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE "submitted|loaded|error|denied" || true
v="$(openshell policy get "$SB" 2>&1 | awk '/^Active:/{print $2}')"
echo "[allow-dev] ✓ $SB nuclei egress 就緒(裝置 ${IP:-<none>} + nuclei binary;active policy v${v:-?})"
