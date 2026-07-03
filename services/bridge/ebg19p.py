#!/usr/bin/env python3
# ebg19p.py — one client for the real ASUS ExpertWiFi EBG19P web API.
# Single source of truth for device access: imported by worker-itops.py (in-container)
# and shelled by the ebg19p-*-sync.sh scripts (host), so the login / token handling
# lives in exactly one place instead of being re-implemented per script.
#
# Library use:
#   c = EBG19PClient(ip, user, pw); c.login()
#   c.hook("get_clientlist()")                 -> raw response text
#   c.nvget("wps_enable")                       -> value string
#   c.apply("restart_wireless", [("wps_enable", "0")])
#   c = from_cred_file("~/.config/nemoclaw/ebg19p.cred")   # reads IP|USER|PASS
#
# CLI use (host sync scripts — one login, batched):
#   python3 ebg19p.py <cred_file> nvget wps_enable sshd_enable   -> {"wps_enable": "...", ...}
#   python3 ebg19p.py <cred_file> hooks 'get_clientlist()' 'netdev(appobj)'
import sys, os, json, re, base64
import urllib.request, urllib.parse, urllib.error

DEFAULT_CRED = os.environ.get("EBG19P_CRED", "~/.config/nemoclaw/ebg19p.cred")


class EBG19PError(Exception):
    pass


class EBG19PClient:
    """Read-only + governed-apply client for the EBG19P web API (login.cgi / appGet.cgi / applyapp.cgi)."""

    def __init__(self, ip, user, pw, timeout=10):
        self.ip, self.user, self.pw, self.timeout = ip, user, pw, timeout
        self.base = f"http://{ip}"
        self.token = None

    def login(self):
        cred = base64.b64encode(f"{self.user}:{self.pw}".encode()).decode()
        body = urllib.parse.urlencode({"login_authorization": cred}).encode()
        req = urllib.request.Request(
            f"{self.base}/login.cgi", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": f"{self.base}/Main_Login.asp"})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            for h in resp.headers.get_all("Set-Cookie") or []:
                m = re.search(r"asus_token=([A-Za-z0-9]+)", h)
                if m:
                    self.token = m.group(1)
                    return self.token
        except Exception as e:
            raise EBG19PError(f"login failed ({self.ip}): {e}")
        raise EBG19PError(f"login failed ({self.ip}): no asus_token in response")

    def _get(self, path):
        req = urllib.request.Request(
            f"{self.base}{path}",
            headers={"Cookie": f"asus_token={self.token}", "Referer": f"{self.base}/index.asp"})
        return urllib.request.urlopen(req, timeout=self.timeout).read().decode("utf-8", "replace")

    def hook(self, hook):
        if not self.token:
            self.login()
        return self._get(f"/appGet.cgi?hook={urllib.parse.quote(hook, safe='()\",')}")

    def nvget(self, key):
        """nvram_get(<key>) → the value string (parses the {\"key\": \"value\"} JSON reply)."""
        raw = self.hook(f"nvram_get({key})")
        return parse_nvram_value(raw)

    def apply(self, script, sets, wait=10):
        """applyapp.cgi: write nvram (one or more key=value) + run action_script. Returns raw response."""
        if not self.token:
            self.login()
        data = {"action_mode": "apply", "action_script": script, "action_wait": str(wait)}
        for k, v in sets:
            data[k] = v
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            f"{self.base}/applyapp.cgi", data=body,
            headers={"Cookie": f"asus_token={self.token}",
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Referer": f"{self.base}/index.asp"})
        return urllib.request.urlopen(req, timeout=self.timeout + wait).read().decode("utf-8", "replace")


def parse_nvram_value(raw):
    """Pull the value out of an appGet nvram_get reply. Pure function → unit-testable."""
    try:
        vals = list(json.loads(raw).values())
        if vals:
            return str(vals[0])
    except Exception:
        pass
    return (raw or "").strip()


def parse_cred(line):
    """Parse an 'IP|USER|PASS' cred line (pass may contain '|'). Pure function → unit-testable."""
    parts = (line or "").strip().split("|")
    if len(parts) < 3 or not parts[0] or not parts[1]:
        raise EBG19PError("cred format must be IP|USER|PASS (chmod 600)")
    return parts[0], parts[1], "|".join(parts[2:])


def from_cred_file(path=DEFAULT_CRED):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        ip, user, pw = parse_cred(f.read())
    return EBG19PClient(ip, user, pw)


def _main(argv):
    if len(argv) < 2:
        print("usage: ebg19p.py <cred_file> nvget|hooks <arg>...", file=sys.stderr)
        return 2
    cred, op, args = argv[0], argv[1], argv[2:]
    try:
        c = from_cred_file(cred)
        c.login()
    except EBG19PError as e:
        print(f"[ebg19p] {e}", file=sys.stderr)
        return 1
    out = {}
    for a in args:
        try:
            out[a] = c.nvget(a) if op == "nvget" else c.hook(a) if op == "hooks" else None
        except Exception:
            out[a] = None
    if op not in ("nvget", "hooks"):
        print(f"[ebg19p] unknown op {op}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
