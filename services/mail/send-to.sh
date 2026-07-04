#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# send-to.sh — send a notification email to any recipient via the real SMTP relay (.env).
# Used when a manager is added as a notify recipient (welcome / test mail).
# Usage: send-to.sh <to-addr> "<subject>" "<body>" [from-addr]
set -euo pipefail
TO="${1:?need to}"; SUBJ="${2:?need subject}"; BODY="${3:?need body}"; FROM="${4:-${SMTP_FROM:-}}"
python3 "$MAIL_DIR/send.py" "$TO" "$SUBJ" "$BODY" "$FROM"
