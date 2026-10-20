"""Real-input regressions: scope closure, policy timing and finite cash."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
AVAILABLE=all(importlib.util.find_spec(x) for x in ("mesa","scipy","pdfplumber"))
if AVAILABLE:
    from run_q2_empirical_support import (preflight,scope_inputs,tariff_inputs,
        NationalModel,add_existing_support,csv_rows,fiscal_observations)


@unittest.skipUnless(AVAILABLE,"Install research dependencies")
class EmpiricalSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        cls.theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                       replacement_adoption=.2,expectation_rate=.25)

    def fixture(self,share=.5):
        d,s,p,b,a,_=scope_inputs(self.data,self.design,self.theta,recovery_share=share)
        policy,cells,tax=tariff_inputs(d,s,mode="finite")
        model=NationalModel(d,s,p,2014,detail=True,revenue_policy=policy,operating_boundary=b)
        add_existing_support(model,cells,tax,available_fraction=.5)
        return model,a

    def test_initial_gas_oil_and_total_capacity_are_actual_source_anchors(self):
        before=deepcopy(self.data)
        model,a=self.fixture()
        self.assertEqual(model.initial_capacities["gas"],56970)
        self.assertEqual(model.initial_capacities["oil"],5116)
        self.assertAlmostEqual(a["unidentified_inactive_capacity_mw"],717)
        self.assertAlmostEqual(model.initial_generation["oil"]/1e6,9.517)
        self.assertEqual(self.data,before)
        self.assertEqual(model.a["nonfossil_priority_start_year"],2015)
        self.assertEqual(model.design["demand_identification"]["fitted"]["training_years"],list(range(2015,2022)))
        target=next(t for t in model.design["targets"] if t["observation"]=="hydro_capacity_mw")
        self.assertEqual(target["metric"],"hydro_including_pumped_capacity_mw")
        self.assertEqual(model.data[2021,"hydro_capacity_mw"],self.data[2021,"hydro_capacity_mw"])

    def test_capacity_additions_cannot_be_selected_as_stock(self):
        rows=csv_rows("data/raw/q2_capacity_detail/annual_technology_anchors.csv")
        initial=next(r for r in rows if r["year"]=="2014" and r["tr_ordinal_1based"]=="62")
        addition=next(r for r in rows if r["year"]=="2014" and r["tr_ordinal_1based"]=="113")
        self.assertEqual(initial["metric"],"capacity")
        self.assertEqual(addition["metric"],"capacity_additions")

    def test_real_fiscal_cells_and_missing_future_tariff(self):
        rows=fiscal_observations()
        self.assertEqual(float(rows[2015,"revenue"]["actual"]),514.87)
        model,_=self.fixture()
        with self.assertRaisesRegex(ValueError,"Missing energy-only"):
            model.revenue_policy.energy_tariff(2019,"gas")
        for p in model.revenue_policy.positions:
            terms=p["terms"]
            self.assertEqual(terms.commissioned_year+terms.eligible_years,2019)
            self.assertGreaterEqual(terms.commissioned_year,2006)

    def test_actual_run_has_2015_biomass_finite_payments_and_balanced_cash(self):
        model,_=self.fixture()
        model.run(2015)
        row=model.paths[0]
        self.assertGreater(row["biomass_generation_mwh"],1e6)
        self.assertAlmostEqual(row["hydro_including_pumped_capacity_mw"],row["hydro_capacity_mw"]+22110)
        self.assertGreater(row["subsidy_paid_nominal_cny"],0)
        self.assertLessEqual(row["subsidy_paid_nominal_cny"],289.8e8+.01)
        self.assertLess(abs(row["cash_balance_residual_cny"]),.05)
        self.assertAlmostEqual(row["pumped_charge_mwh"]-row["pumped_generation_mwh"],row["pumped_loss_mwh"],delta=.01)
        self.assertTrue(all(p["terms"].project.startswith("initial/") for p in model.revenue_policy.positions))


if __name__=="__main__":unittest.main()
