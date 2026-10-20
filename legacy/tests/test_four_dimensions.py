import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_four_dimension_assessment import INPUTS, build, calculate, concentration_bounds
from workflow_status import read_json


class FourDimensionTests(unittest.TestCase):
    def setUp(self):
        self.data = [read_json(ROOT / path) for path in INPUTS]

    def test_missing_origin_shares_produce_bounds_never_point_hhi(self):
        bounds = concentration_bounds(80, 100, 5)
        self.assertIsNone(bounds["country_hhi_point"])
        # Valid, nonidentical country distributions with the same named-group total.
        for shares in ([.16] * 5 + [.2], [.4, .1, .1, .1, .1] + [.1, .1],
                       [.16] * 5 + [.02] * 10):
            hhi = sum(x * x for x in shares) * 10000
            self.assertLessEqual(bounds["hhi_lower_bound_10000"], hhi + 1e-9)
            self.assertGreaterEqual(bounds["hhi_upper_bound_10000"], hhi - 1e-9)
            self.assertLessEqual(bounds["largest_origin_share_lower_pct"], max(shares) * 100)
            self.assertGreaterEqual(bounds["largest_origin_share_upper_pct"], max(shares) * 100)

    def test_invalid_group_data_rejected(self):
        for values in ((101, 100, 5), (-1, 100, 5), (1, 0, 5),
                       (1, 100, 0), (1, 100, True), (float("nan"), 100, 5)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                concentration_bounds(*values)

    def test_bill_shares_have_one_scope_and_sum_to_100(self):
        result = calculate(*self.data)
        metrics = {r["indicator_id"]: r for r in result["metrics"]}
        self.assertEqual(metrics["selected_import_value"]["value"], 33533)
        self.assertAlmostEqual(sum(v["value"] for k, v in metrics.items()
                                   if k.endswith("_import_bill_share")), 100)
        self.assertAlmostEqual(metrics["crude_oil_import_bill_share"]["value"], 23108 / 33533 * 100)
        self.assertAlmostEqual(metrics["grid_investment_share"]["value"], 6083 / 17770 * 100)

    def test_coordination_proxies_do_not_become_efficiency_or_security_score(self):
        result = calculate(*self.data)
        metrics = {r["indicator_id"]: r for r in result["metrics"]}
        self.assertAlmostEqual(metrics["electricity_energy_growth_gap"]["value"], 2.5)
        self.assertEqual(metrics["gas_power_use_share"]["value"], 18)
        for key in ("composite_score", "gas_to_power_efficiency", "adequacy_margin",
                    "national_co2_total", "net_import_dependency_pct"):
            self.assertIsNone(result[key])

    def test_units_and_source_cannot_silently_change(self):
        for target, key, replacement in ((1, "source_id", "S05"),):
            changed = deepcopy(self.data)
            changed[target][key] = replacement
            with self.assertRaises(ValueError):
                calculate(*changed)
        changed = deepcopy(self.data)
        changed[1]["units"]["grid_investment_100m_yuan"] = "元"
        with self.assertRaises(ValueError):
            calculate(*changed)

    def test_failed_admission_stops_before_calculation(self):
        with patch("build_four_dimension_assessment.check_formal_inputs",
                   return_value={"passed": False, "accepted_inputs": []}), \
             patch("build_four_dimension_assessment.calculate") as computation:
            with self.assertRaises(ValueError):
                build(ROOT)
            computation.assert_not_called()

    def test_each_metric_and_finding_has_resolvable_provenance(self):
        result = calculate(*self.data)
        datasets = dict(zip(INPUTS, self.data))
        ids = {r["indicator_id"] for r in result["metrics"]}
        self.assertEqual(len(ids), len(result["metrics"]))
        for metric in result["metrics"]:
            self.assertTrue(metric["formula"])
            for ref in metric["input_refs"]:
                data = datasets[ref["dataset_path"]]
                fields = (data["columns"] if "columns" in data
                          else [r["indicator_id"] for r in data["observations"]])
                self.assertEqual(ref["source_id"], data["source_id"])
                self.assertTrue(set(ref["fields"]).issubset(fields))
        for finding in result["findings"]:
            self.assertTrue(set(finding["metric_ids"]).issubset(ids))
