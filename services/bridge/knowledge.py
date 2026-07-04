#!/usr/bin/env python3
# knowledge.py — the fleet's single source of shared KNOWLEDGE. team-lead + workers all read the
# SAME facts through here: the approved EBG19P baseline (what "correct" looks like), the security-key
# definitions (what counts as a regression), the sedimented lessons, and the live fleet snapshot.
#
# This is the "shared context layer" — what keeps a multi-agent fleet from each-agent-knowing-
# different-facts (the #1 multi-agent-orchestration failure). Native + dependency-free: worker-a's
# drift detection reads the SAME baseline/security-keys team-lead pulls live via GET /knowledge (an
# A2A/MCP-shaped read), and boot syncs the canonical knowledge/ dir to every node. The full-MCP
# upgrade (agents mounting an MCP client) rides on top of this same content.
#
# Canonical layout (version-controlled under repo knowledge/):
#   knowledge/baselines/ebg19p.conf   — approved config baseline
#   knowledge/security-keys.json      — keys whose drift = security regression
# Env overrides (per node): KNOWLEDGE_DIR, LESSONS_FILE, FLEET_FILE.
import os
import json
import hashlib

_HERE = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR") or os.path.normpath(os.path.join(_HERE, "..", "..", "knowledge"))
LESSONS_FILE = os.environ.get("LESSONS_FILE") or os.path.normpath(os.path.join(_HERE, "..", "..", "eval", "lessons.json"))
FLEET_FILE = os.environ.get("FLEET_FILE") or os.path.normpath(os.path.join(_HERE, "..", "..", "data", "proactive-status.json"))

# Embedded fallback so a worker still functions if the canonical dir was not synced to it.
_FALLBACK_BASELINE = "# (fallback) approved baseline unavailable — sync knowledge/ to this node\ndevice.model = EBG19P\n"
_FALLBACK_SECKEYS = {"ebg19p": ["ssh.password_login", "ssh.wan_access", "webui.http.enabled",
                                "webui.wan_access", "firewall.wan_to_lan.default",
                                "firewall.dos_protection", "upnp.enabled", "wps.enabled"]}


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default


def baseline_conf(asset_family="ebg19p"):
    """Approved config baseline (the canonical 'correct' state) for an asset family."""
    return _read(os.path.join(KNOWLEDGE_DIR, "baselines", asset_family + ".conf")) or _FALLBACK_BASELINE


def security_keys(asset_family="ebg19p"):
    """Keys whose deviation from the baseline counts as a SECURITY regression (not a benign drift)."""
    try:
        d = json.loads(_read(os.path.join(KNOWLEDGE_DIR, "security-keys.json"), "{}")) or {}
    except Exception:
        d = {}
    return list(d.get(asset_family) or _FALLBACK_SECKEYS.get(asset_family) or [])


def _lessons_digest():
    try:
        d = json.loads(_read(LESSONS_FILE, "{}")) or {}
        items = d.items() if isinstance(d, dict) else []
        out = [{"id": k, "lesson": (v.get("lesson") or v.get("correction") or v.get("desc") or "")}
               for k, v in items if isinstance(v, dict)]
        return out[:20]
    except Exception:
        return []


def _fleet_snapshot():
    try:
        return json.loads(_read(FLEET_FILE, "{}")) or {}
    except Exception:
        return {}


def version():
    """Content hash of the canonical (version-controlled) knowledge — nodes compare this to confirm
    they agree on the same baseline + security-key definitions. Excludes live-varying lessons/fleet."""
    h = hashlib.sha256()
    h.update(baseline_conf().encode("utf-8"))
    h.update(json.dumps(security_keys(), sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:12]


def get_knowledge():
    """The full shared-knowledge bundle — what every agent should read identically."""
    return {
        "version": version(),
        "baseline": {"ebg19p": baseline_conf("ebg19p")},
        "security_keys": {"ebg19p": security_keys("ebg19p")},
        "lessons": _lessons_digest(),
        "fleet": _fleet_snapshot(),
        "sources": {"dir": KNOWLEDGE_DIR, "lessons": LESSONS_FILE, "fleet": FLEET_FILE},
    }


if __name__ == "__main__":
    print(json.dumps(get_knowledge(), ensure_ascii=False, indent=2))
