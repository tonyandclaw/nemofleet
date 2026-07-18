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


class TestRuntimeGate(unittest.TestCase):
    """The P1 runtime device gate. pc.gate() is the pure decision; wi._policy_gate() is worker-itops'
    fail-open wrapper actually wired in front of run_ebg_remediate."""

    def test_gate_allows_every_real_nvram_action(self):
        # the gate must never deny a legitimate in-catalog nvram action — i.e. zero behaviour change
        # for everything the fleet already does today.
        for aid in set(wi.EBG_ACTIONS) | set(wi.EBG_MULTI):
            g = pc.gate(CAT, aid, allow_effects=pc.NVRAM_EFFECTS)
            self.assertTrue(g["allow"], f"{aid} wrongly denied by the gate: {g['reason']}")

    def test_gate_denies_unknown_action(self):
        self.assertFalse(pc.gate(CAT, "ebg-please-just-brick-it", allow_effects=pc.NVRAM_EFFECTS)["allow"])

    def test_gate_denies_forbidden_action(self):
        self.assertFalse(pc.gate(CAT, "factory-reset")["allow"])

    def test_gate_denies_non_nvram_id_on_the_device_path(self):
        # rollback/firmware are real catalog actions but must not flow through the nvram device path
        self.assertFalse(pc.gate(CAT, "rollback-config", allow_effects=pc.NVRAM_EFFECTS)["allow"])
        self.assertFalse(pc.gate(CAT, "firmware-apply", allow_effects=pc.NVRAM_EFFECTS)["allow"])

    def test_worker_wrapper_allows_real_action_from_default_catalog(self):
        wi._CATALOG = None; wi._CATALOG_TRIED = False   # force a real load from the default catalog path
        g = wi._policy_gate("ebg-wps", allow_effects=wi.policy_catalog.NVRAM_EFFECTS)
        self.assertTrue(g["allow"], f"wrapper wrongly denied a real action: {g['reason']}")

    def test_worker_wrapper_fails_open_when_catalog_unavailable(self):
        # a missing/unloadable catalog must ALLOW (never block remediation because a policy file is gone)
        wi._CATALOG = None; wi._CATALOG_TRIED = True    # simulate: load already attempted and failed
        g = wi._policy_gate("ebg-wps", allow_effects=None)
        self.assertTrue(g["allow"], "gate must fail OPEN when the catalog is unavailable")
        wi._CATALOG_TRIED = False                       # reset so a later call re-loads cleanly


class TestAttackSurfaceDriftMap(unittest.TestCase):
    """The Security page's Attack-surface panel maps each auto nvram remediation to a baseline-drift
    key so it can show hardened/exposed. A control with no mapping renders the opaque 'nvram-only'
    state — so every auto nvram catalog action MUST have an ATTACK_SURFACE_DRIFT entry, and each mapped
    drift key must be a real baseline security key. This guard stops 'nvram-only' from silently
    reappearing when a new auto action is added to the catalog."""
    import re as _re

    def _drift_map(self):
        js = open(os.path.join(ROOT, "services/bridge/web/app.js"), encoding="utf-8").read()
        block = self._re.search(r"const ATTACK_SURFACE_DRIFT = \{(.*?)\};", js, self._re.S).group(1)
        return dict(self._re.findall(r"'([\w-]+)':\s*'([\w.]+)'", block))

    def test_every_auto_nvram_action_has_a_drift_mapping(self):
        drift = self._drift_map()
        auto_nvram = {a["id"] for a in CAT["actions"]
                      if a.get("approval_tier") == "auto" and str((a.get("effect") or {}).get("type", "")).startswith("nvram")}
        unmapped = auto_nvram - set(drift)
        self.assertEqual(unmapped, set(), f"auto nvram actions with no drift mapping (would show 'nvram-only'): {unmapped}")

    def test_mapped_drift_keys_are_real_baseline_security_keys(self):
        import json
        drift = self._drift_map()
        with open(os.path.join(ROOT, "knowledge/security-keys.json"), encoding="utf-8") as f:
            sec = set(json.load(f).get("ebg19p", []))
        missing = {k for k in drift.values() if k not in sec}
        self.assertEqual(missing, set(), f"drift keys not tracked in security-keys.json (won't ever flag exposed): {missing}")


if __name__ == "__main__":
    unittest.main()
