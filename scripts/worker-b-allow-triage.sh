#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# worker-b-allow-triage.sh — make worker-b's SAST triage egress to the LOCAL vLLM explicit & governed.
#
# worker-b's Semgrep findings are triaged by Nemotron, which worker-itops calls directly at the local
# vLLM (host.openshell.internal:8000 → the host's OpenAI /v1). That call must be a *scoped, auditable*
# OpenShell egress rule (localhost inference only, python only) rather than relying on default host
# reachability — so it shows up as ALLOWED [policy:sast_triage] in the OCSF log and can't drift into
# arbitrary host access. Idempotent (merge semantics); boot-stack re-runs it after a rebuild.
set -uo pipefail
SB="${WORKERB_SANDBOX:-worker-b}"
command -v openshell >/dev/null 2>&1 || { echo "[triage] openshell CLI 不可用" >&2; exit 1; }
openshell policy get "$SB" >/dev/null 2>&1 || { echo "[triage] 沙箱 $SB 未就緒(略過)"; exit 0; }
openshell policy update "$SB" \
  --add-endpoint host.openshell.internal:8000:full \
  --binary /usr/bin/python3 --binary /usr/local/bin/python3 \
  --wait --timeout 60 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE "submitted|loaded|error|denied" || true
v="$(openshell policy get "$SB" 2>&1 | awk '/^Active:/{print $2}')"
echo "[triage] ✓ $SB 允許 SAST triage → 本地 vLLM(host.openshell.internal:8000;python only;active v${v:-?})"
