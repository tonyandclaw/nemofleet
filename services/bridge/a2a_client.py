#!/usr/bin/env python3
# a2a_client.py — minimal A2A (Agent2Agent) client. team-lead uses this to DISCOVER a worker via its
# Agent Card, then DELEGATE a task via JSON-RPC message/send — the standard NVIDIA / Linux-Foundation
# A2A shape, over the governed worker_bridge channel (X-Bridge-Token). No external deps.
#
# Library:
#   c = A2AClient("http://127.0.0.1:9099", token); card = c.agent_card(); result = c.send("monitor")
# CLI:
#   python3 a2a_client.py http://127.0.0.1:9099 card
#   python3 a2a_client.py http://127.0.0.1:9099 skills
#   python3 a2a_client.py http://127.0.0.1:9099 send monitor
#   python3 a2a_client.py http://127.0.0.1:9099 send remediate --bug ebg-wps
import sys, os, json, time
import urllib.request


class A2AClient:
    def __init__(self, base, token=None, timeout=30):
        self.base = base.rstrip("/")
        self.token = token if token is not None else os.environ.get("BRIDGE_TOKEN", "")
        self.timeout = timeout

    def _req(self, path, data=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Bridge-Token"] = self.token
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, headers=headers,
                                     method="POST" if data is not None else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=self.timeout).read().decode("utf-8", "replace"))  # nosemgrep: dynamic-urllib-use-detected — self.base is only ever an internal worker endpoint (127.0.0.1 or a peer IP from egress policy), never externally-supplied input

    def agent_card(self):
        """A2A capability discovery — the worker's public Agent Card (skills it can be delegated)."""
        return self._req("/.well-known/agent-card.json")

    def skills(self):
        return [s.get("id") for s in (self.agent_card().get("skills") or [])]

    def send(self, skill, **meta):
        """A2A message/send — delegate a skill to the worker; returns the unwrapped result."""
        rpc = {"jsonrpc": "2.0", "id": "1", "method": "message/send",
               "params": {"message": {"role": "user", "messageId": "m-" + str(int(time.time() * 1000)),
                          "parts": [{"kind": "text", "text": skill}], "metadata": dict(meta, skill=skill)}}}
        r = self._req("/a2a", rpc)
        if "error" in r:
            raise RuntimeError((r["error"] or {}).get("message", "a2a error"))
        task = r.get("result") or {}
        for art in (task.get("artifacts") or []):
            for p in (art.get("parts") or []):
                if p.get("kind") == "text":
                    try:
                        return json.loads(p["text"])
                    except Exception:
                        return p["text"]
        return task


def _main(argv):
    if len(argv) < 2:
        print("usage: a2a_client.py <base_url> card|skills|send [skill] [--bug X]", file=sys.stderr)
        return 2
    base, op, rest = argv[0], argv[1], argv[2:]
    c = A2AClient(base)
    if op == "card":
        print(json.dumps(c.agent_card(), ensure_ascii=False, indent=2)); return 0
    if op == "skills":
        print(" ".join(c.skills())); return 0
    if op == "send":
        skill = rest[0] if rest else ""
        meta = {"bug": rest[rest.index("--bug") + 1]} if "--bug" in rest else {}
        print(json.dumps(c.send(skill, **meta), ensure_ascii=False)); return 0
    print("unknown op " + op, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
