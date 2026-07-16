#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# siem-export.sh — emit the fleet's current security/governance events as OCSF NDJSON for a SIEM.
#
# OCSF (Open Cybersecurity Schema Framework) is the schema Splunk / Elastic / Microsoft Sentinel ingest.
# Each finding is tagged with the right MITRE framework (ATLAS for LLM-layer guardrail attacks, ATT&CK
# for network detections, D3FEND for the defensive remediations) so a SOC analyst can pivot on technique
# IDs. Runs on the host beside the dashboard; a forwarder (Vector / Fluent Bit / Splunk UF) pipes stdout.
#
# Usage:
#   bash scripts/siem-export.sh                         # OCSF NDJSON to stdout
#   bash scripts/siem-export.sh > /var/log/nemofleet-ocsf.ndjson   # for a file-tailing forwarder
#   bash scripts/siem-export.sh | curl -k https://splunk:8088/services/collector/raw \
#        -H "Authorization: Splunk $HEC_TOKEN" --data-binary @-      # push to Splunk HEC
# Schedule it (cron / systemd timer) at your SOC's ingestion cadence.
set -uo pipefail
export NEMOFLEET_ROOT
case "${1:-}" in -h|--help) sed -n '6,20p' "$0"; exit 0 ;; esac

python3 - <<'PYEOF'
import os, sys, importlib.util
root = os.environ["NEMOFLEET_ROOT"]
sys.path.insert(0, os.path.join(root, "services", "bridge"))
import ocsf
spec = importlib.util.spec_from_file_location("dash", os.path.join(root, "services/bridge/agent-dashboard.py"))
dash = importlib.util.module_from_spec(spec); spec.loader.exec_module(dash)
recs = ocsf.emit(dash.collect())
out = ocsf.to_ndjson(recs)
if out:
    sys.stdout.write(out + "\n")
sys.stderr.write("[siem-export] %d OCSF finding(s) emitted\n" % len(recs))
PYEOF
