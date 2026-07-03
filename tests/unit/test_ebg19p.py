import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load

ebg = load("services/bridge/ebg19p.py", "ebg19p")


class TestCredParsing(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(ebg.parse_cred("192.168.50.1|admin|s3cret"),
                         ("192.168.50.1", "admin", "s3cret"))

    def test_password_may_contain_pipe(self):
        # the old `IFS='|' read IP USER PASS` truncated such passwords; the client keeps them
        self.assertEqual(ebg.parse_cred("10.0.0.1|admin|p@ss|w0rd"),
                         ("10.0.0.1", "admin", "p@ss|w0rd"))

    def test_whitespace_trimmed(self):
        self.assertEqual(ebg.parse_cred("  10.0.0.1|u|p\n"), ("10.0.0.1", "u", "p"))

    def test_malformed_raises(self):
        for bad in ("", "onlyip", "ip|user"):
            with self.assertRaises(ebg.EBG19PError):
                ebg.parse_cred(bad)


class TestNvramValueParsing(unittest.TestCase):
    def test_json_value(self):
        self.assertEqual(ebg.parse_nvram_value('{"wps_enable":"0"}'), "0")
        self.assertEqual(ebg.parse_nvram_value('{"sshd_enable":"1"}'), "1")

    def test_non_json_falls_back_to_stripped_text(self):
        self.assertEqual(ebg.parse_nvram_value("  raw text \n"), "raw text")

    def test_empty(self):
        self.assertEqual(ebg.parse_nvram_value(""), "")


if __name__ == "__main__":
    unittest.main()
