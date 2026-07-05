#!/usr/bin/env python3
# wi_nuclei.py — worker-b active vulnerability scanning with projectdiscovery/nuclei + nuclei-templates.
# Cohesive subsystem: owns LAST_NUCLEI and the scan / schedule logic. Its dependencies on the host
# endpoint (zone check, live settings, Jira escalation) are injected once via configure(), so this
# module stays decoupled. Co-located — boot-stack cp's it next to worker-itops.py.
import os
import json
import time
import shutil
import subprocess

NUCLEI_INTERVAL = int(os.environ.get("BRIDGE_NUCLEI_INTERVAL", "86400"))
NUCLEI_TARGET = os.environ.get("EBG19P_TARGET", "").strip()
NUCLEI_TAGS = os.environ.get("BRIDGE_NUCLEI_TAGS", "asus").strip()
# Templates are pre-seeded into the sandbox at a fixed path (worker-b-install-nuclei.sh docker cp's
# them there) so a scan never has to phone home to update templates — the sandbox is deny-by-default.
NUCLEI_TEMPLATES = os.environ.get("NUCLEI_TEMPLATES_DIR", "/usr/local/share/nuclei-templates").strip()
LAST_NUCLEI = {}
_deps = {"zone_has": lambda c: False, "load_settings": lambda: {},
         "open_jira": lambda *a, **k: None, "zone": "?"}


def configure(zone_has, load_settings, open_jira, zone):
    """Inject the host endpoint's helpers + this worker's zone (called once at startup)."""
    _deps.update(zone_has=zone_has, load_settings=load_settings, open_jira=open_jira, zone=zone)


def _parse_nuclei(jsonl):
    """nuclei -jsonl 輸出 → 正規化 findings(純函式，可單元測試)。"""
    out = []
    for line in (jsonl or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        info = r.get("info") or {}
        cls = info.get("classification") or {}
        cves = cls.get("cve-id") or cls.get("cve_id") or []
        if isinstance(cves, str):
            cves = [cves]
        ref = info.get("reference")
        out.append({
            "template": r.get("template-id") or r.get("templateID") or "",
            "name": info.get("name") or "",
            "severity": (info.get("severity") or "unknown").lower(),
            "matched_at": r.get("matched-at") or r.get("host") or "",
            "type": r.get("type") or "",
            "cve": [c.upper() for c in cves if c],
            "reference": ref[:3] if isinstance(ref, list) else [],
        })
    return out


def run_nuclei_scan(trigger="api"):
    """worker-b 用 nuclei-templates 主動掃 EBG19P。高/嚴重命中 → 開真實 Jira(依 auto_escalate)。"""
    global LAST_NUCLEI
    if not _deps["zone_has"]("nuclei"):
        return {"available": False, "note": "非資安節點(僅 zone B 跑 nuclei)", "zone": _deps["zone"]}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not shutil.which("nuclei"):
        LAST_NUCLEI = {"available": False, "note": "nuclei 未安裝於 worker-b 沙箱(OpenShell binaries policy 需允許 nuclei)", "ts": now}
        return LAST_NUCLEI
    if not NUCLEI_TARGET:
        LAST_NUCLEI = {"available": False, "note": "無掃描目標(boot 需 -e EBG19P_TARGET=<ip> 給 worker-b + 開 worker-b→裝置 egress)", "ts": now}
        return LAST_NUCLEI
    url = NUCLEI_TARGET if NUCLEI_TARGET.startswith("http") else "http://" + NUCLEI_TARGET
    settings = _deps["load_settings"]()
    tags = (settings.get("nuclei_tags") or NUCLEI_TAGS or "asus").strip()
    cmd = ["nuclei", "-u", url, "-tags", tags, "-severity", "low,medium,high,critical",
           "-jsonl", "-silent", "-nc", "-timeout", "10", "-retries", "1", "-rate-limit", "50",
           "-duc"]  # disable the auto template-update check (no phone-home in the governed sandbox)
    if os.path.isdir(NUCLEI_TEMPLATES):
        cmd += ["-t", NUCLEI_TEMPLATES]        # pinned, pre-seeded template set
    # nuclei writes its config/cache under $HOME; the sandbox service user's HOME may be unwritable,
    # so point it at /tmp which always is.
    env = dict(os.environ, HOME=os.environ.get("NUCLEI_HOME", "/tmp"))
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        LAST_NUCLEI = {"available": True, "target": url, "note": "nuclei 逾時(600s)", "count": 0, "findings": [], "ts": now}
        return LAST_NUCLEI
    except Exception as e:
        LAST_NUCLEI = {"available": False, "note": "nuclei 執行失敗:%s" % e, "ts": now}
        return LAST_NUCLEI
    findings = _parse_nuclei(p.stdout)
    counts = {}
    for fnd in findings:
        counts[fnd["severity"]] = counts.get(fnd["severity"], 0) + 1
    opened = []
    if settings.get("auto_escalate", True):
        for fnd in findings:
            if fnd["severity"] in ("high", "critical"):
                tid = _deps["open_jira"](
                    "[nuclei] %s (%s)" % (fnd["name"], ", ".join(fnd["cve"]) or fnd["template"]),
                    "nuclei 主動掃描命中:%s\ntemplate=%s severity=%s\nmatched=%s\ntarget=%s" % (
                        fnd["name"], fnd["template"], fnd["severity"], fnd["matched_at"], url),
                    "nuclei", "lab-asus-ebg19p-01", "High")
                if tid:
                    opened.append({"template": fnd["template"], "ticket": tid})
    LAST_NUCLEI = {"available": True, "target": url, "tags": tags, "count": len(findings),
                   "counts": counts, "findings": findings[:50], "escalated": opened,
                   "schedule_interval_sec": settings.get("nuclei_interval_sec", NUCLEI_INTERVAL),
                   "trigger": trigger, "ts": now}
    print("[NUCLEI] %s findings on %s (%s)" % (len(findings), url, counts), flush=True)
    return LAST_NUCLEI


def schedule_loop():
    """worker-b nuclei 排程:就緒後先掃一輪,之後每 nuclei_interval_sec 秒掃一次(0=暫停)。"""
    time.sleep(30)
    while True:
        iv = NUCLEI_INTERVAL
        try:
            iv = int(_deps["load_settings"]().get("nuclei_interval_sec", NUCLEI_INTERVAL) or 0)
            if iv > 0:
                run_nuclei_scan("schedule")
            else:
                iv = 3600
        except Exception as e:
            print("[NUCLEI] loop error:", e, flush=True); iv = 3600
        time.sleep(max(iv, 60))
