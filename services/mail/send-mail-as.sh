#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# send-mail-as.sh — deliver a message into the team-lead's mailbox as a given sender.
# The dashboard uses this to ask the team-lead to forward a Telegram push (the lead's
# email adapter polls TEAMLEAD_EMAIL). Real SMTP relay from .env.
# Usage: send-mail-as.sh <from-addr> "<subject>" "<body>"
set -euo pipefail
FROM="${1:?need from addr}"; SUBJ="${2:?need subject}"; BODY="${3:?need body}"
TO="${TEAMLEAD_EMAIL:?set TEAMLEAD_EMAIL in .env (team-lead mailbox address)}"
python3 "$MAIL_DIR/send.py" "$TO" "$SUBJ" "$BODY" "$FROM"
