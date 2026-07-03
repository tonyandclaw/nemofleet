import os, sys, json, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load

d = load("services/bridge/agent-dashboard.py", "agent_dashboard")
# isolate audit writes (e.g. _dlp() logs a redaction event) away from the real path
d.ADMIN_AUDIT = tempfile.mktemp(suffix="-nftest-audit.jsonl")


class TestDLP(unittest.TestCase):
    def test_redacts_credentials_and_tokens(self):
        out = d._dlp("password: hunter2")
        self.assertIn("[REDACTED", out)
        self.assertNotIn("hunter2", out)

    def test_redacts_card_numbers(self):
        out = d._dlp("card 4111 1111 1111 1111 here")
        self.assertNotIn("4111 1111 1111 1111", out)

    def test_passes_clean_text(self):
        self.assertEqual(d._dlp("nothing sensitive here"), "nothing sensitive here")


class TestPasswordHash(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(d._pwhash("pw", "00ff"), d._pwhash("pw", "00ff"))

    def test_salt_changes_hash(self):
        self.assertNotEqual(d._pwhash("pw", "00ff"), d._pwhash("pw", "11ee"))

    def test_is_hex_sha256(self):
        h = d._pwhash("pw", "00ff")
        self.assertEqual(len(h), 64)
        int(h, 16)  # raises if not hex


class TestAuditChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._orig = d.ADMIN_AUDIT
        d.ADMIN_AUDIT = self.tmp

    def tearDown(self):
        d.ADMIN_AUDIT = self._orig
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_valid_chain_verifies(self):
        d.audit("alice", "login", "ok", "127.0.0.1", True)
        d.audit("bob", "logout", "", "127.0.0.1", True)
        res = d.verify_audit()
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 2)
        self.assertIsNone(res["broken"])

    def test_tamper_is_detected(self):
        d.audit("alice", "login", "ok", "127.0.0.1", True)
        d.audit("bob", "logout", "", "127.0.0.1", True)
        rows = [json.loads(l) for l in open(self.tmp) if l.strip()]
        rows[0]["actor"] = "mallory"  # tamper with a committed entry
        with open(self.tmp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        res = d.verify_audit()
        self.assertFalse(res["ok"])
        self.assertEqual(res["broken"], 1)


if __name__ == "__main__":
    unittest.main()
