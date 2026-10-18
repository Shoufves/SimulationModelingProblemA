"""Q1 scientific counterexamples and fail-closed input/output contracts."""
import copy
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
import shutil
from contextlib import contextmanager
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))
from energy_model.q1 import (Q1Error,balance_table,concentration,identity,inside,
    price_volatility,ratio_records,read_csv,read_json,screening_lcoe,spatial_difference)
import run_q1_assessment
from run_q1_assessment import validate_inputs,normalize,calculate
from scan_google_keys import scan_workspace
from audit_workspace import inventory_scope


@contextmanager
def fixture_dir(parent):
    parent=parent.resolve()
    parent.mkdir(parents=True,exist_ok=True)
    path=parent/("q1-test-"+uuid.uuid4().hex)
    path.mkdir()  # inherit repository ACLs, including in Windows desktop sandbox
    try:
        yield path
    finally:
        if path.resolve().parent!=parent or not path.name.startswith("q1-test-"):
            raise ValueError("Refusing to clean outside test fixture")
        shutil.rmtree(path)


class Q1CalculationTests(unittest.TestCase):
    def trade_record(self,value,**changes):
        row=dict(year="2023",region="mainland",unit="tonne",source_id="same-table",
                 boundary="same fuel and ledger",value=value)
        row.update(changes)
        return row

    def test_net_dependency_same_fuel_ledger(self):
        self.assertEqual(ratio_records(*(self.trade_record(x) for x in (30,5,100))),25)

    def test_net_dependency_rejects_cross_year_unit_region_source_boundary(self):
        for field,value in (("year","2024"),("unit","EJ"),("region","other"),
                            ("source_id","different-table"),("boundary","different fuel")):
            with self.subTest(field=field),self.assertRaises(Q1Error):
                ratio_records(self.trade_record(30,**{field:value}),
                              self.trade_record(5),self.trade_record(100))

    def test_unknown_exports_are_not_zero(self):
        self.assertIsNone(ratio_records(self.trade_record(30),self.trade_record(None),
                                        self.trade_record(100)))

    def test_trade_invalid_and_empty_consumption(self):
        for x in (-2,0):
            with self.assertRaises(Q1Error):
                ratio_records(self.trade_record(30),self.trade_record(2),self.trade_record(x))

    def origins(self):
        return [dict(year="2024",destination="China",unit="EJ",source_id="TEST",
                     origin=name,value=value,row_type=kind)
                for name,value,kind in [("A",60,"origin"),("Other Asia Pacific",40,"origin"),
                                       ("Total imports",100,"total")]]

    def test_group_hhi_is_an_upper_bound_not_country_point(self):
        result=concentration(self.origins())
        self.assertAlmostEqual(result["reported_bin_hhi"],.52)
        self.assertAlmostEqual(result["country_hhi_lower_infimum"],.36)
        self.assertFalse(result["exact_country_hhi"])
        for n in (1,2,10,100):
            actual=.6**2+n*(.4/n)**2
            self.assertLessEqual(result["country_hhi_lower_infimum"],actual)
            self.assertGreaterEqual(result["country_hhi_upper"]+1e-14,actual)

    def test_rest_of_world_not_a_country(self):
        rows=self.origins();rows[1]["origin"]="Rest of World"
        self.assertFalse(concentration(rows)["exact_country_hhi"])

    def test_trade_unmatched_total_and_duplicate_origin_rejected(self):
        for mutate in (lambda r:r[0].update(value=50),lambda r:r[1].update(origin="A"),
                       lambda r:r[1].update(unit="tonne")):
            rows=self.origins();mutate(rows)
            with self.assertRaises(Q1Error):concentration(rows)

    def prices(self,years):
        return [dict(year=str(y),value=str(p),unit="USD",variable="TEST",
                     source_id="archived",region="global") for y,p in years]

    def test_price_gaps_do_not_bridge(self):
        result=price_volatility(self.prices([(2015,1),(2016,2),(2018,100),(2019,100)]))
        self.assertEqual(result["valid_pairs"],[[2015,2016],[2018,2019]])
        self.assertAlmostEqual(result["value"],math.log(2)/math.sqrt(2))
        self.assertIn(2017,result["missing_years"])
        self.assertEqual(result["observations"],2)

    def test_insufficient_prices_unknown_not_zero_volatility(self):
        self.assertIsNone(price_volatility(self.prices([(2015,1),(2016,2)]))["value"])

    def test_price_duplicate_nonpositive_and_mixed_series_rejected(self):
        cases=[self.prices([(2015,1),(2015,2)]),self.prices([(2015,0)])]
        mixed=self.prices([(2015,1),(2016,2)]);mixed[1]["unit"]="CNY";cases.append(mixed)
        for rows in cases:
            with self.assertRaises(Q1Error):price_volatility(rows)

    def region(self,value,year=2024,unit="10^8 kWh"):
        return dict(value=value,year=year,unit=unit)

    def test_same_year_spatial_own_denominators(self):
        g={"A":self.region(80),"B":self.region(20)}
        d={"A":self.region(20),"B":self.region(20)}
        result=spatial_difference(g,d,["A","B"])
        self.assertAlmostEqual(result["value"],.3)
        self.assertEqual(result["generation_sum"],100)
        self.assertEqual(result["consumption_sum"],40)

    def test_regional_missing_year_and_units_fail(self):
        g={"A":self.region(20)}
        for d,expected in [({},["A"]),({"A":self.region(None)},["A"]),
                           ({"A":self.region(10,2023)},["A"]),
                           ({"A":self.region(10,unit="TWh")},["A"])]:
            with self.assertRaises(Q1Error):spatial_difference(g,d,expected)

    def test_common_cost_zero_discount_and_monotonic_sensitivity(self):
        zero=screening_lcoe(1000,20,.5,25,0)
        self.assertAlmostEqual(zero,(1000/25+20)/(8760*.5))
        self.assertLess(screening_lcoe(1000,20,.5,25,.03),
                        screening_lcoe(1000,20,.5,25,.07))
        self.assertAlmostEqual(screening_lcoe(1000,20,.5,25,.05),
                               2*screening_lcoe(1000,20,1,25,.05))

    def test_cost_nonphysical_parameters_fail(self):
        for cf in (0,-.1,1.1,float("nan")):
            with self.assertRaises(Q1Error):screening_lcoe(1000,20,cf,25,.05)

    def test_balance_missing_and_observed_residual_preserved(self):
        r=identity({"supply":100,"production":80},{"production":1,"imports":1},"supply")
        self.assertIsNone(r["residual"]);self.assertEqual(r["missing"],["imports"])
        r=identity({"supply":100,"production":80,"imports":15},
                   {"production":1,"imports":1},"supply")
        self.assertEqual(r["residual"],5)
        self.assertEqual(r["target_value"],100)

    def test_coal_nested_power_not_added_twice(self):
        rows=[dict(source_id="NBS_2025_C09-05",year="2023",unit="10^4 t",
                   variable=k,value=v) for k,v in {
            "production_raw_coal":80,"imports":20,"exports":1,"inventory_opening_minus_closing":-2,
            "available_supply":97,"consumption":90,"final_consumption":20,
            "transformation_input":70,"power_generation_input":55,"heat_input":10,
            "balance_difference":7}.items()]
        ledger=balance_table(rows,"NBS_2025_C09-05",2023)
        self.assertEqual(ledger["use"]["residual"],0)
        self.assertEqual(ledger["supply_minus_consumption"],7)
        self.assertNotIn("power_generation_input",ledger["use"]["terms"])

    def test_2023_published_rounding_is_not_adjusted(self):
        rows=read_csv(ROOT/"data/processed/nbs_balance_checkpoints.csv")
        ledger=balance_table(rows,"NBS_2025_C09-03",2023)
        self.assertEqual(ledger["supply_minus_consumption"],15520)
        self.assertEqual(ledger["published_difference"],15519)
        self.assertEqual(ledger["difference_rounding_residual"],1)


