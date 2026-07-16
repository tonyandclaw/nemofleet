import os, sys, re, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load

prom = load("services/bridge/prom.py", "prom")

# real-shaped collect() payload (raw keys, one node down, device warm, audit broken, a rollback mismatch)
PAYLOAD = {
    "governance": {"allowed": 692, "denied": 3, "benign": 0},
    "guardrail": {"count": 10, "blocked": 4, "fail_open": 1},
    "nodes": [
        {"name": "team-lead", "zone": "", "up": True},
        {"name": "worker-a", "zone": "zone A", "up": True},
        {"name": "worker-b", "zone": "zone B", "up": False},
    ],
    "sysinfo": {"inference": {"reachable": True}},
    "devices": [{"asset": "lab-asus-ebg19p-01", "online": True, "cpu": 23, "mem": 41, "temp": 55}],
    "_audit": {"chain": {"ok": False, "count": 100}},
    "governance_c": {"rollbacks": [{"verify": {"mismatch": [{"key": "wps_enable"}]}}, {"verify": {"mismatch": []}}]},
    "jira": {"tickets": [{"id": "NET-1"}, {"id": "NET-2"}]},
    "frozen": {"frozen": True},
    "alerts_list": [{"sev": "high", "kind": "login_lock"}, {"sev": "warn", "kind": "device_cpu"}, {"sev": "high", "kind": "denied_spike"}],
}
OUT = prom.render(PAYLOAD)
SAMPLE = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})? -?\d+(\.\d+)?$')


def _samples(txt):
    return [l for l in txt.split("\n") if l.strip() and not l.startswith("#")]


def get(txt, name, label=None):
    for l in _samples(txt):
        if l.split("{")[0].split(" ")[0] != name:
            continue
        if label and label not in l:
            continue
        return l.rsplit(" ", 1)[1]
    return None


class TestPromFormat(unittest.TestCase):
    def test_every_sample_line_is_valid_exposition(self):
        for l in _samples(OUT):
            self.assertRegex(l, SAMPLE, "bad exposition line: %r" % l)

    def test_every_metric_has_help_and_type(self):
        types = {l.split()[2] for l in OUT.split("\n") if l.startswith("# TYPE")}
        helps = {l.split()[2] for l in OUT.split("\n") if l.startswith("# HELP")}
        for l in _samples(OUT):
            name = l.split("{")[0].split(" ")[0]
            self.assertIn(name, types, "%s missing # TYPE" % name)
            self.assertIn(name, helps, "%s missing # HELP" % name)

    def test_exporter_liveness_metric_present(self):
        self.assertEqual(get(OUT, "nemofleet_up"), "1")


class TestPromValues(unittest.TestCase):
    def test_node_up_reflects_reachability(self):
        self.assertEqual(get(OUT, "nemofleet_node_up", 'node="worker-b"'), "0")
        self.assertEqual(get(OUT, "nemofleet_node_up", 'node="worker-a"'), "1")

    def test_zone_label_normalized(self):
        self.assertIn('nemofleet_node_up{node="worker-a",zone="A"} 1', OUT)   # "zone A" → "A"; lead node → "lead"
        self.assertIn('zone="lead"', OUT)

    def test_critical_gauges(self):
        self.assertEqual(get(OUT, "nemofleet_nim_reachable"), "1")
        self.assertEqual(get(OUT, "nemofleet_frozen"), "1")
        self.assertEqual(get(OUT, "nemofleet_guardrail_fail_open"), "1")
        self.assertEqual(get(OUT, "nemofleet_audit_chain_ok"), "0")       # broken chain → 0
        self.assertEqual(get(OUT, "nemofleet_rollback_mismatch"), "1")    # exactly one rollback mismatched

    def test_device_and_escalations(self):
        self.assertEqual(get(OUT, "nemofleet_device_online"), "1")
        self.assertEqual(get(OUT, "nemofleet_device_temp_celsius"), "55")
        self.assertEqual(get(OUT, "nemofleet_open_escalations"), "2")

    def test_alerts_by_severity(self):
        self.assertEqual(get(OUT, "nemofleet_active_alerts", 'severity="high"'), "2")
        self.assertEqual(get(OUT, "nemofleet_active_alerts", 'severity="warn"'), "1")

    def test_governance_counts(self):
        self.assertEqual(get(OUT, "nemofleet_governance_allowed"), "692")
        self.assertEqual(get(OUT, "nemofleet_governance_denied"), "3")

    def test_empty_payload_still_renders_liveness(self):
        out = prom.render({})
        self.assertEqual(get(out, "nemofleet_up"), "1")   # never blank — an empty scrape still proves the exporter ran


if __name__ == "__main__":
    unittest.main()
