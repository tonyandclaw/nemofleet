import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "services", "bridge"))
import proactive_backoff as b


class TestAlertSignature(unittest.TestCase):
    def test_order_independent(self):
        self.assertEqual(b.alert_signature(["a", "b"], [], []), b.alert_signature(["b", "a"], [], []))

    def test_changes_with_content(self):
        self.assertNotEqual(b.alert_signature(["a"], [], []), b.alert_signature(["a", "c"], [], []))

    def test_warning_and_stale_are_part_of_state(self):
        self.assertNotEqual(b.alert_signature(["a"], [], []), b.alert_signature(["a"], ["w"], []))
        self.assertNotEqual(b.alert_signature(["a"], [], []), b.alert_signature(["a"], [], ["s"]))


class TestNextAutoInterval(unittest.TestCase):
    """Auto-mode aging: 5m base, ×2 per unchanged cycle, capped at 12h; reset to 5m the moment the
    alert state changes (a genuinely new event) so a new problem is picked up quickly."""
    def test_first_cycle_is_base(self):
        r = b.next_auto_interval(None, None, ["dev offline"], [], [])
        self.assertEqual(r["interval"], 300)
        self.assertTrue(r["changed"])

    def test_same_alert_ages_by_factor(self):
        sig = b.alert_signature(["dev offline"], [], [])
        self.assertEqual(b.next_auto_interval(300, sig, ["dev offline"], [], [])["interval"], 600)
        self.assertEqual(b.next_auto_interval(600, sig, ["dev offline"], [], [])["interval"], 1200)

    def test_caps_at_12h(self):
        sig = b.alert_signature(["dev offline"], [], [])
        iv = 1200
        for _ in range(12):
            iv = b.next_auto_interval(iv, sig, ["dev offline"], [], [])["interval"]
        self.assertEqual(iv, 43200)   # 12h cap, never exceeded

    def test_changed_alert_resets_to_base(self):
        old_sig = b.alert_signature(["dev offline"], [], [])
        r = b.next_auto_interval(43200, old_sig, ["NEW critical"], [], [])
        self.assertEqual(r["interval"], 300)
        self.assertTrue(r["changed"])

    def test_cleared_alert_also_resets(self):
        # a problem clearing (fewer alerts) is a state change too → become responsive again
        old_sig = b.alert_signature(["dev offline"], ["cve up"], [])
        r = b.next_auto_interval(9600, old_sig, [], [], [])
        self.assertEqual(r["interval"], 300)

    def test_bad_prev_interval_falls_back_to_base(self):
        sig = b.alert_signature(["x"], [], [])
        self.assertEqual(b.next_auto_interval("garbage", sig, ["x"], [], [])["interval"], 600)


if __name__ == "__main__":
    unittest.main()
