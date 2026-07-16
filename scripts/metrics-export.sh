#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# metrics-export.sh — render the fleet's governance / security / ops state as Prometheus exposition
# text, so an enterprise's existing Prometheus + Grafana + Alertmanager scrapes nemofleet like any
# other target (northbound observability — the NetOps/SRE-facing integration).
#
# Emits only counts / gauges — never secrets, tokens, or request contents — so it is safe to scrape.
#
# Usage (the standard node_exporter textfile-collector pattern — no new auth surface):
#   # cron / systemd timer, write atomically into the collector directory:
#   bash scripts/metrics-export.sh > /var/lib/node_exporter/textfile_collector/nemofleet.prom.$$ \
#     && mv /var/lib/node_exporter/textfile_collector/nemofleet.prom.$$ \
#           /var/lib/node_exporter/textfile_collector/nemofleet.prom
#   # or to stdout for inspection:
#   bash scripts/metrics-export.sh
# For a directly-scraped /metrics endpoint, front this with your existing exporter sidecar.
set -uo pipefail
export NEMOFLEET_ROOT
case "${1:-}" in -h|--help) sed -n '6,18p' "$0"; exit 0 ;; esac

python3 - <<'PYEOF'
import os, sys, importlib.util
root = os.environ["NEMOFLEET_ROOT"]
sys.path.insert(0, os.path.join(root, "services", "bridge"))
import prom
spec = importlib.util.spec_from_file_location("dash", os.path.join(root, "services/bridge/agent-dashboard.py"))
dash = importlib.util.module_from_spec(spec); spec.loader.exec_module(dash)
d = dash.collect()
# collect() only fills _audit.chain in the admin HTTP branch; add the real chain status host-side so
# the tamper-evident-ledger gauge is populated for the scraper too.
try:
    d.setdefault("_audit", {})["chain"] = dash.verify_audit()
except Exception:
    pass
sys.stdout.write(prom.render(d))
PYEOF
