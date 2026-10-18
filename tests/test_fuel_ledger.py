import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.fuel_ledger import FuelLedger


class FuelLedgerTests(unittest.TestCase):
    def setUp(self):
        # Synthetic physical example, never used as a China observation.
        self.closed = FuelLedger(2024, "synthetic_gas", "synthetic_unit", "test_state", True,
                                 production=100, imports=20, exports=5,
                                 domestic_use_excluding_losses=105, net_stock_addition=4,
                                 losses=3, statistical_difference=3)

    def test_complete_signed_ledger_closes(self):
        self.assertTrue(self.closed.require_closed()["closed"])
        drawn = replace(self.closed, net_stock_addition=-4, domestic_use_excluding_losses=113)
        self.assertTrue(drawn.require_closed()["closed"])
        negative_difference = replace(self.closed, statistical_difference=-3,
                                      domestic_use_excluding_losses=111)
        self.assertTrue(negative_difference.require_closed()["closed"])

    def test_unknown_is_not_zero_even_if_known_terms_balance(self):
        missing = replace(self.closed, exports=None, domestic_use_excluding_losses=110)
        result = missing.evaluate()
        self.assertIsNone(result["residual"])
        self.assertIsNone(result["closed"])
        self.assertEqual(result["missing_terms"], ["exports"])
        with self.assertRaises(ValueError):
            missing.require_closed()

    def test_scope_and_reference_state_required(self):
        for ledger in (replace(self.closed, reference_state=None),
                       replace(self.closed, common_boundary_verified=False)):
            self.assertEqual(ledger.evaluate()["status"], "boundary_unverified")
            with self.assertRaises(ValueError):
                ledger.require_closed()

    def test_residual_cannot_be_used_as_a_balancing_plug(self):
        altered = replace(self.closed, production=101)
        self.assertEqual(altered.evaluate()["residual"], 1)
        self.assertFalse(altered.evaluate()["closed"])
        self.assertEqual(altered.statistical_difference, 3)
        with self.assertRaises(ValueError):
            altered.require_closed()

    def test_invalid_physical_quantities_and_tolerance_rejected(self):
        for edits in ({"production": -1}, {"imports": float("nan")}, {"losses": True},
                      {"common_boundary_verified": 1}, {"unit": ""},
                      {"reference_state": " "}, {"year": 2024.5}):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                replace(self.closed, **edits)
        for tolerance in (-1, float("inf"), True):
            with self.assertRaises(ValueError):
                self.closed.evaluate(tolerance)
