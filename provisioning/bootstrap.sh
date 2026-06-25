#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# bootstrap.sh — deterministic first-time setup on a fresh device.
# Does the parts that DON'T need interactive credentials. The sandbox onboarding
# (NemoClaw/OpenShell install + Hermes/OpenClaw creation) is interactive — see
# provisioning/install-prereqs.md.
set -uo pipefail
cd "$NEMOFLEET_ROOT"
ok(){ printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$1"; }
info(){ printf '  • %s\n' "$1"; }

echo "== nemofleet bootstrap =="
echo "root: $NEMOFLEET_ROOT"

# 1) prerequisite check (don't fail hard — report)
echo "-- prerequisites --"
for c in docker node nemoclaw openshell python3 openssl uv ss; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c"; else warn "$c not found (see provisioning/install-prereqs.md)"; fi
done

# 2) local config
echo "-- config --"
if [ ! -f "$NEMOFLEET_ROOT/.env" ]; then
  cp "$NEMOFLEET_ROOT/.env.example" "$NEMOFLEET_ROOT/.env"; ok ".env created from .env.example (edit as needed)"
else ok ".env already present"; fi

# seed non-secret dashboard auth defaults (users self-seed on first dashboard run)
if [ ! -f "$BRIDGE_DIR/dash-auth.json" ]; then
  cp "$CONFIG_DIR/bridge/dash-auth.example.json" "$BRIDGE_DIR/dash-auth.json"; ok "seeded services/bridge/dash-auth.json"
fi

# 3) secrets (regenerated locally, never committed)
echo "-- secrets / certs --"
if [ ! -f "$BRIDGE_TOKEN_FILE" ]; then
  if [ -x "$SCRIPTS_DIR/rotate-bridge-token.sh" ]; then
    bash "$SCRIPTS_DIR/rotate-bridge-token.sh" >/dev/null 2>&1 && ok "bridge token generated" \
      || { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$BRIDGE_TOKEN_FILE"; ok "bridge token generated (fallback)"; }
  else head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$BRIDGE_TOKEN_FILE"; ok "bridge token generated"; fi
else ok "bridge token present"; fi
if [ ! -f "$BRIDGE_DIR/dash-cert.pem" ]; then
  ( bash "$SCRIPTS_DIR/gen-dash-ca.sh" && bash "$SCRIPTS_DIR/gen-dash-tls.sh" ) >/dev/null 2>&1 \
    && ok "dashboard CA + TLS generated" || warn "dashboard cert gen skipped (run: make gen-certs)"
else ok "dashboard certs present"; fi

echo
echo "== bootstrap done. Next: =="
info "1. Install + onboard the sandboxes:  less provisioning/install-prereqs.md"
info "2. Email channel (optional):         bash services/mail/up.sh"
info "3. Bring the stack up:               make boot && make health"
