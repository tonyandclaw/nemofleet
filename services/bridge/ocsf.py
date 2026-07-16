# ocsf.py — map nemofleet's security/governance events into OCSF (Open Cybersecurity Schema Framework)
# Detection Findings so an enterprise SIEM (Splunk / Elastic / Microsoft Sentinel) can ingest them, and
# tag each with the right MITRE framework so a SOC analyst can pivot on technique IDs:
#   · LLM-layer guardrail attacks  → MITRE ATLAS   (the AI-specific threat framework)
#   · network / device detections  → MITRE ATT&CK  (Enterprise — attacker behaviours)
#   · defensive remediations       → MITRE D3FEND  (the countermeasure taxonomy)
#
# Pure (json + datetime only, no host state) + direct-import (like wi_util) → fully unit-testable. The
# records are OCSF-ALIGNED: they carry the OCSF Detection Finding (class_uid 2004) core fields and put
# nemofleet-native detail + the framework tags under `unmapped` (the OCSF-sanctioned place for
# product-specific data). The MITRE mappings are a documented best-effort, not an authoritative catalog.
import json
from datetime import datetime, timezone

OCSF_VERSION = "1.3.0"
PRODUCT = {"name": "nemofleet", "vendor_name": "nemofleet"}

# nemofleet signal → (technique_id, name). ATT&CK Enterprise: what an attacker would be doing.
ATTACK = {
    "login_lock":    ("T1110", "Brute Force"),
    "login_fail":    ("T1110", "Brute Force"),
    "offhours_admin":("T1078", "Valid Accounts"),
    "denied_spike":  ("T1071", "Application Layer Protocol (C2 / exfil, blocked)"),
    "destructive":   ("T1485", "Data Destruction"),
}
# guardrail category → MITRE ATLAS (LLM / AI-agent attacks).
ATLAS = {
    "prompt_injection": ("AML.T0051", "LLM Prompt Injection"),
    "jailbreak":        ("AML.T0054", "LLM Jailbreak"),
}
# defensive-action class → MITRE D3FEND (the countermeasure).
D3FEND = {
    "surface-reduction": ("D3-ACH", "Application Configuration Hardening"),
    "traffic-filtering": ("D3-NTF", "Network Traffic Filtering"),
    "config-restore":    ("D3-ACH", "Application Configuration Hardening"),
}
# EBG remediation id → which D3FEND class it realises (for per-remediation tagging when fix events are fed in).
REMEDIATION_D3FEND = {
    "ebg-telnet": "surface-reduction", "ebg-ssh": "surface-reduction", "ebg-wanweb": "surface-reduction",
    "ebg-upnp": "surface-reduction", "ebg-samba": "surface-reduction", "ebg-ftp": "surface-reduction",
    "ebg-ddns": "surface-reduction", "ebg-wps": "surface-reduction",
    "ebg-dos": "traffic-filtering", "ebg-fw-on": "traffic-filtering", "ebg-aiprotect": "traffic-filtering",
}

# nemofleet severity → OCSF severity_id / label
_SEV = {"critical": (5, "Critical"), "high": (4, "High"), "warn": (3, "Medium"),
        "medium": (3, "Medium"), "low": (2, "Low"), "info": (1, "Informational")}


def _sev(s):
    return _SEV.get((s or "info").lower(), (1, "Informational"))


def _epoch_ms(ts):
    # parse the fleet's "YYYY-MM-DD[ T]HH:MM:SS" stamps as UTC → deterministic epoch ms (no host-tz drift)
    if not ts:
        return None
    s = str(ts).replace("T", " ").strip()[:19]
    try:
        return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        return None


def _finding(ftype, title, sev, ts, message, observables, native, attack=None, atlas=None, d3fend=None):
    sid, sname = _sev(sev)
    rec = {
        "class_uid": 2004, "class_name": "Detection Finding",
        "category_uid": 2, "category_name": "Findings",
        "type_uid": 200401, "activity_id": 1, "activity_name": "Create",
        "severity_id": sid, "severity": sname,
        "time": _epoch_ms(ts), "time_dt": (str(ts).replace("T", " ") if ts else None),
        "message": message,
        "metadata": {"product": PRODUCT, "version": OCSF_VERSION, "profiles": ["security_control"]},
        "finding_info": {"title": title, "types": [ftype]},
        "observables": observables or [],
        "unmapped": {"nemofleet": native},
    }
    mitre = {}
    if attack:  mitre["attack"] = [{"technique_id": attack[0], "technique": attack[1]}]
    if atlas:   mitre["atlas"] = [{"technique_id": atlas[0], "technique": atlas[1]}]
    if d3fend:  mitre["d3fend"] = [{"technique_id": d3fend[0], "technique": d3fend[1]}]
    if mitre:
        rec["unmapped"]["mitre"] = mitre
    return rec


