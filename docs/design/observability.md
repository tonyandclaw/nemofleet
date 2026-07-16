# Northbound observability — Prometheus metrics

Responds to the "integrate with existing network-ops solutions" feedback. nemofleet exposes its
governance / security / ops state as **Prometheus exposition text**, so an enterprise's *existing*
Prometheus + Grafana + Alertmanager stack scrapes the fleet like any other target — the SRE/NetOps-facing
integration. It emits **only counts and gauges — never secrets, tokens, or request contents** — so it is
safe to scrape.

`make metrics-export` (→ `scripts/metrics-export.sh` → `services/bridge/prom.py`) renders the metrics from
a live `collect()` (plus `verify_audit()` for the audit-chain gauge).

## Metric catalog

| Metric | Type | Meaning |
|---|---|---|
| `nemofleet_up` | gauge | the exporter ran (always 1) |
| `nemofleet_governance_allowed` / `_denied` | gauge | governed egress decisions ALLOWED / DENIED |
| `nemofleet_guardrail_screened` / `_blocked` / `_fail_open` | gauge | guardrail throughput + **fail-opens** (NIM down → unscreened) |
| `nemofleet_node_up{node,zone}` | gauge | each fleet node reachable (1=up) |
| `nemofleet_nim_reachable` | gauge | local NIM inference endpoint reachable |
| `nemofleet_device_online{asset}` · `_device_cpu_percent` · `_device_mem_percent` · `_device_temp_celsius` | gauge | managed-device health |
| `nemofleet_audit_chain_ok` | gauge | tamper-evident ledger verifies (1=ok, **0=broken**) |
| `nemofleet_rollback_mismatch` | gauge | rollbacks that failed read-back verification |
| `nemofleet_open_escalations` | gauge | Jira/ITSM tickets awaiting a human |
| `nemofleet_frozen` | gauge | kill-switch engaged (1=frozen) |
| `nemofleet_active_alerts{severity}` | gauge | active anomaly alerts by severity |

## Alerting (wire into the existing on-call flow)

These are written to be alerted on directly — Alertmanager routes to whatever the SOC/NOC already uses:

```yaml
groups:
- name: nemofleet
  rules:
  - alert: NemofleetNodeDown        # a fleet node unreachable
    expr: nemofleet_node_up == 0
  - alert: NemofleetNimUnreachable  # local inference down → guardrail degrades
    expr: nemofleet_nim_reachable == 0
  - alert: NemofleetFrozen          # kill-switch engaged
    expr: nemofleet_frozen == 1
  - alert: NemofleetGuardrailFailOpen
    expr: nemofleet_guardrail_fail_open > 0
  - alert: NemofleetAuditChainBroken   # tamper-evident ledger stopped verifying
    expr: nemofleet_audit_chain_ok == 0
  - alert: NemofleetRollbackMismatch   # a rollback didn't read back clean
    expr: nemofleet_rollback_mismatch > 0
  - alert: NemofleetDeviceHot
    expr: nemofleet_device_temp_celsius > 80
```

## Wiring it (no new auth surface)

The standard **node_exporter textfile-collector** pattern — a cron / systemd timer writes the metrics
atomically into the collector directory, and the enterprise's existing node_exporter serves them:

```bash
# */1 * * * *  on the dashboard host
bash scripts/metrics-export.sh > /var/lib/node_exporter/textfile_collector/nemofleet.prom.$$ \
  && mv /var/lib/node_exporter/textfile_collector/nemofleet.prom.$$ \
        /var/lib/node_exporter/textfile_collector/nemofleet.prom
```

This deliberately avoids adding an unauthenticated `/metrics` route to the admin-gated dashboard. For a
directly-scraped `/metrics` endpoint instead, front the same output with your existing exporter sidecar
(bearer-token or network-policy protected).

## Honest scope

- **Gauges, current-value**: the count-like metrics are windowed gauges (what `collect()` reports now),
  not monotonic counters — named without `_total` accordingly. Prometheus rate() isn't meaningful on
  them; alert on thresholds/equality.
- **Pull/batch via textfile collector**: a persistent, directly-scraped authenticated `/metrics`
  endpoint is a follow-up; the textfile pattern needs node_exporter (which enterprises already run).
- Pairs with the SOC export (`docs/design/soc-integration.md`): metrics for NetOps/SRE dashboards +
  Alertmanager; OCSF findings for the SIEM/SOC. Together they cover both halves of "integrate with the
  tools the enterprise already runs."
