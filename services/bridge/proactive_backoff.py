#!/usr/bin/env python3
# proactive_backoff.py — auto-mode cadence aging for team-lead's proactive patrol (teamlead-proactive.sh).
# Pure functions, no I/O → unit-tested. The bash loop imports this to decide the next patrol interval.
#
# Model: in AUTO mode the patrol starts at a 5-minute base cadence and "ages" toward a 12-hour cap.
#   - The alert STATE CHANGES cycle-to-cycle (a genuinely new critical/warning, or a problem clearing)
#     → reset to the base cadence, so a new event is picked up quickly.
#   - The alert STATE is UNCHANGED (the same error/warning repeating — an unresolved / unacknowledged
#     problem nobody has responded to) → age ×FACTOR, capped at MAX. So a stuck alert stops firing every
#     5 minutes and stretches out toward 12 hours instead of spamming.
import hashlib
import json

BASE_SEC = 300      # 5 minutes — auto-mode base cadence
MAX_SEC = 43200     # 12 hours — the most it ages to
FACTOR = 2          # each unchanged cycle doubles the interval (300→600→…→43200 in ~8 cycles)


def alert_signature(critical, warning, stale):
    """A stable fingerprint of the alert STATE — the set of critical + warning + stale messages. Two
    cycles reporting the same problems produce the same signature (order-independent); a new/cleared
    problem changes it. Deliberately excludes routine/summary noise and any timestamp."""
    payload = json.dumps({"c": sorted(critical or []), "w": sorted(warning or []), "s": sorted(stale or [])},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def next_auto_interval(prev_interval, prev_sig, critical, warning, stale,
                       base=BASE_SEC, cap=MAX_SEC, factor=FACTOR):
    """Return {"interval", "signature", "changed"} for the NEXT patrol.
    changed → reset to base (responsive); unchanged → min(prev*factor, cap) (age toward the cap)."""
    sig = alert_signature(critical, warning, stale)
    changed = (not prev_sig) or (sig != prev_sig)
    if changed:
        interval = base
    else:
        try:
            prev = int(prev_interval)
        except (TypeError, ValueError):
            prev = base
        interval = min(max(prev, base) * factor, cap)
    return {"interval": interval, "signature": sig, "changed": changed}
