import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _load import load, ROOT

# The Action Catalog (policy/action-catalog.json) is the fleet's decision boundary. These tests make it
# ENFORCED rather than decorative: they bind it 1:1 to worker-itops' real capabilities and prove the
# guardrail blocks every `forbidden` example. If the code gains an action the catalog doesn't list (or
# vice versa), or a forbidden action stops being blocked, CI fails here — the fleet cannot silently
# widen (or a guarantee silently narrow) its own boundary.
pc = load("services/bridge/policy_catalog.py", "policy_catalog")
wi = load("services/bridge/worker-itops.py", "worker_itops")
CAT = pc.load()


class TestCatalogSchema(unittest.TestCase):
    def test_validates(self):
        errs = pc.validate(CAT)
        self.assertEqual(errs, [], f"catalog failed its own invariants: {errs}")

    def test_markdown_view_is_in_sync(self):
        # policy/action-catalog.md is a generated view; it must be byte-identical to render_markdown so
        # the human-readable "contract" can never drift from the machine-readable boundary.
        md_path = os.path.join(ROOT, "policy", "action-catalog.md")
        with open(md_path, encoding="utf-8") as f:
            on_disk = f.read()
        self.assertEqual(on_disk, pc.render_markdown(CAT),
                         "policy/action-catalog.md is stale — regenerate: python3 services/bridge/policy_catalog.py > policy/action-catalog.md")


class TestCatalogBindsToCode(unittest.TestCase):
    """The completeness guarantee: the set of device nvram actions the catalog describes must EXACTLY
    equal the set of nvram actions worker-itops can actually execute — no undocumented capability, no
    phantom entry — and every described value must match the code's real value."""

    def test_nvram_action_set_matches_code_exactly(self):
        catalog_nvram = pc.nvram_action_ids(CAT)
        code_nvram = set(wi.EBG_ACTIONS) | set(wi.EBG_MULTI)
        undocumented = code_nvram - catalog_nvram
        phantom = catalog_nvram - code_nvram
        self.assertEqual(undocumented, set(), f"code can execute actions absent from the catalog: {undocumented}")
        self.assertEqual(phantom, set(), f"catalog lists actions the code cannot execute: {phantom}")

    def test_single_key_effects_match_code(self):
        for aid, tup in wi.EBG_ACTIONS.items():
            a = pc.by_id(CAT, aid)
            self.assertIsNotNone(a, f"{aid} missing from catalog")
            eff = a["effect"]
            self.assertEqual(eff["type"], "nvram-apply", f"{aid}: wrong effect type")
            self.assertEqual((eff["key"], eff["value"], eff["restart"]), (tup[0], tup[1], tup[2]),
                             f"{aid}: catalog effect diverged from code EBG_ACTIONS")

    def test_multi_key_effects_match_code(self):
        for aid, spec in wi.EBG_MULTI.items():
            a = pc.by_id(CAT, aid)
            self.assertIsNotNone(a, f"{aid} missing from catalog")
            eff = a["effect"]
            self.assertEqual(eff["type"], "nvram-multi", f"{aid}: wrong effect type")
            self.assertEqual([list(s) for s in eff["sets"]], [list(s) for s in spec["sets"]],
                             f"{aid}: catalog sets diverged from code EBG_MULTI")
            self.assertEqual((eff["verify_key"], eff["want"], eff["restart"]),
                             (spec["verify_key"], spec["want"], spec["script"]),
                             f"{aid}: catalog verify/restart diverged from code EBG_MULTI")


class TestBoundaryInvariants(unittest.TestCase):
    def test_auto_actions_are_reversible_single_device_nvram(self):
        # an action that runs WITHOUT a human must be a single-device, reversible nvram change — never
        # firmware, never a rollback, never multi-device, never irreversible.
        for a in CAT["actions"]:
            if a["approval_tier"] != "auto":
                continue
            self.assertIn(a["effect"]["type"], pc.NVRAM_EFFECTS, f"{a['id']}: auto action is not an nvram change")
            self.assertTrue(a["reversibility"]["reversible"], f"{a['id']}: auto action must be reversible")
            self.assertEqual(a["blast_radius"]["scope"], "single-device", f"{a['id']}: auto action must be single-device")

    def test_surface_reopening_and_high_risk_actions_need_a_human(self):
        # re-enabling WPS, disabling AiProtection, rollback, firmware — none may be `auto`.
        for aid in ("ebg-wps-on", "ebg-aiprotect-off", "rollback-config", "firmware-apply"):
            a = pc.by_id(CAT, aid)
            self.assertIsNotNone(a, f"{aid} missing")
            self.assertEqual(a["approval_tier"], "human", f"{aid} must require a human")
            self.assertEqual(a.get("requires"), "approval_token", f"{aid} must require an approval token")


class TestForbiddenIsActuallyBlocked(unittest.TestCase):
    """The negative guarantee: every `forbidden` action carries a natural-language example, and the
    guardrail's deterministic pre-filter must block it — so the boundary is proven, not just asserted."""

    def test_every_forbidden_example_is_blocked_by_the_guardrail(self):
        forbidden = [a for a in CAT["actions"] if a["approval_tier"] == "forbidden"]
        self.assertTrue(forbidden, "expected at least one forbidden action in the catalog")
        for a in forbidden:
            phrase = a["blocked_example"]
            verdict = wi._guardrail_prefilter(phrase)
            self.assertIsNotNone(verdict, f"{a['id']}: guardrail did NOT block {phrase!r}")
            self.assertEqual(verdict["verdict"], "block", f"{a['id']}: guardrail verdict was not 'block' for {phrase!r}")


if __name__ == "__main__":
    unittest.main()
