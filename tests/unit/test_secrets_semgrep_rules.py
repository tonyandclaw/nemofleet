import json, os, shutil, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES = os.path.join(ROOT, "config", "semgrep", "nemofleet-hardcoded-credential.yaml")


def _scan(tmpdir):
    p = subprocess.run(
        ["semgrep", "scan", "--config", RULES, "--json", "--quiet", "--metrics=off", tmpdir],
        capture_output=True, text=True, timeout=60)
    data = json.loads(p.stdout or "{}")
    return [r["check_id"].split(".")[-1] for r in data.get("results", [])]


@unittest.skipUnless(shutil.which("semgrep"), "semgrep not installed — CI doesn't install it (see .github/workflows/lint.yml); run locally on a dev box with semgrep on PATH")
class TestSecretsRuleset(unittest.TestCase):
    """worker-b's real Semgrep pipeline (_run_semgrep in worker-itops.py) loads every *.yaml under
    the pinned local ruleset, including config/semgrep/*.yaml — these tests exercise the actual
    rule file against real Semgrep, not a mock, so a regex typo that silently stops matching (or
    starts false-positiving) is caught here instead of only in worker-b's next scan."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_catches_js_hardcoded_credential(self):
        self._write("a.js", 'const cfg = { apiKey: "sk-abcdef1234567890", password: "hunter2plus" };')
        hits = _scan(self.tmp)
        self.assertIn("nemofleet-js-hardcoded-credential", hits)

    def test_catches_bash_hardcoded_credential(self):
        self._write("a.sh", "#!/bin/bash\nPASSWORD=hunter2plusplus\nTOKEN=\"abc123def456xyz\"\n")
        hits = _scan(self.tmp)
        self.assertIn("nemofleet-bash-hardcoded-credential", hits)

    def test_catches_pem_private_key_block(self):
        # split across two literals — a contiguous "-----BEGIN ... PRIVATE KEY-----" in this
        # source file trips GitHub's own push-protection secret scanner (it did, on an earlier
        # version of this file) even though it's a synthetic fixture, not a real key.
        header = "-----BEGIN " + "RSA PRIVATE KEY-----"
        footer = "-----END " + "RSA PRIVATE KEY-----"
        self._write("key.txt", f"{header}\nMIIEpAIBAAKCAQEA1234567890abcdefgh\n{footer}\n")
        hits = _scan(self.tmp)
        self.assertIn("nemofleet-pem-private-key", hits)

    def test_catches_structured_cloud_tokens(self):
        # each fixture "token" is built from split fragments so no single contiguous literal in
        # this committed source file matches a real provider's format closely enough to trip
        # GitHub's push-protection secret scanner (which blocked an earlier version of this file
        # over the Slack-shaped fixture below) — semgrep still sees the full assembled string once
        # it's written to the temp scan file, so the rule under test is exercised identically.
        aws = "AKIA" + "ABCDEFGHIJKLMNOP"
        gh = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz12"
        slack = "xoxb-1234567890" + "-abcdefghijklmnop"
        google = "AIzaSyD-1234567890" + "abcdefghijklmnopqrstuv"
        self._write("tokens.txt",
                     f"aws_key = {aws}\n"
                     f"gh_token = {gh}\n"
                     f"slack = {slack}\n"
                     f"google = {google}\n")
        hits = _scan(self.tmp)
        self.assertIn("nemofleet-cloud-token-pattern", hits)
        self.assertGreaterEqual(hits.count("nemofleet-cloud-token-pattern"), 4)

    def test_bash_variable_reference_is_not_a_false_positive(self):
        # this is exactly the pattern nemofleet's own scripts use everywhere (TOKEN_FILE paths,
        # TOKEN=$(cat ...)) — a reference to a secret is not itself a hardcoded secret.
        self._write("ref.sh",
                     '#!/bin/bash\n'
                     'TOKEN_FILE="$BRIDGE/.bridge-token"\n'
                     'TOKEN=$(cat "$TOKEN_FILE")\n'
                     'TOKEN_FILE="$BRIDGE_TOKEN_FILE"\n')
        hits = _scan(self.tmp)
        self.assertNotIn("nemofleet-bash-hardcoded-credential", hits)

    def test_clean_code_has_no_hits(self):
        self._write("clean.py", 'password = os.environ.get("APP_PASSWORD")\n'
                                 'def f():\n    return "no secret in this literal string at all"\n')
        hits = _scan(self.tmp)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
