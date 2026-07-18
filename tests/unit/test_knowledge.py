"""Unit tests for the shared knowledge layer (services/bridge/knowledge.py)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "bridge")))
import knowledge  # noqa: E402


class TestKnowledge(unittest.TestCase):
    def test_baseline_is_the_real_approved_config(self):
        b = knowledge.baseline_conf("ebg19p")
        self.assertIn("device.model = EBG19P", b)
        self.assertIn("ssh.password_login = false", b)          # a security-relevant approved value
        self.assertNotIn("fallback", b.lower())                  # the canonical file, not the embedded fallback

    def test_security_keys_shared_definition(self):
        keys = knowledge.security_keys("ebg19p")
        self.assertGreaterEqual(len(keys), 8)   # the tracked set grows as more auto remediations get a drift key
        # the original core set + the controls added so the Attack-surface panel shows a real verdict
        for k in ("wps.enabled", "upnp.enabled", "ssh.password_login", "firewall.dos_protection",
                  "telnet.enabled", "samba.enabled", "ftp.enabled", "ddns.enabled", "aiprotection.enabled"):
            self.assertIn(k, keys)

    def test_version_stable_and_hashlike(self):
        v1, v2 = knowledge.version(), knowledge.version()
        self.assertEqual(v1, v2)                                  # deterministic
        self.assertEqual(len(v1), 12)
        int(v1, 16)                                              # is hex

    def test_get_knowledge_bundle_shape(self):
        k = knowledge.get_knowledge()
        for field in ("version", "baseline", "security_keys", "lessons", "fleet", "sources"):
            self.assertIn(field, k)
        self.assertEqual(k["security_keys"]["ebg19p"], knowledge.security_keys("ebg19p"))

    def test_fallback_when_canonical_dir_missing(self):
        saved = knowledge.KNOWLEDGE_DIR
        try:
            knowledge.KNOWLEDGE_DIR = "/no/such/knowledge/dir"
            self.assertIn("fallback", knowledge.baseline_conf().lower())      # degrades, does not crash
            self.assertEqual(len(knowledge.security_keys("ebg19p")), 8)        # embedded fallback keys
        finally:
            knowledge.KNOWLEDGE_DIR = saved


if __name__ == "__main__":
    unittest.main()
