import os, sys, tempfile, shutil, unittest
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


class TestApproved(unittest.TestCase):
    """_approved(token) gates worker-c's high-risk actions (rollback/firmware-apply). It used to be
    a plain truthiness check (any non-empty string "approved" the action) — now it's a real shared
    secret (APPROVAL_TOKEN, injected only into worker-c's container) compared in constant time,
    and fails CLOSED (rejects everything) if that secret was never configured."""
    def setUp(self):
        self._orig = w.APPROVAL_TOKEN

    def tearDown(self):
        w.APPROVAL_TOKEN = self._orig

    def test_correct_secret_approves(self):
        w.APPROVAL_TOKEN = "real-secret"
        self.assertTrue(w._approved("real-secret"))

    def test_wrong_value_rejected(self):
        w.APPROVAL_TOKEN = "real-secret"
        self.assertFalse(w._approved("close-but-wrong"))
        self.assertFalse(w._approved("x"))   # the old bug: any non-empty string used to pass

    def test_empty_rejected(self):
        w.APPROVAL_TOKEN = "real-secret"
        self.assertFalse(w._approved(""))
        self.assertFalse(w._approved(None))

    def test_fails_closed_when_secret_unset(self):
        # not configured (e.g. zone A/B, or zone C before boot-stack.sh provisions it) → nothing
        # approves anything, not even a caller who happens to send an empty APPROVAL_TOKEN too.
        w.APPROVAL_TOKEN = ""
        self.assertFalse(w._approved(""))
        self.assertFalse(w._approved("anything"))


class TestRunRollbackValidation(unittest.TestCase):
    """run_rollback(to, approval_token) applies `to`.json's saved config to the real EBG19P — `to`
    must be exactly a run_backup()-issued id (bk-YYYYMMDD-HHMMSS), or a caller with a valid bridge
    token could read/apply an arbitrary .json path (e.g. to="../../../etc/passwd") instead of a
    real backup. zone C is required for rollback at all, so force it for this test regardless of
    the process's real BRIDGE_ZONE. APPROVAL_TOKEN is set to a known test secret so the `to`
    validation can be tested on its own, independent of the approval-token check."""
    def setUp(self):
        self._orig_zone = w.ZONE; w.ZONE = "C"
        self._orig_token = w.APPROVAL_TOKEN; w.APPROVAL_TOKEN = "test-approval-secret"

    def tearDown(self):
        w.ZONE = self._orig_zone
        w.APPROVAL_TOKEN = self._orig_token

    def test_rejects_path_traversal(self):
        r = w.run_rollback("../../../etc/passwd", approval_token="test-approval-secret")
        self.assertFalse(r["ok"])
        self.assertIn("格式", r["error"])

    def test_rejects_absolute_path(self):
        r = w.run_rollback("/etc/passwd", approval_token="test-approval-secret")
        self.assertFalse(r["ok"])

    def test_rejects_non_matching_format(self):
        r = w.run_rollback("not-a-backup-id", approval_token="test-approval-secret")
        self.assertFalse(r["ok"])

    def test_accepts_valid_format_but_missing_file(self):
        # correct shape, just doesn't exist on disk — should reach the "not found" branch, not the
        # format-rejection branch, proving the regex isn't overly strict for real backup ids.
        r = w.run_rollback("bk-20260101-000000", approval_token="test-approval-secret")
        self.assertFalse(r["ok"])
        self.assertIn("找不到備份", r["error"])

    def test_rejects_wrong_approval_token(self):
        r = w.run_rollback("bk-20260101-000000", approval_token="not-the-real-secret")
        self.assertFalse(r["ok"])
        self.assertIn("approval_token", r["error"])

    def test_still_requires_approval_token(self):
        r = w.run_rollback("bk-20260101-000000", approval_token="")
        self.assertFalse(r["ok"])
        self.assertIn("approval_token", r["error"])


if __name__ == "__main__":
    unittest.main()
