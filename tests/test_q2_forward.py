"""Counterexamples for continuing state and applying forward-only shocks."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
from run_q2_national import preflight
from q2_competition_factory import build
from energy_model.q2_forward import activate_forward


class ForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        source=ROOT/"outputs/q2_revenue_recalibration/20261020T001729054583Z"
        cls.config=json.loads((source/"design.json").read_text("utf-8"))
        cls.parameters=json.loads((source/"training_selection.json").read_text("utf-8"))["scenarios"]["25"]["parameters"]

    def make(self):
        return build(self.data,self.design,self.config,self.parameters,25,end_year=2024)[0]

    def test_forward_activation_preserves_all_opening_assets_and_cash(self):
        m=self.make()
        before=deepcopy((m.cohorts,m.projects,m.storage_cohorts,m.fuel_stocks,m.revenue_policy.fund.__dict__,
                         m.revenue_policy.positions,{k:g.cash for k,g in m.generators.items()},m.paths))
        activate_forward(m,self.config,dict(name="S0"))
        after=(m.cohorts,m.projects,m.storage_cohorts,m.fuel_stocks,m.revenue_policy.fund.__dict__,
               m.revenue_policy.positions,{k:g.cash for k,g in m.generators.items()},m.paths)
        self.assertEqual(before,after)
        self.assertIsNone(m.revenue_policy.new_support.offer(2025,"wind",1))
        self.assertIsNone(m.revenue_policy.new_support.offer(2025,"solar",1))
        m.run(2026)
        self.assertEqual(before[-1],m.paths[:10])
        self.assertEqual(m.revenue_policy.fund.last_year,2026)
        self.assertLess(max(abs(p["cash_balance_residual_cny"]) for p in m.paths),.1)

    def test_shock_current_information_not_future_recovery(self):
        m=self.make()
        activate_forward(m,self.config,dict(name="shock",event=dict(start_year=2026,end_year=2026,
            gas_import_multiplier=.5,gas_price_multiplier=1.3,hydro_energy_multiplier=.8)),end_year=2030)
        m.drivers()
        normal=m.suppliers["gas"].offer(2029,record=False)
        opening=m.forward_base_prices["gas"]
        m.run(2025)
        m.drivers()
        shocked=m.suppliers["gas"].offer(2029,record=False)
        self.assertEqual(shocked["domestic_mw"],normal["domestic_mw"])
        self.assertEqual(shocked["import_mw"],[v*.5 for v in normal["import_mw"]])
        self.assertEqual(m.suppliers["gas"].price,opening*1.3)
        m.year=2027
        m.drivers()
        self.assertEqual(m.forward_import_factor,1)
        self.assertEqual(m.suppliers["gas"].price,opening)

    def test_early_exit_does_not_cancel_debt_or_pending_projects(self):
        m=self.make()
        projects=deepcopy(m.projects)
        loans=deepcopy(m.generators["coal"].loans)
        old={c["id"]:c["exit_year"] for c in m.cohorts}
        activate_forward(m,self.config,dict(name="early",retirement_acceleration_years=3,infrastructure_delay_years=2))
        self.assertEqual(projects,m.projects)
        self.assertEqual(loans,m.generators["coal"].loans)
        for c in m.cohorts:
            expected=max(2025,old[c["id"]]-3) if c["tech"]=="coal" and c["status"]=="active" else old[c["id"]]
            self.assertEqual(c["exit_year"],expected)
        self.assertEqual(m.a["grid_lead_years"],self.design["assumptions"]["grid_lead_years"]+2)

    def test_frozen_new_gas_retains_old_projects(self):
        m=self.make()
        before=deepcopy(m.projects)
        activate_forward(m,self.config,dict(name="frozen",freeze_new_gas=True),end_year=2030)
        m.run(2027)
        self.assertFalse(any(p["tech"]=="gas" and p["decision_year"]>=2025 for p in m.projects))
        self.assertTrue({p["id"] for p in before}.issubset(p["id"] for p in m.projects))
        self.assertTrue(any(b["kind"]=="new_gas_investment_frozen" for b in m.behavior))

    def test_bad_horizon_and_unknown_control_rejected(self):
        m=self.make()
        with self.assertRaises(ValueError):activate_forward(m,self.config,{"name":"bad","free_capacity":1})
        with self.assertRaises(ValueError):activate_forward(m,self.config,{"name":"bad"},end_year=2070)


if __name__=="__main__":unittest.main()
