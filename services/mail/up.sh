#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# up.sh — validate the real SMTP relay config (.env). No mock container to bring up:
# outbound notifications go directly to the real SMTP relay via services/mail/send.py;
# the team-lead's inbound email adapter polls TEAMLEAD_EMAIL over governed egress.
set -uo pipefail
ok(){   printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn(){ printf '  \033[33m⚠\033[0m %s\n' "$1"; }
if [ -n "${SMTP_HOST:-}" ] && [ -n "${SMTP_FROM:-}" ]; then
  ok "SMTP relay: $SMTP_FROM via $SMTP_HOST:${SMTP_PORT:-587} (STARTTLS=${SMTP_STARTTLS:-1})"
else
  warn "SMTP not configured — set SMTP_HOST / SMTP_FROM (+ SMTP_USER/PASS) in .env for outbound notifications"
fi
[ -n "${TEAMLEAD_EMAIL:-}" ] && ok "team-lead mailbox: $TEAMLEAD_EMAIL" \
  || warn "TEAMLEAD_EMAIL unset — Telegram-forward-via-email path disabled"
