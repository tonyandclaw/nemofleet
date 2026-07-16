# prom.py — render the fleet's governance / security / ops state as Prometheus exposition text so an
# enterprise's existing Prometheus + Grafana + Alertmanager scrapes nemofleet like any other target
# (northbound observability). Pure (reads a collect() dict, no host state) + direct-import → unit-tested.
#
# Alertmanager can fire the enterprise's existing on-call flow on these directly, e.g.:
#   nemofleet_node_up == 0            (a fleet node down)
#   nemofleet_nim_reachable == 0      (local NIM unreachable)
#   nemofleet_frozen == 1             (kill-switch engaged)
#   nemofleet_guardrail_fail_open > 0 (guardrail passed requests unscreened)
#   nemofleet_audit_chain_ok == 0     (tamper-evident ledger broken)
#   nemofleet_rollback_mismatch > 0   (a rollback failed read-back verification)

_ESC = str.maketrans({"\\": "\\\\", "\n": "\\n", '"': '\\"'})


def _lbl(v):
    return str(v).translate(_ESC)


def _fmt(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if v is None:
        return "0"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _metric(lines, name, mtype, help_, samples):
    # samples: list of (labels_dict_or_None, value). Emits HELP/TYPE once + one line per sample.
    if not samples:
        return
    lines.append("# HELP %s %s" % (name, help_))
    lines.append("# TYPE %s %s" % (name, mtype))
    for labels, val in samples:
        lbl = ""
        if labels:
            lbl = "{" + ",".join('%s="%s"' % (k, _lbl(v)) for k, v in labels.items() if v is not None) + "}"
        lines.append("%s%s %s" % (name, lbl, _fmt(val)))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def render(d):
    """collect() payload → Prometheus exposition text. Reads the raw collect() shape with the same
    fallbacks normalize() uses, so it works host-side. Only counts / gauges — never secrets, tokens,
    or request contents — so the endpoint is safe to expose to a scraper."""
    d = d or {}
    L = []
    _metric(L, "nemofleet_up", "gauge", "The nemofleet metrics exporter is running.", [(None, 1)])

    gov = d.get("governance") or d.get("gov") or {}
    _metric(L, "nemofleet_governance_allowed", "gauge", "Governed egress decisions ALLOWED (current window).", [(None, gov.get("allowed", 0))])
    _metric(L, "nemofleet_governance_denied", "gauge", "Egress blocked by policy (DENIED).", [(None, gov.get("denied", 0))])

    gr = d.get("guardrail") or {}
    _metric(L, "nemofleet_guardrail_screened", "gauge", "Inbound requests screened by the guardrail.", [(None, gr.get("count", 0))])
    _metric(L, "nemofleet_guardrail_blocked", "gauge", "Inbound requests blocked by the guardrail.", [(None, gr.get("blocked", 0))])
    _metric(L, "nemofleet_guardrail_fail_open", "gauge", "Guardrail fail-open events (NIM down → request passed unscreened).", [(None, gr.get("fail_open", 0))])

    nodes = d.get("nodes") or []
    _metric(L, "nemofleet_node_up", "gauge", "Fleet node reachable (1=up, 0=down).",
            [({"node": n.get("name"), "zone": (n.get("zone") or "").replace("zone ", "").strip() or "lead"},
              1 if n.get("up") else 0) for n in nodes if n.get("name")])

    inf = (d.get("sysinfo") or {}).get("inference") or {}
    _metric(L, "nemofleet_nim_reachable", "gauge", "Local NIM inference endpoint reachable (1=yes).", [(None, 1 if inf.get("reachable") else 0)])

    devs = d.get("devices") or []
    _metric(L, "nemofleet_device_online", "gauge", "Managed device online (1=yes).",
            [({"asset": dv.get("asset")}, 1 if dv.get("online") else 0) for dv in devs if dv.get("asset")])
    for suffix, key, help_ in (("cpu_percent", "cpu", "Managed device CPU load percent."),
                               ("mem_percent", "mem", "Managed device memory usage percent."),
                               ("temp_celsius", "temp", "Managed device temperature in Celsius.")):
        _metric(L, "nemofleet_device_" + suffix, "gauge", help_,
                [({"asset": dv.get("asset")}, _num(dv.get(key))) for dv in devs if dv.get("asset") and _num(dv.get(key)) is not None])

    chain = (d.get("_audit") or {}).get("chain") or d.get("audit") or {}
    if chain.get("ok") is not None:
        _metric(L, "nemofleet_audit_chain_ok", "gauge", "Tamper-evident audit chain verifies (1=ok, 0=broken).", [(None, 1 if chain.get("ok") else 0)])

    rbs = ((d.get("governance_c") or {}).get("rollbacks")) or []
    _metric(L, "nemofleet_rollback_mismatch", "gauge", "Rollbacks whose read-back verification mismatched.",
            [(None, sum(1 for r in rbs if (r.get("verify") or {}).get("mismatch")))])

    jira = d.get("jira")
    n_jira = len(jira.get("tickets") or []) if isinstance(jira, dict) else (len(jira) if isinstance(jira, list) else 0)
    _metric(L, "nemofleet_open_escalations", "gauge", "Open Jira/ITSM escalations awaiting a human.", [(None, n_jira)])

    _metric(L, "nemofleet_frozen", "gauge", "Kill-switch engaged / fleet frozen (1=frozen).", [(None, 1 if (d.get("frozen") or {}).get("frozen") else 0)])

    alerts = d.get("alerts_list") or d.get("alerts") or []
    bysev = {}
    for a in alerts:
        s = a.get("sev") or "info"
        bysev[s] = bysev.get(s, 0) + 1
    _metric(L, "nemofleet_active_alerts", "gauge", "Active anomaly alerts by severity.",
            [({"severity": s}, c) for s, c in sorted(bysev.items())])

    return "\n".join(L) + "\n"