class Q1ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=read_json(ROOT/"workflow/q1_inputs.json")

    def test_missing_input_or_changed_hash_fails_closed(self):
        for mutate in (lambda m:m["inputs"][0].update(path="tmp/does-not-exist-q1.csv"),
                       lambda m:m["inputs"][0].update(sha256="0"*64),
                       lambda m:m["inputs"].pop()):
            manifest=copy.deepcopy(self.manifest);mutate(manifest)
            with self.assertRaises(Q1Error):validate_inputs(ROOT,manifest)

    def test_restricted_and_escape_paths_rejected_before_read(self):
        for p in ("data/restricted/household/file","../outside","D:/outside"):
            with self.assertRaises(Q1Error):inside(ROOT,p)

    def test_unowned_output_directory_is_not_overwritten(self):
        parent=ROOT/"outputs/q1";parent.mkdir(parents=True,exist_ok=True)
        with fixture_dir(parent) as folder:
            path=Path(folder);marker=path/"other_member.txt";marker.write_bytes(b"preserve")
            with patch.object(sys,"argv",["run_q1_assessment","--output-dir",
                              path.relative_to(ROOT).as_posix()]):
                self.assertEqual(run_q1_assessment.main(),1)
            self.assertEqual(marker.read_bytes(),b"preserve")

    def test_output_cannot_target_other_workspace_locations(self):
        with patch.object(sys,"argv",["run_q1_assessment","--output-dir","data/processed"]):
            self.assertEqual(run_q1_assessment.main(),1)

    def test_inventory_external_history_does_not_require_B_C_checkout(self):
        row=dict(target="../B题/original.pdf",action="external_duplicate")
        self.assertEqual(inventory_scope(ROOT,row),"external_history_not_verified")
        for target,action in (("../outside.txt","retain"),("../B题/original.pdf","retain"),
                              ("../other/original.pdf","external_duplicate")):
            with self.assertRaises(ValueError):
                inventory_scope(ROOT,dict(target=target,action=action))
        self.assertEqual(inventory_scope(ROOT,dict(target="data/restricted/fixture",action="restricted")),
                         "restricted_metadata_only")
        self.assertEqual(inventory_scope(ROOT,dict(target="data/raw/fixture",action="retain")),
                         "repository_content")

    def test_actual_candidate_preserves_quarantine_and_years(self):
        inputs=validate_inputs(ROOT,self.manifest)
        history,by_input=normalize(ROOT,inputs)
        self.assertEqual(len([r for r in by_input["nbs"] if r["variable"]=="consumption_10ktce"]),10)
        self.assertTrue(all(r["status"]=="archived_reference" for r in by_input["price"]))
        self.assertEqual({r["year"] for r in by_input["price"]},set(range(2015,2021)))
        self.assertEqual({r["year"] for r in by_input["province"]},{2024})
        self.assertEqual({r["year"] for r in by_input["snapshot"]
                          if r["variable"].startswith("new_storage")},{2025})
        self.assertTrue(all(r["variable"]!="real_gdp_growth_pct" for r in history))
        self.assertTrue(all(r["source_key"] in self.manifest["sources"] for r in history))
        blank=next(r for r in by_input["province"] if r["region"]=="上海" and
                   r["variable"]=="hydro_generation_100GWh")
        self.assertIsNone(blank["value"])
        self.assertTrue(blank["missing_reason"])

    def test_actual_four_dimensions_and_intensity_unit(self):
        inputs=validate_inputs(ROOT,self.manifest)
        history,indicators,roles,handoff,gaps,static=calculate(ROOT,self.manifest,inputs)
        self.assertTrue({"保障","低碳","经济","协调"}.issubset({r["dimension"] for r in indicators}))
        ei=next(r for r in indicators if r["indicator_id"]=="energy_intensity" and r["year"]==2024)
        self.assertAlmostEqual(ei["value"],596000*10000*1000/(128209664468400/10000))
        self.assertEqual(len(roles),12)
        self.assertTrue(all(r["status"]!="admitted" for r in handoff))
        self.assertEqual(static["national_2024_physical_energy_carbon_closure"]["status"],"blocked")
        self.assertEqual(static["hydrogen"]["approximate_category_sum"],3632)

    def test_scanner_never_opens_restricted_or_virtual_environment(self):
        parent=ROOT/"tmp/tests";parent.mkdir(parents=True,exist_ok=True)
        with fixture_dir(parent) as folder:
            root=Path(folder)
            for name in ("data/restricted/private.txt",".venv/secret.txt","public.txt"):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"ordinary")
            original=Path.read_bytes
            def guarded(path):
                if "restricted" in path.parts or ".venv" in path.parts:
                    raise AssertionError("Restricted content was opened")
                return original(path)
            with patch.object(Path,"read_bytes",guarded):
                result=scan_workspace(root)
            self.assertTrue(result["passed"])
            self.assertEqual(result["files_scanned"],1)
            self.assertIn("data/restricted",result["excluded_directories"])


if __name__=="__main__":
    unittest.main()
