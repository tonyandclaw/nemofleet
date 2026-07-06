#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# worker-b-allow-triage.sh — make the workers' LOCAL-NIM egress explicit & governed.
#
# Two worker-itops features call the local vLLM directly (host.openshell.internal:8000 → the host's
# OpenAI /v1): worker-b's SAST triage (Nemotron reviews Semgrep findings) and the request GUARDRAIL
# (screens inbound requests for prompt-injection / destructive intent before /fix acts). Both must be
# a *scoped, auditable* OpenShell egress rule (localhost inference only, python only) rather than
# relying on default host reachability — so they log as ALLOWED [policy] in OCSF and can't drift into
# arbitrary host access. Applied to worker-a (guardrail gate on /fix) + worker-b (triage + guardrail).
# Idempotent (merge semantics); boot-stack re-runs it after a rebuild.
set -uo pipefail
command -v openshell >/dev/null 2>&1 || { echo "[nim-egress] openshell CLI 不可用" >&2; exit 1; }
for SB in ${TRIAGE_SANDBOXES:-worker-a worker-b}; do
  openshell policy get "$SB" >/dev/null 2>&1 || { echo "[nim-egress] 沙箱 $SB 未就緒(略過)"; continue; }
  openshell policy update "$SB" \
    --add-endpoint host.openshell.internal:8000:full \
    --binary /usr/bin/python3 --binary /usr/local/bin/python3 \
    --wait --timeout 60 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE "submitted|loaded|error|denied" || true
  v="$(openshell policy get "$SB" 2>&1 | awk '/^Active:/{print $2}')"
  echo "[nim-egress] ✓ $SB 允許 triage/guardrail → 本地 vLLM(host.openshell.internal:8000;python only;active v${v:-?})"
done
