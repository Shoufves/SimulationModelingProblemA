"""Q1 scientific counterexamples and fail-closed input/output contracts."""
import copy
import importlib.util
import math
import statistics
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
import validate_q1
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

    def test_mixed_annual_level_is_retained_but_neither_adjacent_return_is_used(self):
        rows=self.prices([(2015,1),(2016,10),(2017,20),(2018,20)])
        for row in rows:
            row.update(definition_id="TTF",definition_status="homogeneous")
        rows[0].update(definition_id="mixed_border_TTF",definition_status="mixed_definition")
        result=price_volatility(rows)
        self.assertEqual(result["valid_pairs"],[[2016,2017],[2017,2018]])
        self.assertEqual(result["excluded_level_years"],[2015])
        self.assertNotIn(2015,result["missing_years"])
        self.assertEqual(result["excluded_pairs"],[
            dict(years=[2015,2016],reason="mixed_definition_level")])
        self.assertAlmostEqual(result["value"],math.log(2)/math.sqrt(2))
        rows[0]["value"]="100000"
        self.assertEqual(price_volatility(rows)["value"],result["value"])

    def test_definition_switch_segments_are_not_pooled(self):
        rows=self.prices([(2015,1),(2016,2),(2017,2),(2018,100),(2019,100),(2020,200)])
        for row in rows:
            row.update(definition_id="A" if int(row["year"])<2018 else "B",
                       definition_status="homogeneous")
        result=price_volatility(rows)
        self.assertIsNone(result["value"])
        self.assertEqual(result["observations"],4)
        self.assertEqual(len(result["definition_segments"]),2)
        self.assertEqual(result["excluded_pairs"],[
            dict(years=[2017,2018],reason="definition_change")])
        for segment in result["definition_segments"]:
            self.assertEqual(segment["observations"],2)
            self.assertAlmostEqual(segment["value"],math.log(2)/math.sqrt(2))

    def test_partial_or_invalid_definition_metadata_fails_closed(self):
        for mutation in (lambda r:r[0].update(definition_id="TTF"),
                         lambda r:[x.update(definition_id="TTF",definition_status="unknown") for x in r]):
            rows=self.prices([(2015,1),(2016,2)])
            mutation(rows)
            with self.assertRaisesRegex(Q1Error,"definition metadata"):
                price_volatility(rows)

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

    def test_cost_near_zero_agrees_with_discounted_cash_flow(self):
        for rate in (0,1e-20,1e-12,.03,.05,.07):
            # Independent finite cash-flow sum, avoiding the CRF subtraction.
            annuity=sum((1+rate)**(-year) for year in range(1,26))
            discounted=(1000+20*annuity)/(8760*.5*annuity)
            with self.subTest(rate=rate):
                self.assertAlmostEqual(screening_lcoe(1000,20,.5,25,rate),discounted,places=13)

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

    def test_refreshed_manifest_hash_cannot_reuse_stale_semantic_review(self):
        with fixture_dir(ROOT/"tmp/tests") as folder:
            item=self.manifest["inputs"][0]
            changed=folder/"changed.csv"
            original=(ROOT/item["path"]).read_bytes()
            changed.write_bytes(original.replace(b"596000",b"597000"))
            self.assertNotEqual(original,changed.read_bytes())
            manifest=copy.deepcopy(self.manifest)
            manifest["inputs"][0].update(path=changed.relative_to(ROOT).as_posix(),
                                        sha256=run_q1_assessment.sha(changed))
            with self.assertRaisesRegex(Q1Error,"substantive review"):
                validate_inputs(ROOT,manifest)

    def test_changed_allowed_use_cannot_inherit_older_review(self):
        manifest=copy.deepcopy(self.manifest)
        manifest["inputs"][0]["allowed_use"]="national model initialization"
        with self.assertRaisesRegex(Q1Error,"substantive review"):
            validate_inputs(ROOT,manifest)

    def test_invalid_sensitivity_and_unsupported_method_labels_rejected(self):
        for rates in ([],[.03,.03],[-.01],[float("nan")],[float("inf")],[".05"],[True]):
            manifest=copy.deepcopy(self.manifest)
            manifest["assumptions"]["real_wacc"]=rates
            with self.subTest(rates=rates),self.assertRaises(Q1Error):
                validate_inputs(ROOT,manifest)
        manifest=copy.deepcopy(self.manifest)
        manifest["observation_window"]=[2016,2024]
        with self.assertRaisesRegex(Q1Error,"observation window"):
            validate_inputs(ROOT,manifest)
        manifest=copy.deepcopy(self.manifest)
        manifest["assumptions"]["cost_service"]="firmed electricity"
        with self.assertRaisesRegex(Q1Error,"unfirmed"):
            validate_inputs(ROOT,manifest)

    def test_report_follows_actual_cost_rates_order_and_summary(self):
        for rates in ([.07,.03,.05],[.031,.034]):
            manifest=copy.deepcopy(self.manifest)
            manifest["assumptions"]["real_wacc"]=rates
            h,i,r,_,g,s=calculate(ROOT,manifest,validate_inputs(ROOT,manifest))
            text=run_q1_assessment.report(i,r,g,s,h)
            labels="|".join(f"{x*100:g}%" for x in rates)
            self.assertIn("|技术|"+labels+"|单位|",text)
            expected="|onshore_wind|"+"|".join(
                f"{screening_lcoe(856,29,.33,25,rate):.5f}" for rate in rates)+"|2024 USD/kWh|"
            self.assertIn(expected,text)
            representative=.05 if .05 in rates else rates[0]
            self.assertIn(f"统一25年、{representative*100:g}%实际WACC的陆风",text)
            ids=[x["indicator_id"] for x in i if x["indicator_id"].startswith("screening_")]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertEqual(len(ids),2*len(rates))

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

    def test_gdp_is_driver_and_handoff_retains_observation_boundaries(self):
        inputs=validate_inputs(ROOT,self.manifest)
        history,indicators,roles,handoff,gaps,static=calculate(ROOT,self.manifest,inputs)
        records={r["record_id"]:r for r in history}
        drivers=[r for r in handoff if r["variable"]=="NY.GDP.MKTP.KN"]
        self.assertEqual(len(drivers),10)
        self.assertTrue(all(r["kind"]=="外生驱动候选" for r in drivers))
        self.assertTrue(all(r["kind"]!="校准目标候选" for r in drivers))
        for row in handoff:
            if row["status"]=="blocked":
                continue
            source=records[row["evidence"]]
            for field in ("region","source_key","boundary"):
                self.assertEqual(row[field],source[field])
            self.assertEqual(row["source_status"],source["status"])

    def test_regional_share_provenance_contains_both_full_denominators(self):
        inputs=validate_inputs(ROOT,self.manifest)
        history,indicators,roles,handoff,gaps,static=calculate(ROOT,self.manifest,inputs)
        denominator_refs={r["record_id"] for r in history if r["year"]==2024 and
            (r["input_id"]=="demand" or
             r["input_id"]=="province" and r["variable"]=="generation_100GWh")}
        self.assertEqual(len(denominator_refs),62)
        for row in indicators:
            if row["indicator_id"]=="province_share_difference":
                self.assertEqual(set(row["input_refs"].split(";")),denominator_refs)

    def test_2024_storage_units_precision_and_unknown_initial_soc(self):
        inputs=validate_inputs(ROOT,self.manifest)
        history,indicators,roles,handoff,gaps,static=calculate(ROOT,self.manifest,inputs)
        storage=static["storage_2024"]
        self.assertAlmostEqual(storage["power_gw"],73.76)
        self.assertAlmostEqual(storage["energy_gwh_figure"],168.2)
        self.assertAlmostEqual(storage["energy_gwh_paragraph"],168)
        self.assertIsNone(storage["initial_soc"])
        self.assertNotEqual(storage["power_gw"],136)  # 2025 update is not 2024 stock.
        selected=[r for r in handoff if r["evidence"].startswith("storage_2024:")]
        self.assertEqual(len(selected),2)  # Figure/text energy is not counted twice.
        self.assertTrue(all(r["year"]==2024 and r["status"]=="candidate_not_admitted"
                            for r in selected))
        self.assertEqual(next(r["status"] for r in gaps if r["gap_id"]=="storage_2024"),
                         "blocked_state")

    def test_ndc_preliminary_share_has_distinct_evidence_and_candidate_handoff(self):
        history,indicators,roles,handoff,gaps,static=calculate(
            ROOT,self.manifest,validate_inputs(ROOT,self.manifest))
        published=[r for r in history if r["variable"]=="nonfossil_primary_consumption_share"]
        self.assertEqual(len(published),1)
        observation=published[0]
        self.assertEqual((observation["year"],observation["value"],observation["unit"]),(2024,19.8,"%"))
        self.assertEqual(observation["source_key"],"lb/base:NDC_2035")
        self.assertEqual(observation["status"],"published_preliminary_estimate")
        nbs=next(r for r in history if r["year"]==2024 and
                 r["variable"]=="consumption_primary_electricity_other_pct")
        self.assertNotEqual(observation["record_id"],nbs["record_id"])
        indicator=next(r for r in indicators if r["indicator_id"]==observation["variable"])
        self.assertEqual(indicator["input_refs"],observation["record_id"])
        candidates=[r for r in handoff if r["variable"]==observation["variable"]]
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]["source_status"],"published_preliminary_estimate")
        self.assertEqual(candidates[0]["status"],"candidate_not_admitted")
        self.assertEqual(next(r for r in gaps if r["gap_id"]=="nonfossil_consumption")["years"],"2015-2023")

    def test_actual_europe_volatility_uses_only_full_TTF_years_and_reports_pairs(self):
        history,indicators,roles,handoff,gaps,static=calculate(
            ROOT,self.manifest,validate_inputs(ROOT,self.manifest))
        levels={r["year"]:r["value"] for r in history if
                r["input_id"]=="price" and r["variable"]=="Natural gas, Europe"}
        expected=statistics.stdev([math.log(levels[y]/levels[y-1]) for y in range(2017,2021)])
        result=static["prices"]["Natural gas, Europe"]
        self.assertAlmostEqual(result["value"],expected)
        self.assertEqual(result["observations"],4)
        self.assertEqual(result["comparable_level_years"],list(range(2016,2021)))
        self.assertEqual(result["missing_years"],list(range(2021,2025)))
        indicator=next(r for r in indicators if r["indicator_id"]=="price_log_sd_Natural gas, Europe")
        self.assertEqual(indicator["valid_years"],"2016-2017;2017-2018;2018-2019;2019-2020")
        self.assertTrue(all(s["observations"]==5 for k,s in static["prices"].items()
                            if k!="Natural gas, Europe"))
        text=run_q1_assessment.report(indicators,roles,gaps,static,history)
        self.assertIn("Description!B12",text)
        self.assertIn("四个相邻变化",text)

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


