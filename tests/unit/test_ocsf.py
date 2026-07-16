import os, sys, json, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load

oc = load("services/bridge/ocsf.py", "ocsf")

# real-shaped inputs (mirror worker /guardrail-log, detect_anomalies, and governance_c)
GUARDRAIL = {"recent": [
    {"ts": "2026-07-13T13:40:22", "gate": "intake", "verdict": "block", "category": "prompt_injection", "by": "deterministic", "reason": "token exfil", "excerpt": "reveal the bridge token", "fail_open": False},
    {"ts": "2026-07-13T13:41:00", "gate": "action", "verdict": "block", "category": "destructive", "by": "deterministic", "reason": "factory reset", "excerpt": "factory reset the device", "fail_open": False},
    {"ts": "2026-07-13T13:42:00", "gate": "intake", "verdict": "allow", "category": "ok", "by": "-", "reason": "guardrail unreachable", "fail_open": True},
    {"ts": "2026-07-13T13:43:00", "gate": "intake", "verdict": "allow", "category": "ok", "by": "nim", "reason": "ok", "fail_open": False},
]}
ALERTS = [
    {"id": "loginlock:1.2.3.4", "sev": "high", "kind": "login_lock", "msg": "暴力", "msg_en": "Login brute-force locked out: 1.2.3.4"},
    {"id": "offhours:x", "sev": "info", "kind": "offhours_admin", "msg": "非工時", "msg_en": "Off-hours admin action"},
    {"id": "cpu:lab", "sev": "warn", "kind": "device_cpu", "msg": "CPU 高", "msg_en": "lab high CPU 96%"},
]
GOV = {"rollbacks": [{"ts": "2026-07-12T22:04:11", "ok": True, "verified": True, "restored_to": "bk-1"},
                     {"ts": "2026-07-12T23:00:00", "ok": True, "verified": False, "restored_to": "bk-2"}],
       "reviews": [{"ts_iso": "2026-07-14T10:00:00", "kind": "remediation", "ref": "ebg-wps", "target": "worker-a", "verdict": "reject", "score": 50}]}
PAYLOAD = {"now": "2026-07-15 22:00:00", "guardrail": GUARDRAIL, "alerts_list": ALERTS, "governance_c": GOV}


def _by_title(recs, needle):
    return [r for r in recs if needle in (r["finding_info"]["title"] or "")]


class TestOcsfCore(unittest.TestCase):
    def test_every_record_has_ocsf_core_fields(self):
        for r in oc.emit(PAYLOAD):
            self.assertEqual(r["class_uid"], 2004)
            self.assertEqual(r["category_uid"], 2)
            self.assertIn(r["severity_id"], (1, 2, 3, 4, 5, 6))
            self.assertEqual(r["metadata"]["product"]["name"], "nemofleet")
            self.assertIn("finding_info", r)

    def test_to_ndjson_is_one_valid_json_object_per_line(self):
        recs = oc.emit(PAYLOAD)
        lines = oc.to_ndjson(recs).split("\n")
        self.assertEqual(len(lines), len(recs))
        for ln in lines:
            json.loads(ln)   # raises if any line isn't valid JSON

    def test_time_parsed_to_utc_epoch_ms_deterministically(self):
        # 2026-07-13T13:40:22 UTC → fixed epoch ms regardless of host timezone
        r = _by_title(oc.emit(PAYLOAD), "prompt_injection")[0]
        self.assertEqual(r["time"], 1783950022000)   # 2026-07-13 13:40:22 UTC


class TestGuardrailMapping(unittest.TestCase):
    def test_prompt_injection_block_tagged_atlas(self):
        r = _by_title(oc.guardrail_findings(GUARDRAIL), "prompt_injection")[0]
        self.assertEqual(r["severity_id"], 4)  # High
        self.assertEqual(r["unmapped"]["mitre"]["atlas"][0]["technique_id"], "AML.T0051")

    def test_destructive_block_tagged_attack(self):
        r = _by_title(oc.guardrail_findings(GUARDRAIL), "destructive")[0]
        self.assertEqual(r["unmapped"]["mitre"]["attack"][0]["technique_id"], "T1485")

    def test_fail_open_allow_is_a_medium_finding_plain_allow_is_dropped(self):
        recs = oc.guardrail_findings(GUARDRAIL)
        self.assertTrue(any("fail-open" in r["finding_info"]["title"] for r in recs))
        # 2 blocks + 1 fail-open = 3; the plain allow must NOT appear
        self.assertEqual(len(recs), 3)


class TestAnomalyMapping(unittest.TestCase):
    def test_bruteforce_and_offhours_get_attack_tags(self):
        recs = oc.anomaly_findings(ALERTS, now="2026-07-15 22:00:00")
        bf = _by_title(recs, "brute-force")[0]
        self.assertEqual(bf["unmapped"]["mitre"]["attack"][0]["technique_id"], "T1110")
        oh = _by_title(recs, "Off-hours")[0]
        self.assertEqual(oh["unmapped"]["mitre"]["attack"][0]["technique_id"], "T1078")

    def test_operational_device_alert_has_no_attack_tag(self):
        cpu = _by_title(oc.anomaly_findings(ALERTS), "high CPU")[0]
        self.assertNotIn("mitre", cpu["unmapped"])   # device_cpu is operational, not an attack


class TestGovernanceMapping(unittest.TestCase):
    def test_rollback_is_remediation_tagged_d3fend(self):
        r = _by_title(oc.governance_findings(GOV), "Config rollback → bk-1")[0]
        self.assertEqual(r["finding_info"]["types"], ["Remediation"])
        self.assertEqual(r["unmapped"]["mitre"]["d3fend"][0]["technique_id"], "D3-ACH")

    def test_unverified_rollback_is_high_severity(self):
        r = _by_title(oc.governance_findings(GOV), "Config rollback → bk-2")[0]
        self.assertEqual(r["severity_id"], 4)  # read-back not verified → High

    def test_rejected_review_is_a_governance_finding(self):
        r = _by_title(oc.governance_findings(GOV), "QA review reject")[0]
        self.assertEqual(r["finding_info"]["types"], ["Governance"])


if __name__ == "__main__":
    unittest.main()
