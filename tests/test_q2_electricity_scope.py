"""Keep pure oil, unallocated Other and gross output distinct in new evidence."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from build_q2_electricity_scope import extract


class ElectricityScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows,cls.review=extract()
        cls.data={(r["year"],r["category"]):r["value_twh"] for r in cls.rows}

    def test_full_same_vintage_mix_closes_in_every_year(self):
        self.assertEqual(len(self.rows),200)
        self.assertEqual({r["year"] for r in self.rows},set(range(2005,2025)))
        for row in self.review["same_vintage_closure"]:
            self.assertLess(abs(row["residual_twh"]),1e-7)

    def test_reviewed_oil_and_other_cells_are_not_combined(self):
        self.assertAlmostEqual(self.data[2014,"oil"],9.517)
        self.assertAlmostEqual(self.data[2024,"oil"],9.44963419658422)
        self.assertAlmostEqual(self.data[2024,"other_unallocated"],79.42757747123835)
        row=next(r for r in self.rows if r["year"]==2024 and r["category"]=="oil")
        self.assertEqual(row["cell"],"AO44")
        self.assertEqual(row["output_basis"],"gross")

    def test_composite_renewable_and_other_stay_explicit_not_zero_emission_claims(self):
        keys={r["category"] for r in self.rows}
        self.assertIn("geothermal_biomass_other_renewables",keys)
        self.assertNotIn("biomass",keys)
        self.assertIn("other_is_all_pumped_storage",self.review["excluded_use"])
        self.assertIn("fuel_input_measurement",self.review["excluded_use"])


if __name__=="__main__":
    unittest.main()
