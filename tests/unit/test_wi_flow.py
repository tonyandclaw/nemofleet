"""Unit tests for wi_flow — cross-node flow event ring."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "bridge")))
import wi_flow  # noqa: E402


class TestFlow(unittest.TestCase):
    def setUp(self):
        wi_flow.FLOW.clear()
        wi_flow.configure("A")

    def test_node_from_zone(self):
        wi_flow.flow("team-lead", "monitor-scan", "working")
        e = wi_flow.recent(1)[0]
        self.assertEqual((e["node"], e["peer"], e["status"]), ("worker-a", "team-lead", "working"))

    def test_node_override(self):
        wi_flow.flow("human", "intake", "received", node="team-lead")
        self.assertEqual(wi_flow.recent(1)[0]["node"], "team-lead")

    def test_ring_caps_and_order(self):
        for i in range(80):
            wi_flow.flow("x", "t%d" % i, "done")
        self.assertLessEqual(len(wi_flow.FLOW), 60)
        self.assertEqual(wi_flow.recent(1)[0]["task"], "t79")

    def test_field_truncation(self):
        wi_flow.flow("p", "T" * 100, "done", "D" * 200)
        e = wi_flow.recent(1)[0]
        self.assertLessEqual(len(e["task"]), 40)
        self.assertLessEqual(len(e["detail"]), 100)


if __name__ == "__main__":
    unittest.main()
