import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load

w = load("services/bridge/worker-itops.py", "worker_itops")


class TestSignatureTier(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(w.sig_tier("sha256WithRSAEncryption"), "sha256")
        self.assertEqual(w.sig_tier("sha1WithRSA"), "sha1")
        self.assertEqual(w.sig_tier("md5WithRSA"), "md5")


class TestVersionCompare(unittest.TestCase):
    def test_numeric_not_lexical(self):
        # the classic bug: "386_59" > "386_510" as strings; _vt must order them numerically
        self.assertGreater(w._vt("386_510"), w._vt("386_59"))

    def test_dotted_build(self):
        self.assertEqual(w._vt("3.0.0.4.388_24698"), (3, 0, 0, 4, 388, 24698))

    def test_ordering(self):
        self.assertLess(w._vt("1.2.3"), w._vt("1.2.10"))


class TestCipherBad(unittest.TestCase):
    def test_flags_matching_pattern(self):
        self.assertTrue(w._cipher_bad("ECDHE-RSA-RC4-SHA", ["RC4"]))

    def test_ignores_when_no_pattern_matches(self):
        self.assertFalse(w._cipher_bad("ECDHE-RSA-AES256-GCM-SHA384", ["RC4", "3DES"]))


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
        f = w._parse_nuclei(self.SAMPLE)
        self.assertEqual(len(f), 2)                          # garbage + blank lines skipped
        self.assertEqual(f[0]["template"], "CVE-2024-3080")
        self.assertEqual(f[0]["severity"], "critical")       # lowercased
        self.assertEqual(f[0]["cve"], ["CVE-2024-3080"])
        self.assertEqual(f[1]["matched_at"], "10.0.0.1")     # falls back to host when no matched-at

    def test_empty_and_none(self):
        self.assertEqual(w._parse_nuclei(""), [])
        self.assertEqual(w._parse_nuclei(None), [])


if __name__ == "__main__":
    unittest.main()
