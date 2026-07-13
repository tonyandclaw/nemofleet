import json, os, shutil, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES = os.path.join(ROOT, "config", "semgrep", "nemofleet-command-injection.yaml")


def _scan(path):
    p = subprocess.run(
        ["semgrep", "scan", "--config", RULES, "--json", "--quiet", "--metrics=off", path],
        capture_output=True, text=True, timeout=60)
    data = json.loads(p.stdout or "{}")
    return [r["check_id"].split(".")[-1] for r in data.get("results", [])]


@unittest.skipUnless(shutil.which("semgrep"), "semgrep not installed — CI doesn't install it (see .github/workflows/lint.yml); run locally on a dev box with semgrep on PATH")
class TestCommandInjectionRule(unittest.TestCase):
    """nemofleet-py-command-injection is a taint rule: request/env input -> shell=True sink. Its
    sink patterns need `focus-metavariable` pinned to the actual command argument — without it,
    ANY tainted argument (including env=ENV, which is legitimately built from os.environ for
    PATH passthrough) makes the whole call "tainted", producing 10 false positives across
    agent-dashboard.py/worker-itops.py's already-safe (shlex.quote()d + regex-validated)
    subprocess.run(cmd, shell=True, env=ENV) call sites before this was fixed."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, content):
        path = os.path.join(self.tmp, "t.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_real_injection_via_request_arg_is_caught(self):
        path = self._write(
            "def h(request):\n"
            "    name = request.args.get('name')\n"
            "    import subprocess; subprocess.run(f'echo {name}', shell=True)\n")
        self.assertIn("nemofleet-py-command-injection", _scan(path))

    def test_real_injection_via_os_environ_into_os_system_is_caught(self):
        path = self._write(
            "import os\n"
            "def h():\n"
            "    cmd = os.environ.get('USER_CMD')\n"
            "    os.system(cmd)\n")
        self.assertIn("nemofleet-py-command-injection", _scan(path))

    def test_env_kwarg_built_from_os_environ_is_not_a_false_positive(self):
        # the exact shape this codebase uses everywhere: a literal/quoted command string, with
        # env=ENV (ENV built from os.environ) passed only to preserve PATH — not itself the sink.
        path = self._write(
            "import os, subprocess\n"
            "ENV = dict(os.environ, PATH='/bin')\n"
            "def h():\n"
            "    subprocess.run('echo hello', shell=True, env=ENV)\n")
        self.assertNotIn("nemofleet-py-command-injection", _scan(path))

    def test_shlex_quoted_dynamic_value_is_not_a_false_positive(self):
        path = self._write(
            "import os, shlex, subprocess\n"
            "ENV = dict(os.environ)\n"
            "def h(body):\n"
            "    sb = body.get('sb')\n"
            "    if sb not in ('team-lead', 'worker-a'):\n"
            "        return\n"
            "    cmd = f\"nemoclaw {shlex.quote(sb)} status\"\n"
            "    subprocess.run(cmd, shell=True, env=ENV)\n")
        self.assertNotIn("nemofleet-py-command-injection", _scan(path))


if __name__ == "__main__":
    unittest.main()
