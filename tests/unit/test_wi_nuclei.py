"""Unit tests for wi_nuclei — worker-b active-scan subsystem (parser + configured behavior)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "bridge")))
import wi_nuclei  # noqa: E402


class TestNucleiParse(unittest.TestCase):
    SAMPLE = "\n".join([
        '{"template-id":"CVE-2024-3080","info":{"name":"ASUS Router Auth Bypass","severity":"Critical",'
        '"classification":{"cve-id":["CVE-2024-3080"]},"reference":["https://nvd.nist.gov/vuln/detail/CVE-2024-3080"]},'
        '"matched-at":"http://10.0.0.1","type":"http"}',
        '{"template-id":"tech-detect","info":{"name":"ASUSWRT","severity":"info"},"host":"10.0.0.1","type":"http"}',
        "not-json-garbage",
        "",
    ])

    def test_parses_and_normalizes(self):
        f = wi_nuclei._parse_nuclei(self.SAMPLE)
        self.assertEqual(len(f), 2)                          # garbage + blank lines skipped
        self.assertEqual(f[0]["template"], "CVE-2024-3080")
        self.assertEqual(f[0]["severity"], "critical")       # lowercased
        self.assertEqual(f[0]["cve"], ["CVE-2024-3080"])
        self.assertEqual(f[1]["matched_at"], "10.0.0.1")     # falls back to host

    def test_empty_and_none(self):
        self.assertEqual(wi_nuclei._parse_nuclei(""), [])
        self.assertEqual(wi_nuclei._parse_nuclei(None), [])


class TestNucleiRun(unittest.TestCase):
    def test_non_security_zone_rejected(self):
        # inject a zone lacking the nuclei cap → returns unavailable without touching the binary
        wi_nuclei.configure(zone_has=lambda c: False, load_settings=lambda: {},
                            open_jira=lambda *a, **k: None, zone="A")
        r = wi_nuclei.run_nuclei_scan()
        self.assertFalse(r["available"])
        self.assertEqual(r["zone"], "A")


if __name__ == "__main__":
    unittest.main()
