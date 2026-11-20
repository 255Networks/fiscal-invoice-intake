import csv
import tempfile
import unittest
from pathlib import Path

from intake import ROOT, classify, load_rows, write_queues


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.customers, self.requests, self.history = [load_rows(ROOT / "data", n) for n in ("customers", "requests", "prior")]

    def run_batch(self):
        return classify(self.customers, self.requests, self.history)

    def test_split(self):
        self.assertEqual([len(q) for q in self.run_batch().values()], [1, 4, 2])

    def test_no_fuzzy_automatic_match(self):
        row = next(r for r in self.run_batch()["review"] if r["request_id"] == "REQ-03")
        self.assertEqual(row["suggested_customer"], "DEMO-2")

    def test_order_independent_conflict(self):
        self.requests.reverse()
        rows = [r for r in self.run_batch()["review"] if r["reason"] == "CONFLICTING_PAYLOAD"]
        self.assertEqual({r["request_id"] for r in rows}, {"REQ-05", "REQ-06"})

    def test_history_drift(self):
        self.history[0]["amount_minor"] = "3900"
        self.assertIn("REQ-04", [r["request_id"] for r in self.run_batch()["review"]])

    def test_duplicate_request_id(self):
        self.requests.append(self.requests[0])
        with self.assertRaises(ValueError):
            self.run_batch()

    def test_invalid_amount_and_currency(self):
        for field, value, reason in [("amount_minor", "1.5", "INVALID_AMOUNT"), ("currency","USD","UNSUPPORTED_CURRENCY")]:
            with self.subTest(reason=reason):
                row = dict(self.requests[0], **{field:value})
                self.assertEqual(classify(self.customers, [row], self.history)["review"][0]["reason"], reason)

    def test_export_preserves_formula_like_text(self):
        self.requests[0]["request_id"] = "=fictional"
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            write_queues(self.run_batch(), out)
            with (out / "ready.csv").open(newline="") as handle:
                self.assertEqual(next(csv.DictReader(handle))["request_id"], "'=fictional")
            with self.assertRaises(ValueError):
                write_queues(self.run_batch(), out)
