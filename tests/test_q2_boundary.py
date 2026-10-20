"""National scope counterexamples; all fixture additions are explicitly synthetic."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
AVAILABLE=all(importlib.util.find_spec(k) for k in ("scipy","mesa"))
if AVAILABLE:
    from energy_model.q2_boundary import InheritedOperatingBoundary
    from energy_model.q2_national import NationalModel,TECHS
    from run_q2_national import preflight


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt")
class NationalBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        cls.theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                       replacement_adoption=.2,expectation_rate=.25)

    def fixture(self):
        data=deepcopy(self.data)
        model=NationalModel(data,self.design,self.theta,2024,investment=False)
        history={y:model.capacity_split(y) for y in range(2009,2025)}
        for values in history.values():
            values["coal"]-=1000
            values["hydro"]-=2000
        data[2024,"total_capacity_mw"]=sum(history[2024].values())+3000
        data[2024,"electricity_generation_mwh"]=sum(model.initial_generation.values())+8e6
        source=model.consumers["coal"].name+"/coal"
        boundary=InheritedOperatingBoundary(initial_year=2024,
            stores={"pumped_hydro":dict(exit_year=2026,fixed_om_cny_per_year=1e6,initial_book_value_cny=1e9,
                operation=dict(power_mw=2000,energy_mwh=8000,initial_mwh=4000,
                    charge_efficiency=.9,discharge_efficiency=.9,throughput_cost=3))},
            recovery_plants={"waste_heat":dict(exit_year=2027,fixed_om_cny_per_year=2e6,
                initial_book_value_cny=1e9,initial_generation_mwh=5e6,energy_tariff_real_cny_per_gross_mwh=380,
                operation=dict(input="recovered_heat",output="electricity",efficiency=.3,
                    capacity_mw=1000,availability=[1]*4,variable_cost_per_mwh=10,minimum_fraction=0,
                    ramp_mw_per_hour=1000,window_energy_budget_mwh=24000))},
            recoveries={"industrial":dict(output="recovered_heat",source_input_fractions={source:.01})},
            initial_pumping_mwh=2.5e6,initial_pumped_generation_mwh=2e6,
            initial_statistical_adjustment_mwh=1e6,capacity_history=history,evidence="synthetic boundary fixture, not national input")
        return data,boundary

    def test_national_physical_carbon_and_cash_ledgers_close(self):
        data,boundary=self.fixture()
        model=NationalModel(data,self.design,self.theta,2024,investment=False,operating_boundary=boundary).run(2025)
        row=model.paths[0]
        self.assertLess(abs(row["cash_balance_residual_cny"]),.05)
        self.assertGreater(row["recovery_generation_mwh"],0)
        self.assertAlmostEqual(row["electricity_generation_mwh"],
            sum(row[t+"_generation_mwh"] for t in TECHS)+row["recovery_generation_mwh"]+row["pumped_generation_mwh"],delta=.01)
        self.assertAlmostEqual(row["total_capacity_mw"],sum(row[t+"_capacity_mw"] for t in TECHS)+3000,delta=.001)
        self.assertAlmostEqual(row["combustion_co2_t"],sum(r["combustion_co2_t"] for r in model.operations if r["kind"]=="fuel")*365,delta=.01)
        self.assertAlmostEqual(row["pumped_charge_mwh"]-row["pumped_generation_mwh"],row["pumped_loss_mwh"],delta=.01)
        inputs=sum(r["input_mwh"] for r in model.operations if r["kind"]=="demand" and r["carrier"]=="electricity")*365
        storage=sum((r["charge_mwh"]-r["discharge_mwh"])*365 for r in model.operations if r["kind"] in {"storage","additional_storage"})
        self.assertAlmostEqual(row["generation_bus_output_mwh"],inputs/model.a["grid_efficiency"]+storage,delta=.01)

    def test_initial_load_deducts_pumping_and_statistical_adjustment_once(self):
        data,boundary=self.fixture()
        model=NationalModel(data,self.design,self.theta,2024,investment=False,operating_boundary=boundary)
        self.assertAlmostEqual(model.base_electric,(data[2024,"electricity_generation_mwh"]-3.5e6)*model.a["grid_efficiency"]-model.base_export,delta=.001)

    def test_capacity_and_generation_double_count_are_rejected(self):
        data,boundary=self.fixture()
        data[2024,"electricity_generation_mwh"]+=1e6
        with self.assertRaisesRegex(ValueError,"generation components"):
            NationalModel(data,self.design,self.theta,2024,operating_boundary=boundary)
        data,boundary=self.fixture()
        boundary.capacity_history[2024]["hydro"]+=2000
        with self.assertRaisesRegex(ValueError,"capacity overlaps"):
            NationalModel(data,self.design,self.theta,2024,operating_boundary=boundary)

    def test_retirement_and_planning_never_refill_or_resurrect_assets(self):
        data,boundary=self.fixture()
        model=NationalModel(data,self.design,self.theta,2024,investment=False,operating_boundary=boundary).run(2025)
        forecast=model.planning_operation(3)
        self.assertEqual(forecast["additional_storage"]["pumped_hydro"]["initial_mwh"],0)
        self.assertEqual(forecast["plants"]["waste_heat"]["capacity_mw"],0)
        self.assertAlmostEqual(model.operating_boundary.stock["pumped_hydro"],4000)
        model.run(2027)
        self.assertAlmostEqual(model.paths[1]["supplementary_storage_retirement_loss_mwh"],4000)
        self.assertEqual(model.paths[1]["pumped_generation_mwh"],0)
        self.assertEqual(model.paths[2]["recovery_generation_mwh"],0)
        self.assertEqual(model.paths[2]["supplementary_capacity_mw"],0)
        self.assertEqual(model.paths[2]["pumped_capacity_mw"],0)
        self.assertEqual(model.paths[2]["hydro_including_pumped_capacity_mw"],model.paths[2]["hydro_capacity_mw"])

    def test_initial_state_clock_and_postinitial_capacity_are_rejected(self):
        data,boundary=self.fixture()
        with self.assertRaisesRegex(ValueError,"Post-initial"):
            boundary.capacities(2025,TECHS)
        boundary.initial_year=2023
        with self.assertRaisesRegex(ValueError,"initial years differ"):
            NationalModel(data,self.design,self.theta,2024,operating_boundary=boundary)


if __name__=="__main__":unittest.main()
