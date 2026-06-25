#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# openclaw-b-allow-github.sh — 讓 OpenClaw B(openclaw-2 沙箱)經 OpenShell 受治理 egress 連 github。
# 背景:OPA deny-by-default;B 自主抽 SBOM/SAST/上游 advisory 需連 api/raw github,且用 python3(urllib)抓,
#       而既有 brew 政策只允許 curl/git → 被擋。本腳本加 scoped allow(指定 host + binary),非全開。
# idempotent:openshell policy update 為合併語意,重跑安全。boot-stack 會呼叫,確保重開機/重建後仍允許。
set -uo pipefail
SB="${OPENCLAW_B_SANDBOX:-openclaw-2}"
command -v openshell >/dev/null 2>&1 || { echo "[allow-gh] 找不到 openshell CLI" >&2; exit 1; }
openshell policy get "$SB" >/dev/null 2>&1 || { echo "[allow-gh] 沙箱 $SB 未就緒(略過)"; exit 0; }
openshell policy update "$SB" \
  --add-endpoint api.github.com:443:full \
  --add-endpoint raw.githubusercontent.com:443:full \
  --add-endpoint codeload.github.com:443:full \
  --add-endpoint services.nvd.nist.gov:443:full \
  --add-endpoint api.osv.dev:443:full \
  --binary /usr/local/bin/python3 --binary /usr/bin/python3 \
  --binary /usr/bin/curl --binary /usr/local/bin/node --binary /usr/bin/node \
  --wait --timeout 60 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE "submitted|loaded|error|denied" || true
v="$(openshell policy get "$SB" 2>&1 | awk '/^Active:/{print $2}')"
echo "[allow-gh] ✓ $SB github allow 就緒(active policy v${v:-?})"
