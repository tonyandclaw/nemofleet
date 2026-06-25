#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# relay.sh — send a message to an agent's OpenAI-compatible API and record it on the bus.
# Usage: relay.sh <hermes> "<message>" [max_tokens]
# hermes 腿:Azure Kimi via :8642(round1 已驗證)。openclaw 無入站 OpenAI API(round2 查明,
# :18789 是 Control UI),openclaw 腿改走 dispatch.sh / openclaw-cp-task.sh(✅ 端到端)——本腳本僅服務 hermes。
set -euo pipefail

:
BUS="$BUS_DIR"
mkdir -p "$BUS/inbox" "$BUS/outbox"
TARGET="${1:?target required: hermes|openclaw}"
MSG="${2:?message required}"
MAXTOK="${3:-256}"
# deterministic-ish id without Date.now in scripts is fine here (bash, not workflow)
ID="$(date +%s)-$$"

case "$TARGET" in
  hermes)   URL="$HERMES_API/chat/completions";  MODEL="hermes-agent" ;;
  openclaw) echo "[relay] openclaw has NO inbound OpenAI API (:18789 is Control UI). Use dispatch.sh / openclaw-cp-task.sh all instead. See design/combined-use-case.md" >&2; exit 3 ;;
  *) echo "unknown target: $TARGET" >&2; exit 2 ;;
esac

printf '{"from":"relay","to":"%s","type":"task","content":%s,"ts":"%s"}\n' \
  "$TARGET" "$(printf '%s' "$MSG" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
  "$(date -Is)" > "$BUS/inbox/$ID.json"

REQ=$(python3 -c 'import json,sys;print(json.dumps({"model":sys.argv[1],"stream":False,"max_tokens":int(sys.argv[3]),"messages":[{"role":"user","content":sys.argv[2]}]}))' "$MODEL" "$MSG" "$MAXTOK")

RESP=$(curl -sS -m 600 "$URL" -H "Content-Type: application/json" -d "$REQ" || echo '{"error":"request failed"}')
echo "$RESP" > "$BUS/outbox/$ID.json"

# print just the assistant content if present
printf '%s' "$RESP" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"])
except Exception: print("[relay] non-standard response, see $BUS_DIR/outbox]")' 2>/dev/null || true
echo "[relay] target=$TARGET id=$ID  ($BUS_DIR/outbox/$ID.json)" >&2
