import os, sys, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "services", "bridge"))
import wi_approval as wa

KEY = "test-hmac-key"


def _never_seen(nonce):
    return False


class TestIssueVerifyRoundtrip(unittest.TestCase):
    def test_valid_token_verifies(self):
        tok = wa.issue("rollback", {"to": "bk-20260101-000000"}, "alice@telegram", KEY)
        r = wa.verify(tok, "rollback", {"to": "bk-20260101-000000"}, KEY, _never_seen)
        self.assertTrue(r["ok"])
        self.assertEqual(r["claims"]["iss"], "alice@telegram")

    def test_wrong_key_rejected(self):
        tok = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY)
        r = wa.verify(tok, "rollback", {"to": "bk-1"}, "different-key", _never_seen)
        self.assertFalse(r["ok"])

    def test_tampered_body_rejected(self):
        tok = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY)
        body, sig = tok.rsplit(".", 1)
        r = wa.verify(body + "x." + sig, "rollback", {"to": "bk-1"}, KEY, _never_seen)
        self.assertFalse(r["ok"])

    def test_malformed_token_rejected(self):
        for bad in ("", "no-dot-here", "..", None):
            r = wa.verify(bad, "rollback", {"to": "bk-1"}, KEY, _never_seen)
            self.assertFalse(r["ok"])


class TestActionAndParamBinding(unittest.TestCase):
    """The whole point of this module over a flat shared secret: a token minted for one action or
    one set of params must not validate a DIFFERENT action or DIFFERENT params — otherwise a human
    approving "rollback to bk-A" could be replayed to approve "rollback to bk-B"."""
    def test_wrong_action_rejected(self):
        tok = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY)
        r = wa.verify(tok, "firmware-apply", {"to": "bk-1"}, KEY, _never_seen)
        self.assertFalse(r["ok"])
        self.assertIn("動作", r["error"])

    def test_wrong_params_rejected(self):
        tok = wa.issue("rollback", {"to": "bk-approved-one"}, "alice", KEY)
        r = wa.verify(tok, "rollback", {"to": "bk-a-different-one"}, KEY, _never_seen)
        self.assertFalse(r["ok"])
        self.assertIn("參數", r["error"])

    def test_param_order_does_not_matter(self):
        tok = wa.issue("firmware-apply", {"asset": "x", "version": "1.2"}, "alice", KEY)
        r = wa.verify(tok, "firmware-apply", {"version": "1.2", "asset": "x"}, KEY, _never_seen)
        self.assertTrue(r["ok"])


class TestExpiry(unittest.TestCase):
    def test_expired_token_rejected(self):
        tok = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY, ttl_s=-1)
        r = wa.verify(tok, "rollback", {"to": "bk-1"}, KEY, _never_seen)
        self.assertFalse(r["ok"])
        self.assertIn("過期", r["error"])

    def test_not_yet_expired_token_verifies(self):
        tok = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY, ttl_s=5)
        r = wa.verify(tok, "rollback", {"to": "bk-1"}, KEY, _never_seen)
        self.assertTrue(r["ok"])


class TestSingleUse(unittest.TestCase):
    def test_reused_nonce_rejected(self):
        tok = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY)
        r = wa.verify(tok, "rollback", {"to": "bk-1"}, KEY, lambda n: True)
        self.assertFalse(r["ok"])
        self.assertIn("使用過", r["error"])

    def test_two_independent_tokens_each_have_own_nonce(self):
        t1 = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY)
        t2 = wa.issue("rollback", {"to": "bk-1"}, "alice", KEY)
        n1 = wa.verify(t1, "rollback", {"to": "bk-1"}, KEY, _never_seen)["claims"]["nonce"]
        n2 = wa.verify(t2, "rollback", {"to": "bk-1"}, KEY, _never_seen)["claims"]["nonce"]
        self.assertNotEqual(n1, n2)


if __name__ == "__main__":
    unittest.main()
