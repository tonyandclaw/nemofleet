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


class TestSkillStats(unittest.TestCase):
    def test_success_rate_and_last_ts(self):
        outcomes = [
            {"skill": "review-gate", "pass": True, "ts": "2026-07-10 01:00:00"},
            {"skill": "review-gate", "pass": False, "ts": "2026-07-10 02:00:00"},
            {"skill": "review-gate", "pass": True, "ts": "2026-07-10 03:00:00"},
            {"skill": "it-delegate-worker", "pass": True, "ts": "2026-07-10 01:00:00"},
        ]
        stats = wi_skills.compute_skill_stats(outcomes, min_samples=3)
        self.assertEqual(stats["review-gate"]["uses"], 3)
        self.assertEqual(stats["review-gate"]["passes"], 2)
        self.assertAlmostEqual(stats["review-gate"]["success_rate"], 0.667, places=2)
        self.assertEqual(stats["review-gate"]["last_ts"], "2026-07-10 03:00:00")
        self.assertTrue(stats["review-gate"]["sample_ok"])          # 3 uses, min_samples=3

    def test_sample_ok_false_below_threshold(self):
        outcomes = [{"skill": "new-skill", "pass": True, "ts": "2026-07-10 01:00:00"}]
        stats = wi_skills.compute_skill_stats(outcomes, min_samples=3)
        self.assertFalse(stats["new-skill"]["sample_ok"])

    def test_events_without_skill_are_ignored(self):
        stats = wi_skills.compute_skill_stats([{"pass": True, "ts": "x"}, {"skill": "", "pass": True}])
        self.assertEqual(stats, {})

    def test_downstream_stats_is_informational_not_gating(self):
        # A skill with a terrible track record must NOT flip an otherwise-clean insert to reject —
        # downstream_stats is attached for visibility only, never folded into checks/verdict/score.
        bad_stats = {"fix-wps": {"uses": 10, "passes": 1, "success_rate": 0.1, "sample_ok": True, "last_ts": "x"}}
        v = wi_skills.curate("insert", GOOD, [], downstream_stats=bad_stats)
        self.assertEqual(v["verdict"], "approve")
        self.assertEqual(v["score"], 100)
        self.assertEqual(v["downstream_stats"], bad_stats["fix-wps"])
        self.assertTrue(all(c["name"] != "downstream-success" for c in v["checks"]))

    def test_downstream_stats_absent_when_no_data_for_skill(self):
        v = wi_skills.curate("insert", GOOD, [], downstream_stats={"other-skill": {"uses": 5}})
        self.assertNotIn("downstream_stats", v)


if __name__ == "__main__":
    unittest.main()
