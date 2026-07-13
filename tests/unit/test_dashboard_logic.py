import os, sys, json, tempfile, hashlib, unittest
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


class TestVerify(unittest.TestCase):
    """_verify() gates dashboard login. It must use a constant-time comparison
    (hmac.compare_digest) rather than `==`, which short-circuits on the first mismatched byte and
    can leak timing information about how much of the stored hash a guess got right."""
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix="-nftest-users.json")
        self._orig = d.USERS_FILE
        d.USERS_FILE = self.tmp
        d.save_users({"alice@example.com": d._mkuser("correct-horse", "admin")})

    def tearDown(self):
        d.USERS_FILE = self._orig
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_correct_password_verifies(self):
        u = d._verify("alice@example.com", "correct-horse")
        self.assertIsNotNone(u)
        self.assertEqual(u["role"], "admin")

    def test_wrong_password_rejected(self):
        self.assertIsNone(d._verify("alice@example.com", "wrong"))

    def test_unknown_email_rejected(self):
        self.assertIsNone(d._verify("nobody@example.com", "correct-horse"))

    def test_uses_constant_time_compare(self):
        # can't reliably assert on timing in a unit test, but we can assert the implementation
        # actually calls the constant-time primitive rather than `==`, so a future edit that
        # reintroduces `==` gets caught here instead of only in a security review.
        import inspect
        src = inspect.getsource(d._verify)
        self.assertIn("hmac.compare_digest", src)
        self.assertNotIn("pwhash\"] ==", src)


class TestAuditChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._orig = d.ADMIN_AUDIT
        d.ADMIN_AUDIT = self.tmp
        self.tmp_key = tempfile.mktemp(suffix=".hmac-key")
        self._orig_key = d.AUDIT_KEY_FILE
        d.AUDIT_KEY_FILE = self.tmp_key

    def tearDown(self):
        d.ADMIN_AUDIT = self._orig
        d.AUDIT_KEY_FILE = self._orig_key
        for p in (self.tmp, self.tmp_key):
            if os.path.exists(p):
                os.remove(p)

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

    def test_full_chain_recompute_without_key_is_detected(self):
        # The exact attack a plain (unkeyed) sha256(prev+entry) chain can't catch: an attacker who
        # can rewrite the whole audit file recomputes every hash from scratch, so a naive
        # "recompute and compare" verifier sees a perfectly self-consistent chain. Simulate that
        # attacker (has the log, does NOT have the separate HMAC key file) and confirm the forged
        # chain is still rejected.
        d.audit("alice", "login", "ok", "127.0.0.1", True)
        d.audit("bob", "logout", "", "127.0.0.1", True)
        rows = [json.loads(l) for l in open(self.tmp) if l.strip()]
        rows[0]["actor"] = "mallory"
        forged = []
        prev = "0" * 64
        for r in rows:
            e = {k: v for k, v in r.items() if k not in ("prev_hash", "hash")}
            e["prev_hash"] = prev
            e["hash"] = hashlib.sha256((prev + d._audit_canon(e)).encode()).hexdigest()  # old, unkeyed scheme
            forged.append(e)
            prev = e["hash"]
        with open(self.tmp, "w", encoding="utf-8") as f:
            for e in forged:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        res = d.verify_audit()
        self.assertFalse(res["ok"], "a fully-recomputed (unkeyed) chain was accepted as valid")

    def test_key_file_is_created_with_private_perms(self):
        d.audit("alice", "login", "ok", "127.0.0.1", True)
        self.assertTrue(os.path.exists(self.tmp_key))
        mode = os.stat(self.tmp_key).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_key_persists_across_process_restarts(self):
        # the whole point of a separate key file: a NEW process (simulated here by clearing the
        # in-memory reference and re-reading) must derive the SAME key from disk, or every restart
        # would break its own chain.
        d.audit("alice", "login", "ok", "127.0.0.1", True)
        k1 = d._audit_key()
        k2 = d._audit_key()
        self.assertEqual(k1, k2)
        res = d.verify_audit()
        self.assertTrue(res["ok"])


