import os, sys, json, tempfile, shutil, unittest
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


class TestCertStateCNInjection(unittest.TestCase):
    """_cert_state() shells out to openssl with a CN interpolated into a `-subj '/CN=...'`
    argument (shell=True). A CN containing a single quote can break out of that quoting and run
    arbitrary shell commands unless it's properly escaped. Exercises the real openssl call (no
    mocking the shell) and proves an injection payload never actually executes."""
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_dir = w.CERT_DIR
        w.CERT_DIR = self._tmp

    def tearDown(self):
        w.CERT_DIR = self._orig_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_quote_breakout_payload_does_not_execute(self):
        marker = os.path.join(self._tmp, "PWNED")
        payload = "a'; touch " + marker + " ; echo '"
        st = w._cert_state("test-asset", {"cn": payload, "service": "https"})
        self.assertFalse(os.path.exists(marker), "shell injection via CN executed a command")
        self.assertEqual(st["parsed_by"], "openssl")   # cert was still generated + parsed normally

    def test_slash_in_cn_does_not_inject_subject_fields(self):
        # openssl's -subj treats "/" as a DN field separator; an embedded "/" could otherwise
        # smuggle in an unintended extra subject field (e.g. /CN=x/O=evil).
        st = w._cert_state("test-asset2", {"cn": "evil/O=Not A Real CA", "service": "https"})
        self.assertNotIn("O = Not A Real CA", (st.get("issuer") or ""))


class TestApprovalVerifyAndRecord(unittest.TestCase):
    """_approval_verify_and_record(token, action, params) gates worker-c's high-risk actions
    (rollback/firmware-apply). It used to be a plain truthiness check (any non-empty string
    "approved" the action), then a flat shared-secret compare (any correct-secret string approved
    ANY action). Now a token is minted (wi_approval.issue) for one specific action+params, expires,
    and is single-use — so it fails CLOSED if APPROVAL_KEY is unset, and rejects a
    correctly-signed token that's expired, reused, or bound to a different action/params."""
    def setUp(self):
        self._orig_key = w.APPROVAL_KEY; w.APPROVAL_KEY = "test-hmac-key"
        self._orig_hist = w.APPROVAL_HISTORY
        w.APPROVAL_HISTORY = tempfile.mktemp(suffix="-nftest-approval-history.jsonl")

    def tearDown(self):
        w.APPROVAL_KEY = self._orig_key
        if os.path.exists(w.APPROVAL_HISTORY):
            os.remove(w.APPROVAL_HISTORY)
        w.APPROVAL_HISTORY = self._orig_hist

    def _tok(self, action="rollback", params=None, **kw):
        return w.wi_approval.issue(action, params or {}, "alice@telegram", w.APPROVAL_KEY, **kw)

    def test_correct_token_approves(self):
        tok = self._tok(params={"to": "bk-1"})
        r = w._approval_verify_and_record(tok, "rollback", {"to": "bk-1"})
        self.assertTrue(r["ok"])

    def test_wrong_action_rejected(self):
        tok = self._tok("rollback", {"to": "bk-1"})
        r = w._approval_verify_and_record(tok, "firmware-apply", {"to": "bk-1"})
        self.assertFalse(r["ok"])

    def test_plain_non_empty_string_rejected(self):
        # the original bug: any non-empty string used to pass
        r = w._approval_verify_and_record("x", "rollback", {"to": "bk-1"})
        self.assertFalse(r["ok"])

    def test_empty_rejected(self):
        r = w._approval_verify_and_record("", "rollback", {"to": "bk-1"})
        self.assertFalse(r["ok"])

    def test_fails_closed_when_key_unset(self):
        w.APPROVAL_KEY = ""
        tok = w.wi_approval.issue("rollback", {"to": "bk-1"}, "alice", "test-hmac-key")
        r = w._approval_verify_and_record(tok, "rollback", {"to": "bk-1"})
        self.assertFalse(r["ok"])

    def test_reused_token_rejected_second_time(self):
        tok = self._tok(params={"to": "bk-1"})
        first = w._approval_verify_and_record(tok, "rollback", {"to": "bk-1"})
        second = w._approval_verify_and_record(tok, "rollback", {"to": "bk-1"})
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])

    def test_records_issuer_for_traceability(self):
        tok = self._tok(params={"to": "bk-1"})
        w._approval_verify_and_record(tok, "rollback", {"to": "bk-1"})
        rows = [json.loads(l) for l in open(w.APPROVAL_HISTORY, encoding="utf-8") if l.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["issuer"], "alice@telegram")
        self.assertEqual(rows[0]["act"], "rollback")


