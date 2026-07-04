"""Unit tests for wi_skills — SkillOS-style skill curation (arXiv 2605.06614)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "bridge")))
import wi_skills  # noqa: E402

GOOD = ("---\nname: fix-wps\ndescription: disable WPS on EBG19P and verify\ntags: [ops]\n---\n"
        "# Fix WPS\nSet wps.enabled=false via applyapp.cgi, then re-read the nvram to verify.\n")


class TestParseAndQuality(unittest.TestCase):
    def test_parse_frontmatter(self):
        sk = wi_skills.parse_skill(GOOD)
        self.assertEqual(sk["name"], "fix-wps")
        self.assertIn("disable WPS", sk["description"])
        self.assertIn("applyapp", sk["body"])

    def test_good_skill_approved(self):
        self.assertEqual(wi_skills.curate("insert", GOOD, [])["verdict"], "approve")

    def test_missing_frontmatter_rejected(self):
        v = wi_skills.curate("insert", "# heading only\nsome instructions long enough to pass body check", [])
        self.assertEqual(v["verdict"], "reject")
        self.assertTrue(any(c["name"] == "frontmatter" and not c["pass"] for c in v["checks"]))

    def test_verbose_dump_rejected_by_conciseness(self):
        body = "\n".join("step %d — do a thing" % i for i in range(200))   # a verbatim trajectory dump
        v = wi_skills.curate("insert", "---\nname: dump\ndescription: raw dump\n---\n" + body, [])
        self.assertEqual(v["verdict"], "reject")
        self.assertTrue(any(c["name"] == "concise" and not c["pass"] for c in v["checks"]))


class TestAntiProliferation(unittest.TestCase):
    def test_redundant_insert_rejected(self):
        existing = [wi_skills.parse_skill(GOOD)]
        v = wi_skills.curate("insert", GOOD, existing)          # inserting a near-duplicate
        self.assertEqual(v["verdict"], "reject")
        self.assertTrue(any(c["name"] == "non-redundant" and not c["pass"] for c in v["checks"]))

    def test_distinct_insert_approved(self):
        existing = [wi_skills.parse_skill(GOOD)]
        other = ("---\nname: rotate-token\ndescription: rotate the bridge token weekly\n---\n"
                 "# Rotate\nRun rotate-bridge-token.sh and reapply the worker_bridge policy.\n")
        self.assertEqual(wi_skills.curate("insert", other, existing)["verdict"], "approve")


class TestBM25AndDelete(unittest.TestCase):
    def test_bm25_ranks_relevant_first(self):
        skills = [wi_skills.parse_skill(GOOD),
                  wi_skills.parse_skill("---\nname: rotate-token\ndescription: rotate bridge token\n---\nrotate the token")]
        r = wi_skills.bm25_search("disable wps on the device", skills)
        self.assertTrue(r and r[0]["name"] == "fix-wps")

    def test_delete_existing_ok_missing_rejected(self):
        self.assertEqual(wi_skills.curate("delete", "", [{"name": "fix-wps", "description": "", "body": ""}], name="fix-wps")["verdict"], "approve")
        self.assertEqual(wi_skills.curate("delete", "", [], name="nope")["verdict"], "reject")


if __name__ == "__main__":
    unittest.main()
