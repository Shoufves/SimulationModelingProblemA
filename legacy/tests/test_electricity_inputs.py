import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_electricity_inputs import INPUTS, build, calculate
from workflow_status import read_json


class ElectricityInputTests(unittest.TestCase):
    def setUp(self):
        self.data = [read_json(ROOT / p) for p in INPUTS]

    def test_units_and_four_category_closure(self):
        result = calculate(*self.data)
        self.assertAlmostEqual(result["demand"]["total"]["value"], 9852.1)
        self.assertEqual(result["demand"]["closure_residual_twh"], 0)
        rows = result["demand"]["sectors"]
        self.assertAlmostEqual(sum(r["share_pct"] for r in rows), 100)
        self.assertAlmostEqual(rows[1]["consumption"]["value"], 6387.4)
        self.assertAlmostEqual(rows[1]["share_pct"], 63874 / 98521 * 100)
        self.assertEqual(result["separate_industrial_generation_reference"]["raw_value"], 94181)

    def test_inconsistent_total_cannot_be_renormalized_away(self):
        changed = deepcopy(self.data)
        changed[0]["observations"][0]["value"] += 1
        with self.assertRaises(ValueError):
            calculate(*changed)

    def test_storage_and_biomass_units_keep_unknowns(self):
        result = calculate(*self.data)
        tech = result["renewable_reference"]
        self.assertAlmostEqual(tech["pumped_storage_capacity"]["value"], 58.69)
        self.assertAlmostEqual(tech["biomass_capacity"]["value"], 45.99)
        self.assertAlmostEqual(tech["biomass_generation"]["value"], 208.3)
        self.assertEqual(tech["renewable_generation_total"]["value"], 3460)
        for key in ("pumped_storage_energy_gwh", "pumped_storage_duration_h",
                    "biomass_co2_factor", "biomass_emissions", "hourly_load_mw"):
            self.assertIsNone(result["unknowns"][key])

    def test_utilization_never_becomes_capacity_factor_or_curtailment(self):
        result = calculate(*self.data)
        self.assertEqual(result["renewable_reference"]["wind_utilization_pct"]["value"], 95.9)
        self.assertEqual(result["renewable_reference"]["pv_utilization_pct"]["value"], 96.8)
        for key in ("capacity_factors", "curtailed_energy_twh", "national_supply_demand_gap_twh"):
            self.assertIsNone(result["unknowns"][key])

    def test_different_categories_and_versions_survive(self):
        result = calculate(*self.data)
        tech = result["renewable_reference"]
        self.assertAlmostEqual(tech["solar_capacity_summary"]["value"], 887)
        self.assertAlmostEqual(tech["pv_capacity_detailed"]["value"], 886)
        generation = next(r for r in result["version_comparisons"] if r["label"] == "水电发电")
        self.assertAlmostEqual(generation["left"]["value"], 1425.68)
        self.assertAlmostEqual(generation["right"]["value"], 1423.9)
        pv = next(r for r in result["version_comparisons"] if r["label"] == "太阳能/光伏发电")
        self.assertEqual(pv["compatibility"], "category_bridge_pending")

    def test_bad_source_period_unit_and_nonfinite_rejected(self):
        cases = [(0, "source_id", "S13"), (1, "year", 2025)]
        for i, field, value in cases:
            changed = deepcopy(self.data)
            changed[i][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                calculate(*changed)
        for field, value in (("unit", "MWh"), ("value", float("nan")), ("value", -1)):
            changed = deepcopy(self.data)
            changed[1]["observations"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                calculate(*changed)

    def test_new_anchor_and_reference_fields_have_traceable_originals(self):
        result = calculate(*self.data)
        fields = list(result["renewable_reference"].values())
        fields += [result["demand"]["total"], result["demand"]["growth"],
                   result["separate_industrial_generation_reference"]]
        fields += [r[k] for r in result["demand"]["sectors"] for k in ("consumption", "growth")]
        self.assertEqual(len(fields), 26)
        datasets = dict(zip(INPUTS, self.data))
        for field in fields:
            ref = field["input_ref"]
            rows = datasets[ref["dataset_path"]]["observations"]
            original = next(r for r in rows if r["indicator_id"] == ref["field"])
            self.assertEqual(original["value"], field["raw_value"])
            self.assertEqual(original["unit"], field["raw_unit"])
            self.assertTrue(ref["locator"])

    def test_failed_or_incomplete_admission_stops_before_calculation(self):
        for passed in (False, True):
            with self.subTest(passed=passed), \
                 patch("build_electricity_inputs.check_formal_inputs",
                       return_value={"passed": passed, "accepted_inputs": []}), \
                 patch("build_electricity_inputs.calculate") as computation:
                with self.assertRaises(ValueError):
                    build(ROOT)
                computation.assert_not_called()
