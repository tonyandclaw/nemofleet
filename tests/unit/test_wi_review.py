"""Unit tests for wi_review — worker-c QA-review gates (pure)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "bridge")))
import wi_review  # noqa: E402

BASELINE = "wps.enabled = false\nssh.password_login = false\n"
KEYS = ["wps.enabled", "ssh.password_login"]


class TestReviewRemediation(unittest.TestCase):
    def test_approve_when_matches_baseline_and_verified(self):
        v = wi_review.review_remediation({"bug": "ebg-wps", "ok": True, "after": {"wps.enabled": "false"}}, BASELINE, KEYS)
        self.assertEqual(v["verdict"], "approve")
        self.assertEqual(v["score"], 100)

    def test_reject_when_after_still_deviates(self):
        v = wi_review.review_remediation({"bug": "ebg-wps", "ok": True, "after": {"wps.enabled": "true"}}, BASELINE, KEYS)
        self.assertEqual(v["verdict"], "reject")
        self.assertTrue(any("baseline" in c["name"] for c in v["checks"] if not c["pass"]))
        self.assertTrue(v["required_fixes"])                       # tells a/b what to redo

    def test_reject_when_unverified(self):
        v = wi_review.review_remediation({"bug": "ebg-wps"}, BASELINE, KEYS)   # no ok/after
        self.assertEqual(v["verdict"], "reject")

    def test_reject_scope_creep(self):
        # target is wps, but the change also flipped ssh (still compliant, yet out of declared scope)
        v = wi_review.review_remediation(
            {"bug": "ebg-wps", "ok": True, "target_key": "wps.enabled",
             "before": {"wps.enabled": "true", "ssh.password_login": "true"},
             "after": {"wps.enabled": "false", "ssh.password_login": "false"}}, BASELINE, KEYS)
        self.assertEqual(v["verdict"], "reject")
        self.assertTrue(any(c["name"] == "scope" and not c["pass"] for c in v["checks"]))

    def test_approve_in_scope(self):
        # only the target key changed → scope gate passes (ssh unchanged, still compliant)
        v = wi_review.review_remediation(
            {"bug": "ebg-wps", "ok": True, "target_key": "wps.enabled",
             "before": {"wps.enabled": "true", "ssh.password_login": "false"},
             "after": {"wps.enabled": "false", "ssh.password_login": "false"}}, BASELINE, KEYS)
        self.assertEqual(v["verdict"], "approve")


class TestReviewCve(unittest.TestCase):
    def test_reject_affected_without_evidence(self):
        v = wi_review.review_cve({"cve": "CVE-2024-1", "verdict": "affected"})   # no component/version
        self.assertEqual(v["verdict"], "reject")

    def test_approve_with_evidence(self):
        v = wi_review.review_cve({"cve": "CVE-2024-1", "verdict": "affected", "component": "openssl", "our_version": "3.0.1"})
        self.assertEqual(v["verdict"], "approve")

    def test_reject_affected_when_version_at_or_above_fixed(self):
        # our_version already >= the fixed version → "affected" is suspicious (likely false positive)
        v = wi_review.review_cve({"cve": "CVE-1", "verdict": "affected", "component": "openssl",
                                  "our_version": "3.0.5", "fixed_version": "3.0.2"})
        self.assertEqual(v["verdict"], "reject")
        self.assertTrue(any(c["name"] == "version-consistent" and not c["pass"] for c in v["checks"]))

    def test_approve_affected_when_version_below_fixed(self):
        v = wi_review.review_cve({"cve": "CVE-1", "verdict": "affected", "component": "openssl",
                                  "our_version": "3.0.1", "fixed_version": "3.0.2"})
        self.assertEqual(v["verdict"], "approve")


if __name__ == "__main__":
    unittest.main()


class TestRedoEscalation(unittest.TestCase):
    def _rej(self):
        return wi_review.review_remediation({"bug": "ebg-wps", "ok": True, "after": {"wps.enabled": "true"}}, BASELINE, KEYS)

    def test_approve_resets(self):
        v = wi_review.review_remediation({"bug": "ebg-wps", "ok": True, "after": {"wps.enabled": "false"}}, BASELINE, KEYS)
        v = wi_review.annotate_redo(v, [{"kind": "remediation", "ref": "ebg-wps", "verdict": "reject"}])
        self.assertEqual((v["redo_count"], v["escalate"]), (0, False))

    def test_redo_counts_same_subject(self):
        hist = [{"kind": "remediation", "ref": "ebg-wps", "verdict": "reject"}]
        v = wi_review.annotate_redo(self._rej(), hist)
        self.assertEqual((v["redo_count"], v["escalate"]), (2, False))   # 2nd reject, cap=2 → not yet

    def test_escalates_past_cap(self):
        hist = [{"kind": "remediation", "ref": "ebg-wps", "verdict": "reject"}] * 2
        v = wi_review.annotate_redo(self._rej(), hist)
        self.assertEqual((v["redo_count"], v["escalate"]), (3, True))    # 3rd reject > cap → human
        self.assertIn("升級真人", v["required_fixes"][0])

    def test_other_subject_does_not_count(self):
        hist = [{"kind": "remediation", "ref": "ebg-upnp", "verdict": "reject"},
                {"kind": "cve", "ref": "ebg-wps", "verdict": "reject"}]
        v = wi_review.annotate_redo(self._rej(), hist)
        self.assertEqual(v["redo_count"], 1)   # different bug / different kind don't count
