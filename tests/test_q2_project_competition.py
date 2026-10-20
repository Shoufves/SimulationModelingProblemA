"""Private project returns, displaced incumbents, and finite physical sales."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"),str(ROOT/"scripts"),str(ROOT/"tests")]
from energy_model.q2_project_competition import ProjectCompetitionModel
from energy_model.q2_thermal_vintages import ThermalNationalModel,ThermalVintages
from energy_model.q2_renewable_vintages import RenewableVintages
from energy_model.q2_exposure import AnnualExposure
from energy_model.q2_national import EF
from run_q2_national import preflight
from test_q2 import small_operation


class ProjectCompetitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_ = preflight()
        cls.theta = dict(activity_elasticity=.5,investment_response=1,
            renewable_mix_response=.7,replacement_adoption=.2,expectation_rate=.25)

    def model(self,competition=True,**options):
        return ProjectCompetitionModel(deepcopy(self.data),deepcopy(self.design),self.theta,2014,
            thermal_vintages=ThermalVintages(new_gross_efficiencies={"coal":.5,"gas":.6},
                decision_start_year=2015,evidence="synthetic test"),project_competition=competition,**options)

    def gas_operation(self):
        op = small_operation()
        op["storage"].update(initial_mwh=0,energy_mwh=0,power_mw=0)
        op["fuels"]["gas"].update(domestic_mw=[100,100],domestic_cost_per_mwh=1,import_cost_per_mwh=1)
        op["plants"]["gas"].update(capacity_mw=10,efficiency=.5,policy_cost_per_mwh=0)
        return op

    def test_disabled_exactly_preserves_aggregate_owner_model(self):
        new = self.model(False).run(2016)
        old = ThermalNationalModel(deepcopy(self.data),deepcopy(self.design),self.theta,2014,
            thermal_vintages=ThermalVintages(new_gross_efficiencies={"coal":.5,"gas":.6},
                decision_start_year=2015,evidence="synthetic test")).run(2016)
        for field in ("paths","finance","projects","operations","behavior","balances"):
            self.assertEqual(getattr(new,field),getattr(old,field),field)
        self.assertEqual(new.project_forecasts,[])

    def test_project_can_profit_by_sharing_existing_sales_without_creating_sales(self):
        m = self.model()
        m.suppliers["gas"].price = 1
        op = self.gas_operation()
        with patch.object(m,"planning_operation",side_effect=lambda _:deepcopy(op)), \
             patch.object(m,"tariff",return_value=100),patch.object(m,"variable_om",return_value=0), \
             patch.object(m,"fixed_om_per_mw",return_value=0):
            margin,hours = m.project_economics("gas",10)
        self.assertAlmostEqual(hours,5*365/10)
        self.assertAlmostEqual(margin,hours*(100-1/.6))
        forecast = m.project_forecasts[-1]
        self.assertAlmostEqual(forecast["candidate_generation_mwh"],5*365)
        self.assertAlmostEqual(forecast["incumbent_generation_mwh"],5*365)
        self.assertAlmostEqual(forecast["total_same_technology_generation_mwh"],10*365)
        self.assertAlmostEqual(forecast["candidate_fuel_mwh"],5*365/.6)

    def test_renewable_share_uses_available_output_not_equal_capacity(self):
        m = self.model(renewable_vintages=RenewableVintages(new_project_cf={"wind":.3,"solar":.2},evidence="fixture"))
        m.a["wind_shape"] = [1,1,1,1]
        op = self.gas_operation()
        op["demands"]["load"]["service_mwh"] = [1,1]
        op["plants"]["wind"] = dict(op["plants"]["gas"],input=None,efficiency=1,
            capacity_mw=10,availability=[.1,.1],window_energy_budget_mwh=240)
        with patch.object(m,"planning_operation",side_effect=lambda _:deepcopy(op)), \
             patch.object(m,"tariff",return_value=100),patch.object(m,"variable_om",return_value=0), \
             patch.object(m,"fixed_om_per_mw",return_value=0):
            margin,hours = m.marginal_renewable_economics("wind",10)
        r = m.project_forecasts[-1]
        self.assertAlmostEqual(r["total_same_technology_generation_mwh"],2*365)
        self.assertAlmostEqual(r["candidate_generation_mwh"],1.5*365)
        self.assertAlmostEqual(r["incumbent_generation_mwh"],.5*365)
        self.assertAlmostEqual(margin,hours*100)

    def test_partial_exposure_and_ets_normalise_to_project_operating_year(self):
        m = self.model(annual_exposure=AnnualExposure(.25,"fixture"))
        m.year,m.carbon = 2022,100
        m.suppliers["gas"].price = 1
        op = self.gas_operation()
        with patch.object(m,"planning_operation",side_effect=lambda _:deepcopy(op)), \
             patch.object(m,"tariff",return_value=100),patch.object(m,"variable_om",return_value=0), \
             patch.object(m,"fixed_om_per_mw",return_value=5):
            margin,hours = m.project_economics("gas",10)
        self.assertAlmostEqual(hours,10*365/12.5)
        expected = hours*(100-1/.6-100*(EF["gas"]/.6-m.a["ets_2021_2025_proxy"]["gas"]))-5
        self.assertAlmostEqual(margin,expected)
        self.assertAlmostEqual(m.project_forecasts[-1]["candidate_generation_mwh"],2.5*hours)

    def test_support_uses_own_sales_and_zero_support_is_respected(self):
        m = self.model()
        op = self.gas_operation()
        hours_seen = []
        def support(model,tech,*,full_load_hours):
            hours_seen.append(full_load_hours)
            return 100*full_load_hours
        m.revenue_policy = SimpleNamespace(investment_value=support)
        with patch.object(m,"planning_operation",side_effect=lambda _:deepcopy(op)), \
             patch.object(m,"tariff",return_value=100):
            no_support = m.thermal_candidate_npv("gas",10,support_fraction=0)
            supported = m.thermal_candidate_npv("gas",10,support_fraction=1)
        self.assertEqual(hours_seen,[182.5,182.5])
        self.assertAlmostEqual(supported-no_support,18250)

    def test_actual_project_accounts_close_to_sector_without_cash_creation(self):
        m = self.model(renewable_vintages=RenewableVintages(new_project_cf={"wind":.3,"solar":.2},evidence="fixture"),
                       annual_exposure=AnnualExposure(.5,"fixture"))
        m.run(2022)
        self.assertTrue(m.project_forecasts)
        self.assertTrue(m.project_operation_accounts)
        for row in m.paths:
            self.assertLess(abs(row["cash_balance_residual_cny"]),.01)
            for tech in ("coal","gas","wind","solar"):
                accounts = [a for a in m.project_operation_accounts if a["year"]==row["year"] and a["tech"]==tech]
                self.assertAlmostEqual(sum(a["generation_mwh"] for a in accounts),row[tech+"_generation_mwh"],delta=.001)
                ledger = next(a for a in m.finance if a["year"]==row["year"] and a["kind"]=="generator_operation" and a["actor"]==tech)
                self.assertAlmostEqual(sum(a["ets_transfer_cny"] for a in accounts),ledger["ets_transfer_cny"],delta=.001)
        self.assertTrue(any(a["ets_transfer_cny"] != 0 for a in m.project_operation_accounts if a["year"]>=2021))

    def test_zero_first_year_uses_first_positive_exposure_without_division_by_zero(self):
        m = self.model(annual_exposure=AnnualExposure(0,"fixture"))
        op = self.gas_operation()
        with patch.object(m,"planning_operation",side_effect=lambda _:deepcopy(op)) as planning:
            m.project_economics("gas",10)
        planning.assert_called_once_with(4)
        self.assertEqual(m.project_forecasts[-1]["candidate_operating_mw_year"],10)

    def test_rejects_competition_when_thermal_project_screening_would_be_bypassed(self):
        for vintage in (None,ThermalVintages(new_gross_efficiencies={"gas":.6},decision_start_year=2015,evidence="fixture"),
                        ThermalVintages(new_gross_efficiencies={"coal":.5,"gas":.6},decision_start_year=2025,evidence="fixture")):
            with self.assertRaisesRegex(ValueError,"both thermal project screens"):
                ProjectCompetitionModel(deepcopy(self.data),deepcopy(self.design),self.theta,2014,
                    thermal_vintages=vintage,project_competition=True)


if __name__ == "__main__":
    unittest.main()