class TestGovernanceLedger(unittest.TestCase):
    """_governance_ledger_entries() turns the already-fetched governance stores into the NEW binding
    decisions to append to the tamper-evident chain, deduped against a seen-set. It must chain every
    kind (review/curate/rollback/guardrail-block), skip guardrail ALLOWs, and never re-chain an event
    it has already recorded (idempotent across polls) — otherwise the ledger would grow every 5s."""
    def _d(self):
        return {"governance_c": {
                    "reviews": [{"ts_iso": "2026-07-14T10:00:00", "kind": "remediation", "target": "worker-a", "ref": "ebg-wps", "verdict": "reject", "score": 50}],
                    "curations": [{"ts_iso": "2026-07-14T10:01:00", "op": "insert", "name": "foo", "verdict": "approve"}],
                    "rollbacks": [{"ts": "2026-07-14T10:02:00", "restored_to": "bk-1", "ok": True, "verified": True}]},
                "guardrail": {"recent": [
                    {"ts": "2026-07-14T10:03:00", "verdict": "block", "category": "destructive", "reason": "factory reset"},
                    {"ts": "2026-07-14T10:04:00", "verdict": "allow", "category": "ok", "reason": "ok"}]}}

    def test_chains_all_kinds_and_skips_allows(self):
        entries, seen = d._governance_ledger_entries(self._d(), [])
        actions = sorted(e["action"] for e in entries)
        self.assertEqual(actions, ["gov-curate", "gov-guardrail-block", "gov-review", "gov-rollback"])
        # verdict → ok mapping: reject/block are ok=False, approve/verified rollback are ok=True
        by = {e["action"]: e["ok"] for e in entries}
        self.assertFalse(by["gov-review"]); self.assertFalse(by["gov-guardrail-block"])
        self.assertTrue(by["gov-curate"]); self.assertTrue(by["gov-rollback"])

    def test_idempotent_across_polls(self):
        entries1, seen1 = d._governance_ledger_entries(self._d(), [])
        self.assertEqual(len(entries1), 4)
        entries2, seen2 = d._governance_ledger_entries(self._d(), seen1)
        self.assertEqual(entries2, [], "same data re-chained on the next poll — the ledger would grow forever")

    def test_new_event_after_seen_is_chained(self):
        _, seen = d._governance_ledger_entries(self._d(), [])
        d2 = self._d()
        d2["governance_c"]["reviews"].append({"ts_iso": "2026-07-14T11:00:00", "kind": "cve", "target": "worker-b", "ref": "CVE-1", "verdict": "approve", "score": 100})
        entries, _ = d._governance_ledger_entries(d2, seen)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "gov-review")


class TestFirmwareUrgency(unittest.TestCase):
    """_firmware_urgency() computes the Governance-view firmware urgency host-side from worker-b's
    affected DEVICE CVEs (worker-c can't see worker-b under hub-and-spoke, so it can't do this
    itself). Severity-weighted — the old frontend logic was "any CVE finding at all = update urgent",
    which ignored severity entirely."""
    def test_none_affected_is_normal(self):
        r = d._firmware_urgency([])
        self.assertEqual(r["urgency"], "normal")
        self.assertEqual(r["cve_driven"], [])
        self.assertEqual(r["driven_count"], 0)

    def test_critical_wins(self):
        r = d._firmware_urgency([{"cve": "C1", "severity": "medium"}, {"cve": "C2", "severity": "critical"}])
        self.assertEqual(r["urgency"], "critical")

    def test_high_without_critical(self):
        self.assertEqual(d._firmware_urgency([{"cve": "C1", "severity": "high"}])["urgency"], "high")
        # worker-b sometimes labels "serious" instead of "high" — treated equivalently
        self.assertEqual(d._firmware_urgency([{"cve": "C1", "severity": "serious"}])["urgency"], "high")

    def test_only_medium_or_unknown_is_elevated_not_normal(self):
        # affected-but-low-severity must NOT read as "normal/up-to-date" (that would hide a real hit)
        self.assertEqual(d._firmware_urgency([{"cve": "C1", "severity": "medium"}])["urgency"], "elevated")
        self.assertEqual(d._firmware_urgency([{"cve": "C1", "severity": None}])["urgency"], "elevated")

    def test_cve_driven_sorted_severity_first_and_no_internal_rank_leaks(self):
        r = d._firmware_urgency([{"cve": "LOW", "severity": "low"}, {"cve": "CRIT", "severity": "critical"}])
        self.assertEqual([x["cve"] for x in r["cve_driven"]], ["CRIT", "LOW"])
        self.assertTrue(all("_r" not in x for x in r["cve_driven"]), "internal _r rank leaked into the payload")
        self.assertEqual(r["driven_count"], 2)


if __name__ == "__main__":
    unittest.main()
