"""Unit tests for wi_util — the worker's pure helper module."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "bridge")))
import wi_util  # noqa: E402


class TestWiUtil(unittest.TestCase):
    def test_vtuple_numeric_not_lexical(self):
        self.assertGreater(wi_util.vtuple("386_510"), wi_util.vtuple("386_59"))
        self.assertEqual(wi_util.vtuple("3.0.0.4.388_24698"), (3, 0, 0, 4, 388, 24698))
        self.assertEqual(wi_util.vtuple(None), ())            # None-safe

    def test_sig_tier(self):
        self.assertEqual(wi_util.sig_tier("sha256WithRSAEncryption"), "sha256")
        self.assertEqual(wi_util.sig_tier("sha1WithRSA"), "sha1")
        self.assertIsNone(wi_util.sig_tier("weirdAlg"))

    def test_cipher_bad(self):
        self.assertTrue(wi_util.cipher_bad("ECDHE-RSA-RC4-SHA", ["RC4"]))
        self.assertTrue(wi_util.cipher_bad("ECDHE-RSA-AES128-SHA", ["@SHA1MAC"]))     # -SHA suffix family
        self.assertFalse(wi_util.cipher_bad("ECDHE-RSA-AES256-GCM-SHA384", ["RC4", "3DES"]))

    def test_days_left(self):
        self.assertIsNone(wi_util.days_left("not-a-date"))
        self.assertIsInstance(wi_util.days_left("2099-01-01"), int)

    def test_conf_kv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False, encoding="utf-8") as f:
            f.write("a.b = 1\nUPPER_KEY = x\n# comment\nnot a kv line\n")
            p = f.name
        try:
            d = wi_util.conf_kv(p)
            self.assertEqual(d.get("a.b"), "1")
            self.assertEqual(d.get("UPPER_KEY"), "x")          # uppercase keys ok (UCI-style)
            self.assertNotIn("# comment", d)
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
