#!/usr/bin/env python3
# wi_flow.py — cross-node work-flow event ring for the GUI Flow view: who (node) was delegated by whom
# (peer) to do what, and the status. Pure ring + a small API; the host injects its zone once via
# configure(). Kept tiny + side-effect-free so it unit-tests directly.
import time

FLOW = []
_zone = "a"


def configure(zone):
    global _zone
    _zone = (zone or "a").lower()


def flow(peer, task, status, detail="", node=None):
    FLOW.append({"ts": time.strftime("%H:%M:%S"), "node": node or ("worker-" + _zone), "peer": peer,
                 "task": str(task)[:40], "status": status, "detail": str(detail)[:100]})
    del FLOW[:-60]
    return FLOW[-1]


def recent(n=40):
    return FLOW[-n:]