class Q1ValidationTests(unittest.TestCase):
    def make_run(self,folder):
        for name in validate_q1.ARTIFACTS:
            (folder/name).write_bytes(("fixture "+name).encode())
        expected=dict(candidate="p1/mmj",success=True,code_hashes={"code.py":"current"},
                      input_manifest={"path":"inputs.json","sha256":"current"})
        manifest=dict(expected,outputs={name:run_q1_assessment.sha(folder/name)
                                       for name in sorted(validate_q1.ARTIFACTS)})
        run_q1_assessment.write_json(folder/"run_manifest.json",manifest)
        return expected,manifest

    def test_reproduction_checks_actual_artifacts_not_just_matching_manifests(self):
        with fixture_dir(ROOT/"tmp/tests") as folder:
            expected,_=self.make_run(folder)
            self.assertTrue(validate_q1.inspect_run(folder,".",True,expected)["passed"])
            (folder/"history.csv").write_bytes(b"changed without refreshing either manifest")
            result=validate_q1.inspect_run(folder,".",True,expected)
            self.assertFalse(result["passed"])
            self.assertIn("Artifact fingerprint mismatch: history.csv",result["errors"])

    def test_old_valid_outputs_do_not_pass_after_failed_current_command(self):
        with fixture_dir(ROOT/"tmp/tests") as folder:
            expected,_=self.make_run(folder)
            self.assertFalse(validate_q1.inspect_run(folder,".",False,expected)["passed"])

    def test_stale_code_or_inputs_cannot_claim_current_reproduction(self):
        with fixture_dir(ROOT/"tmp/tests") as folder:
            expected,manifest=self.make_run(folder)
            for key in ("code_hashes","input_manifest"):
                changed=copy.deepcopy(manifest);changed[key]={}
                run_q1_assessment.write_json(folder/"run_manifest.json",changed)
                result=validate_q1.inspect_run(folder,".",True,expected)
                self.assertFalse(result["passed"])
                self.assertIn("Run identity mismatch: "+key,result["errors"])

    def test_missing_malformed_or_unsafe_artifact_manifests_fail_closed(self):
        with fixture_dir(ROOT/"tmp/tests") as folder:
            expected,manifest=self.make_run(folder)
            for output_map in ({},dict(manifest["outputs"],**{"../outside":"unused"})):
                changed=dict(manifest,outputs=output_map)
                run_q1_assessment.write_json(folder/"run_manifest.json",changed)
                self.assertFalse(validate_q1.inspect_run(folder,".",True,expected)["passed"])
            (folder/"run_manifest.json").write_bytes(b"{invalid")
            self.assertFalse(validate_q1.inspect_run(folder,".",True,expected)["passed"])
            (folder/"run_manifest.json").write_bytes(b"[]")
            self.assertFalse(validate_q1.inspect_run(folder,".",True,expected)["passed"])
            run_q1_assessment.write_json(folder/"run_manifest.json",manifest)
            (folder/"history.csv").unlink()
            self.assertFalse(validate_q1.inspect_run(folder,".",True,expected)["passed"])
            (folder/"run_manifest.json").unlink()
            self.assertFalse(validate_q1.inspect_run(folder,".",True,expected)["passed"])

    def test_interrupted_validation_restores_existing_and_absent_reports(self):
        for failure in ("child_launch","malformed_json"):
            with self.subTest(failure=failure),fixture_dir(ROOT/"tmp/tests") as folder:
                before={}
                for index,name in enumerate(validate_q1.LATEST_PATHS):
                    path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
                    before[name]=b"historical bytes\r\n" if index%2==0 else None
                    if before[name] is not None:
                        path.write_bytes(before[name])
                def broken_execute(arguments):
                    for name in validate_q1.LATEST_PATHS:
                        (folder/name).write_bytes(b"{invalid")
                    if failure=="child_launch":
                        raise OSError("simulated child launch failure")
                    return run_q1_assessment.read_json(folder/validate_q1.LATEST_PATHS[0])
                with patch.object(validate_q1,"ROOT",folder),self.assertRaises((OSError,ValueError)):
                    validate_q1.run_checks(broken_execute)
                for name,data in before.items():
                    path=folder/name
                    self.assertEqual(path.read_bytes() if path.exists() else None,data)

    def test_evidence_path_cannot_overwrite_preserved_report(self):
        with patch.object(sys,"argv",["validate_q1","--evidence","outputs/validation/tests.json"]),\
                patch.object(validate_q1,"run_checks") as checks,self.assertRaises(SystemExit) as caught:
            validate_q1.main()
        self.assertEqual(caught.exception.code,2)
        checks.assert_not_called()


if __name__=="__main__":
    unittest.main()
