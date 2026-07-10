#!/usr/bin/env bash
# --- nemofleet: locate repo root + load shared library ---
__src="${BASH_SOURCE[0]:-$0}"; __dir="$(cd "$(dirname "$(readlink -f "$__src" 2>/dev/null || echo "$__src")")" && pwd)"
while [ "$__dir" != / ] && [ ! -e "$__dir/.nemofleet-root" ]; do __dir="$(dirname "$__dir")"; done
NEMOFLEET_ROOT="$__dir"; DIR="$NEMOFLEET_ROOT"; . "$NEMOFLEET_ROOT/lib/common.sh"
# eval-scheduler.sh — recurring heartbeat (host-side, same pattern as teamlead-proactive.sh) that
# runs eval/eval.sh on an interval so eval/ledgers/history.jsonl accumulates real trend data over
# time instead of only being scored when someone remembers to run it by hand.
# Interval: EVAL_INTERVAL_SEC (default 21600 = 6h), overridable via .env. A trigger file
# (data/eval-trigger, same convention as data/proactive-trigger) forces an out-of-cycle run.
set -uo pipefail
DIR=$NEMOFLEET_ROOT
log(){ printf '[eval-sched %s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }   # stderr: keep stdout free for eval.sh's own output

TRIGGER="$DATA_DIR/eval-trigger"
INTERVAL="${EVAL_INTERVAL_SEC:-21600}"
log "eval 排程啟動(每 ${INTERVAL}s;history: $DIR/eval/ledgers/history.jsonl)"
while true; do
  bash "$DIR/eval/eval.sh" >>"$DIR/data/eval-run.log" 2>&1 || log "本輪 eval 未全過(見 data/eval-run.log / eval/ledgers/LEDGER.md)"
  waited=0
  while [ "$waited" -lt "$INTERVAL" ]; do
    [ -f "$TRIGGER" ] && { rm -f "$TRIGGER"; log "手動觸發 eval(dashboard)"; break; }
    sleep 20; waited=$((waited + 20))
  done
done