class TestRunRollbackValidation(unittest.TestCase):
    """run_rollback(to, approval_token) applies `to`.json's saved config to the real EBG19P — `to`
    must be exactly a run_backup()-issued id (bk-YYYYMMDD-HHMMSS), or a caller with a valid bridge
    token could read/apply an arbitrary .json path (e.g. to="../../../etc/passwd") instead of a
    real backup. zone C is required for rollback at all, so force it for this test regardless of
    the process's real BRIDGE_ZONE. A real approval_token, freshly minted and bound to the exact
    `to` under test, is used for every "should pass approval" case so the `to` validation can be
    tested on its own, independent of the approval-token check itself."""
    def setUp(self):
        self._orig_zone = w.ZONE; w.ZONE = "C"
        self._orig_key = w.APPROVAL_KEY; w.APPROVAL_KEY = "test-hmac-key"
        self._orig_hist = w.APPROVAL_HISTORY
        w.APPROVAL_HISTORY = tempfile.mktemp(suffix="-nftest-approval-history.jsonl")

    def tearDown(self):
        w.ZONE = self._orig_zone
        w.APPROVAL_KEY = self._orig_key
        if os.path.exists(w.APPROVAL_HISTORY):
            os.remove(w.APPROVAL_HISTORY)
        w.APPROVAL_HISTORY = self._orig_hist

    def _tok(self, to):
        return w.wi_approval.issue("rollback", {"to": to}, "alice@telegram", w.APPROVAL_KEY)

    def test_rejects_path_traversal(self):
        to = "../../../etc/passwd"
        r = w.run_rollback(to, approval_token=self._tok(to))
        self.assertFalse(r["ok"])
        self.assertIn("格式", r["error"])

    def test_rejects_absolute_path(self):
        to = "/etc/passwd"
        r = w.run_rollback(to, approval_token=self._tok(to))
        self.assertFalse(r["ok"])

    def test_rejects_non_matching_format(self):
        to = "not-a-backup-id"
        r = w.run_rollback(to, approval_token=self._tok(to))
        self.assertFalse(r["ok"])

    def test_accepts_valid_format_but_missing_file(self):
        # correct shape, just doesn't exist on disk — should reach the "not found" branch, not the
        # format-rejection branch, proving the regex isn't overly strict for real backup ids.
        to = "bk-20260101-000000"
        r = w.run_rollback(to, approval_token=self._tok(to))
        self.assertFalse(r["ok"])
        self.assertIn("找不到備份", r["error"])

    def test_rejects_wrong_approval_token(self):
        r = w.run_rollback("bk-20260101-000000", approval_token="not-a-real-token")
        self.assertFalse(r["ok"])
        self.assertIn("approval_token", r["error"])

    def test_still_requires_approval_token(self):
        r = w.run_rollback("bk-20260101-000000", approval_token="")
        self.assertFalse(r["ok"])
        self.assertIn("approval_token", r["error"])

    def test_token_approved_for_a_different_backup_id_is_rejected(self):
        # the exact replay this design exists to stop: a human approved rollback to bk-A, the
        # token must not also work for rollback to bk-B.
        tok = self._tok("bk-20260101-000000")
        r = w.run_rollback("bk-20260202-000000", approval_token=tok)
        self.assertFalse(r["ok"])
        self.assertIn("approval_token", r["error"])


if __name__ == "__main__":
    unittest.main()
