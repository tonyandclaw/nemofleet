#!/usr/bin/env python3
# jira-mock.py — 本機 mock Jira / ITSM endpoint(demo 用)。跑在 host,沙箱經 host.openshell.internal:3690 觸達。
# 真環境換成公司 Jira REST(/rest/api/2/issue);出站一樣受 OpenShell `policy:jira` egress 治理,
# 故 demo 的「修不了→開 Jira」會在 OpenClaw OPA log 留下 ALLOWED ... host.openshell.internal:3690 [policy:jira]。
import json, os, time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 3690
STORE = "/tmp/jira-mock-issues.jsonl"
SEQ = {"n": 0}

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        SEQ["n"] += 1
        key = f"NETOPS-{1000 + SEQ['n']}"
        rec = {"key": key, "received": time.strftime("%Y-%m-%d %H:%M:%S"),
               "fields": body.get("fields", body)}
        with open(STORE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[jira-mock] created {key}: {rec['fields'].get('summary','')[:60]}", flush=True)
        self._send(201, {"id": str(10000 + SEQ["n"]), "key": key,
                         "self": f"http://host.openshell.internal:{PORT}/rest/api/2/issue/{key}"})
    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "ok", "service": "jira-mock", "port": PORT})
        issues = []
        if os.path.exists(STORE):
            issues = [json.loads(l) for l in open(STORE, encoding="utf-8") if l.strip()]
        self._send(200, {"total": len(issues), "issues": issues[-20:]})
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    print(f"[jira-mock] listening on 0.0.0.0:{PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