def guardrail_findings(gr):
    """d['guardrail']['recent'] → OCSF findings. Blocks are High findings tagged ATLAS (prompt-injection /
    jailbreak) or ATT&CK (destructive). A fail-open (NIM down → passed unscreened) is a Medium governance
    finding. Plain allows are dropped (not security-relevant noise for a SOC)."""
    out = []
    for g in (gr.get("recent") or []):
        cat = g.get("category") or ""
        if g.get("verdict") == "block":
            out.append(_finding("Guardrail", "Guardrail blocked a request: %s" % (cat or "?"),
                "high", g.get("ts"), g.get("reason") or "",
                [{"name": "request.excerpt", "type": "Other", "type_id": 0, "value": (g.get("excerpt") or "")[:120]}],
                {"gate": g.get("gate"), "verdict": "block", "category": cat, "by": g.get("by"),
                 "fail_open": bool(g.get("fail_open")), "reason": g.get("reason")},
                attack=ATTACK.get(cat), atlas=ATLAS.get(cat)))
        elif g.get("fail_open"):
            out.append(_finding("Guardrail", "Guardrail fail-open — request passed unscreened (NIM down)",
                "warn", g.get("ts"), g.get("reason") or "guardrail unreachable",
                [], {"gate": g.get("gate"), "verdict": g.get("verdict"), "category": cat, "fail_open": True}))
    return out


def anomaly_findings(alerts, now=None):
    """detect_anomalies() output → OCSF findings. Attacker-behaviour kinds (brute force, off-hours admin,
    blocked-egress spike) carry an ATT&CK tag; operational kinds (device_cpu/ram/temp/offline, port_down)
    are emitted without one (honest — they aren't attacks)."""
    out = []
    for a in (alerts or []):
        kind = a.get("kind") or ""
        msg = a.get("msg_en") or a.get("msg") or kind
        out.append(_finding("Anomaly", msg, a.get("sev") or "warn", now, msg,
            [], {"id": a.get("id"), "kind": kind, "sev": a.get("sev"), "msg": msg},
            attack=ATTACK.get(kind)))
    return out


def governance_findings(gc):
    """d['governance_c'] → OCSF findings: config rollbacks (Remediation, tagged D3FEND config-restore) and
    QA-review verdicts (Governance). Rollbacks that failed read-back verification are High."""
    out = []
    gc = gc or {}
    for rb in gc.get("rollbacks", []):
        ok = bool(rb.get("ok") and rb.get("verified"))
        out.append(_finding("Remediation", "Config rollback → %s" % (rb.get("restored_to") or "?"),
            "warn" if ok else "high", rb.get("ts"),
            "rollback restored_to=%s verified=%s" % (rb.get("restored_to"), rb.get("verified")),
            [], {"restored_to": rb.get("restored_to"), "ok": rb.get("ok"), "verified": rb.get("verified")},
            d3fend=D3FEND["config-restore"]))
    for r in gc.get("reviews", []):
        ok = r.get("verdict") == "approve"
        out.append(_finding("Governance", "QA review %s: %s" % (r.get("verdict") or "?", r.get("ref") or ""),
            "info" if ok else "warn", r.get("ts_iso") or r.get("ts"),
            "%s %s → %s (score %s)" % (r.get("kind", ""), r.get("ref", ""), r.get("verdict", ""), r.get("score", "")),
            [], {"target": r.get("target"), "ref": r.get("ref"), "verdict": r.get("verdict"), "score": r.get("score")}))
    return out


def emit(d):
    """The whole fleet's current security/governance events as OCSF findings, from a collect() payload."""
    d = d or {}
    out = []
    out += guardrail_findings(d.get("guardrail") or {})
    out += anomaly_findings(d.get("alerts_list") or d.get("alerts") or [], d.get("now"))
    out += governance_findings(d.get("governance_c") or {})
    return out


def to_ndjson(records):
    # newline-delimited JSON — the lingua franca SIEM HTTP collectors (Splunk HEC, Elastic bulk) ingest.
    return "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in (records or []))
