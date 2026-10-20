"""Run real-input, finite-cash historical support/physical-scope experiments.

The four-year window is deliberate: reviewed national technology tariffs end
in 2018. This is an explicitly conditional experiment, NOT a replacement for
the team's admitted dataset, a policy census or a recalibrated forecast.
"""
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
from math import fsum, sqrt
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from run_q2_national import preflight, CODE, INPUTS
from build_q2_electricity_scope import extract
from energy_model.q2_national import NationalModel, TECHS, TCE_MWH
from energy_model.q2_boundary import InheritedOperatingBoundary
from energy_model.q2_revenue import AnnualRevenuePolicy
from energy_model.q2_subsidies import SupportTerms
from energy_model.q2_identification import fit_nonpower, identified_parameters
from energy_model.q2_statistics import fit_bridge

YEARS = tuple(range(2015, 2019))
EVIDENCE = "docs/sources/q2_empirical_support_experiment.md"


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def csv_rows(path):
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def fiscal_observations(years=YEARS):
    """Check all used monetary values against original MOF table cells."""
    import importlib.util
    spec=importlib.util.spec_from_file_location("mof_fiscal",ROOT/"data/raw/q2_fiscal/build_fiscal.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest=json.loads((ROOT/"data/raw/q2_fiscal/source_manifest.json").read_text("utf-8"))
    hashes={r["source_file"]:r["sha256"] for r in manifest}
    result={}
    for r in csv_rows("data/raw/q2_fiscal/annual_renewable_levy.csv"):
        y=int(r["year"])
        if y not in years or r["scope"]!="national":continue
        key=y,r["measure"]
        if key in result or r["status"]!="exact_row_found" or r["unit"]!="亿元":
            raise ValueError("Duplicate/unreviewed fiscal input")
        path="data/raw/q2_fiscal/"+r["source_file"]
        if sha(path)!=hashes.get(r["source_file"]):
            raise ValueError("Changed fiscal original")
        page=module.read_page(ROOT/path)
        headers=[h for h in page.rows if "预算数" in h and "决算数" in h]
        original=page.rows[int(r["row_ordinal_1based"])-1]
        if (len(headers)!=1 or original[0]!=r["row_label"] or
            "可再生能源电价附加收入" not in original[0] or
            original[headers[0].index("决算数")]!=r["actual"] or
            original[headers[0].index("预算数")]!=r["budget"] or
            r["source_file"]!=f"mof_{y}_national_{r['measure']}.html"):
            raise ValueError("Fiscal transcription/source locator mismatch")
        result[key]=r
    if set(result)!={(y,m) for y in years for m in ("revenue","expenditure")}:
        raise ValueError("Missing observed fiscal year")
    return result


def cec_tables():
    """Parse original bytes; do not trust cached/transformed capacity labels."""
    import importlib.util
    path = ROOT / "data/raw/q2_capacity_detail/research.py"
    spec = importlib.util.spec_from_file_location("cec_detail", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = {y: f"data/raw/q2_capacity_detail/cec_{y}_portal.html" for y in range(2009, 2014)}
    paths[2014] = "data/raw/q2_technology_scope/cec2014_portal.html"
    manifest=json.loads((ROOT/"data/raw/q2_capacity_detail/source_manifest.json").read_text("utf-8"))
    hashes={(ROOT/"data/raw/q2_capacity_detail"/r["file"]).resolve():r["sha256"] for r in manifest}
    for path in paths.values():
        if sha(path)!=hashes.get((ROOT/path).resolve()):
            raise ValueError("Changed reviewed capacity original: "+path)
    return {y: module.parse(ROOT / p).rows for y, p in paths.items()}, paths


def reviewed_capacity_history():
    """Exact cited cells plus explicit pre-2014 scope reconstructions.

    Older >=6 MW thermal series are scaled to their 2014 all-scope snapshot.
    No post-2014 capacity informs this history. Biomass combines waste and
    agroforestry; 2011 already combines these. Coal-gangue subrows are added
    only in 2010/2011 where they are parallel, not 'of which' subsets.
    """
    tables, paths = cec_tables()
    lineage = []

    def cell(y, row, label, *, previous=False):
        values = tables[y][row - 1]
        if label not in "".join(values).replace(" ", "") or "MW" not in values:
            raise ValueError(f"CEC stock cell moved: {y}/{row}/{label}")
        value = float(values[values.index("MW") + (1 if previous else 2)].replace(",", ""))
        lineage.append(dict(year=y - int(previous), source_year=y, source_path=paths[y],
                            tr_ordinal_1based=row, label=label, value_mw=value,
                            column="previous_year" if previous else "current_year"))
        return value

    history = {}
    # For 2009 pumping, the 2010 figure is only an upper bound; reconstruct
    # proportional to total hydro. This does not enter the 2014 pump snapshot.
    pump2010 = cell(2011, 4, "抽水蓄能", previous=True)
    for y in range(2009, 2015):
        if y <= 2010:
            hydro, nuclear, wind, solar = [cell(y, r, label) for r, label in
                ((3, "水电"), (5, "核电"), (6, "风电"), (8, "太阳能"))]
            pump = pump2010 if y == 2010 else pump2010 * hydro / cell(2010, 3, "水电")
            coal = cell(y, 10, "燃煤") + (cell(y, 13, "煤矸石") if y == 2010 else 0)
            gas, oil = cell(y, 12, "燃气"), cell(y, 11, "燃油")
            bio = cell(y, 13 if y == 2009 else 14, "生物质") + cell(y, 14 if y == 2009 else 15, "垃圾")
        elif y == 2011:
            hydro, pump, nuclear, wind, solar = [cell(y, r, label) for r, label in
                ((3, "水电"), (4, "抽水蓄能"), (6, "核电"), (7, "风电"), (8, "太阳能"))]
            coal = cell(y, 11, "燃煤") + cell(y, 12, "煤矸石")
            gas, oil, bio = cell(y, 14, "燃气"), cell(y, 13, "燃油"), cell(y, 15, "生物质")
        elif y == 2012:
            hydro, pump, nuclear, wind, solar = [cell(y, r, label) for r, label in
                ((32, "水电"), (33, "抽水蓄能"), (35, "核电"), (36, "风电"), (37, "太阳能"))]
            # Same-year national values printed in the following annual table.
            coal, gas, oil = [cell(2013, r, label, previous=True) for r, label in
                              ((61, "燃煤"), (62, "燃气"), (63, "燃油"))]
            bio = cell(y, 47, "垃圾") + cell(y, 48, "秸秆")
        else:
            hydro, pump, nuclear, wind, solar, coal, gas, oil = [cell(y, r, label) for r, label in
                ((58, "水电"), (59, "抽水蓄能"), (64, "核电"), (65, "风电"), (66, "太阳能"),
                 (61, "燃煤"), (62, "燃气"), (63, "燃油"))]
            bio = cell(y, 77, "垃圾") + cell(y, 78, "秸秆")
        if y <= 2011:
            coal *= 832326 / 831063
            gas *= 56970 / 56663
            oil *= 5116 / 2700
        bio *= 10300 / (4685 + 5117)
        history[y] = dict(coal=coal, gas=gas, oil=oil, biomass=bio,
                          hydro=hydro-pump, nuclear=nuclear, wind=wind, solar=solar)
    # 10300 is the explicitly cited full-scope footnote, not a silent average
    # with the separate NEA preliminary 9480 MW observation.
    original = (ROOT / paths[2014]).read_text(encoding="utf-8")
    if "1030万千瓦" not in original:
        raise ValueError("CEC full biomass footnote changed")
    total = cell(2014, 57, "发电装机容量")
    return history, total, lineage, paths


def scope_inputs(data, design, theta, *, recovery_share, priority_start_year=2015):
    """Whole EI vintage + CEC capacity + explicitly uncertain Other bridge.

    Pumped generation is a separate observed CEC anchor. Assigning it to EI
    Other, and allocating the remaining Other between loss recovery and a
    statistical adjustment, are TESTED HYPOTHESES, not observed category links.
    """
    if not 0 <= recovery_share <= 1:
        raise ValueError("Other recovery share must be bounded")
    data, design, theta = deepcopy(data), deepcopy(design), dict(theta)
    if priority_start_year not in {2015,2016}:
        raise ValueError("Unsupported historical priority comparison")
    from build_q2_revenue_evidence import html_text
    policy=html_text(ROOT/"data/raw/q2_revenue/nea_clean_dispatch_2015_518.html")
    if "风电、光伏发电、生物质发电按照本地区资源条件全额安排发电" not in policy:
        raise ValueError("Historical priority-policy evidence changed")
    design["assumptions"]["nonfossil_priority_start_year"]=priority_start_year
    rows, review = extract()
    mapping = dict(total="electricity_generation_mwh", coal="coal_electricity_mwh",
        gas="gas_electricity_mwh", oil="oil_electricity_mwh", hydro_primary="hydro_electricity_mwh",
        nuclear="nuclear_electricity_mwh", wind="wind_electricity_mwh", solar="solar_electricity_mwh",
        geothermal_biomass_other_renewables="biofuel_electricity_mwh", other_unallocated="unallocated_electricity_mwh")
    for row in rows:
        data[row["year"], mapping[row["category"]]] = row["value_twh"] * 1e6
    history, total, lineage, paths = reviewed_capacity_history()
    data[2014, "total_capacity_mw"] = total
    # The admitted observation is total hydro INCLUDING pumped storage.
    # Keep its original values and compare like for like; never inject pump
    # capacity into primary hydro output or silently deduct a constant stock.
    for target in design["targets"]:
        if target["metric"] == "hydro_capacity_mw" and target["observation"] == "hydro_capacity_mw":
            target["metric"] = "hydro_including_pumped_capacity_mw"
    # Use changed oil consistently in both initial nonpower state and all
    # training residuals. Refit the statistical coefficient to the same vintage.
    design["demand_identification"]["fitted"] = fit_nonpower(data, design)
    theta.update(identified_parameters(design["demand_identification"]["fitted"]))
    design["statistical_bridge"]["fitted"] = fit_bridge(data, design)
    pump_output, pump_power = 13.19e6, 22110.0
    remaining = data[2014, "unallocated_electricity_mwh"] - pump_output
    if remaining < 0:
        raise ValueError("Hypothesised Other bridge infeasible")
    recovered = remaining * recovery_share
    # The observed 18384 MW is >=6 MW recovered-energy capacity. The 717 MW
    # unresolved capacity is inherited but inactive, not free coal generation.
    residual_capacity = total - fsum(history[2014].values()) - pump_power - 18384
    if residual_capacity < 0:
        raise ValueError("Reviewed capacity bridge is overallocated")
    primary = data[2014,"consumption_10ktce"] * 1e4 * TCE_MWH * data[2014,"consumption_coal_pct"] / 100
    direct_coal = primary * (1-design["assumptions"]["nonenergy_fuel_fraction"]["coal"]) - data[2014,"coal_electricity_mwh"]/.41
    recovered_fraction = recovered/.3/direct_coal
    if recovered_fraction > 1-design["assumptions"]["direct_fuel_efficiency"]["coal"]:
        raise ValueError("Recovery exceeds reconstructed upstream losses")

    def inherited_plant(capacity, output):
        return dict(exit_year=2039, fixed_om_cny_per_year=capacity*100000,
            initial_book_value_cny=capacity*4e6, initial_generation_mwh=output,
            energy_tariff_real_cny_per_gross_mwh=design["assumptions"]["generation_price_cny_per_mwh"],
            operation=dict(input="recovered_heat", output="electricity", efficiency=.3,
                capacity_mw=capacity, availability=[.85]*4, variable_cost_per_mwh=20,
                minimum_fraction=0, ramp_mw_per_hour=capacity*.2, window_energy_budget_mwh=output/365))

    boundary = InheritedOperatingBoundary(initial_year=2014,
        stores={"pumped_hydro":dict(exit_year=2054, fixed_om_cny_per_year=pump_power*100000,
            initial_book_value_cny=pump_power*6e6,
            operation=dict(power_mw=pump_power, energy_mwh=pump_power*6, initial_mwh=pump_power*3,
                charge_efficiency=sqrt(.8), discharge_efficiency=sqrt(.8), throughput_cost=3))},
        recovery_plants={"inherited_recovery":inherited_plant(18384,recovered),
                         "unidentified_inactive_stock":inherited_plant(residual_capacity,0)},
        recoveries={"industrial_heat":dict(output="recovered_heat",source_input_fractions={
            design["assumptions"]["demand_fuel_archetypes"]["coal"]+"/coal":recovered_fraction})},
        initial_pumping_mwh=pump_output/.8, initial_pumped_generation_mwh=pump_output,
        initial_statistical_adjustment_mwh=remaining-recovered, capacity_history=history, evidence=EVIDENCE)
    assumptions = dict(recovery_share_of_other_after_pump=recovery_share,
        nonfossil_priority_start_year=priority_start_year,
        initial_statistical_adjustment_mwh=remaining-recovered, recovery_fraction_of_direct_coal_input=recovered_fraction,
        unidentified_inactive_capacity_mw=residual_capacity,
        pumped_roundtrip_efficiency=.8, pumped_duration_hours=6, pump_initial_fraction=.5,
        supplementary_fixed_om_cny_per_mw_year=100000, recovery_efficiency=.3,
        waste_carbon="not_yet_integrated_into_total_carbon_no_carbon_acceptance",
        ei_other_mapping="conditional_not_observed", source_capacity_rows=lineage)
    return data, design, theta, boundary, assumptions, list(paths.values())


def tariff_inputs(data, design, *, mode):
    if mode not in {"legacy", "energy_only", "finite", "all_in"}:
        raise ValueError("Unknown revenue experiment")
    path = "data/processed/q2/revenue/nea_tariff_and_auxiliary_use.csv"
    rows = csv_rows(path)
    review = json.loads((ROOT/"data/catalog/q2_revenue_review.json").read_text("utf-8"))
    for source, digest in review["source_sha256"].items():
        if sha(source) != digest:
            raise ValueError("Changed reviewed revenue source: " + source)
    cells = {(int(r["year"]),r["technology"],r["metric"]):float(r["value"]) for r in rows}
    from build_q2_revenue_evidence import PRICES,AUX_USE,TECHS as REPORT_TECHS
    expected={(y,t,m):values[y][i] for m,values in
              (("feed_in_tariff",PRICES),("auxiliary_own_use",AUX_USE))
              for y in values for i,t in enumerate(REPORT_TECHS)}
    if len(cells)!=len(rows) or cells!=expected:
        raise ValueError("Revenue transcription differs from reviewed source extraction")
    prices, meters, factors, tax = {}, {}, {}, {}
    for y in (2014, *YEARS):
        # Equal monthly export is an explicit approximation to the May change.
        tax[y] = 1/1.17 if y < 2018 else 4/12/1.17+8/12/1.16
        factors[y] = data[2024,"cpi"]/data[y,"cpi"]
        meters[y] = {t:1-cells[y,t,"auxiliary_own_use"]/100 for t in TECHS if t!="oil"}
        # No observed oil own-use/tariff. Coal is an explicit billing proxy only.
        meters[y]["oil"] = meters[y]["coal"]
        prices[y] = {}
        for t in TECHS:
            if mode == "legacy":
                p = design["assumptions"]["generation_price_cny_per_mwh"]
                if t in {"wind","solar"}:
                    p += (design["assumptions"]["renewable_tariff_2014_proxy"][t]-p)*(2021-y)/7
                prices[y][t] = p  # historical gross-billing control, disclosed
            else:
                source_t = "coal" if t=="oil" or (mode!="all_in" and t in {"wind","solar","biomass"}) else t
                prices[y][t] = cells[y,source_t,"feed_in_tariff"]*tax[y]*factors[y]*meters[y][t]
    fiscal = fiscal_observations()
    funding = {}
    for y in YEARS:
        # Actual fund revenue is an observed exogenous aggregate. The chosen
        # fraction of expenditure is a scenario cap, NEVER enterprise receipts.
        funding[y] = dict(levy_receipts_cny=float(fiscal[y,"revenue"]["actual"])*1e8 if mode=="finite" else 0,
            treasury_transfer_cny=0., expenditure_limit_cny=float(fiscal[y,"expenditure"]["actual"])*1e8 if mode=="finite" else 0)
    policy = AnnualRevenuePolicy(energy_tariffs=prices,annual_funding=funding,support_rates={},
        positions=[],opening_cash_cny=0,opening_payables=[],initial_year=2014,
        real_2024_per_nominal=factors,metering_fraction=meters,evidence=EVIDENCE)
    return policy, cells, tax


def add_existing_support(model, cells, tax, *, available_fraction):
    """Bounded existing-fleet support-spread experiment, not legal eligibility.

    No new project inherits an existing position. No 2020 lifetime rules are
    backdated. The 4-year exercise truncates support in 2019 without making a
    claim about rights beyond that date. Missing pre-2014 arrears are a stated
    zero-opening sensitivity, not a measured clean balance sheet.
    """
    if not 0<=available_fraction<=1:
        raise ValueError("Payment availability outside [0,1]")
    policy=model.revenue_policy
    for y in YEARS:
        policy.annual_funding[y]["expenditure_limit_cny"] *= available_fraction
        policy.support_rates[y] = {}
    for cohort in model.cohorts:
        t=cohort["tech"]
        if t not in {"wind","solar","biomass"} or cohort["status"]!="active":
            continue
        online=cohort["online_year"]
        # Only reconstructed post-law cohorts enter the broad upper entitlement
        # set. Actual catalog admission/provincial reference prices are unknown.
        if online<2006:
            continue
        duration=2019-online
        terms=SupportTerms(project=cohort["id"],actor=t,eligible=True,
            commissioned_year=online,policy_start_year=2015,eligible_years=duration,
            capacity_mw=cohort["capacity_mw"],lifetime_hours=8760*duration,priority=0,evidence=EVIDENCE)
        prior=cohort["capacity_mw"]*model.generators[t].reference_cf*8760*max(0,2015-online)*policy.export_fraction(2014,t)
        policy.positions.append(dict(terms=terms,prior_lifetime_mwh=prior))
        for y in YEARS:
            policy.support_rates[y][terms.project]=dict(
                supported_tariff_cny_per_mwh=cells[y,t,"feed_in_tariff"],
                reference_tariff_cny_per_mwh=cells[y,"coal","feed_in_tariff"],vat_rate=1/tax[y]-1)


def main():
    data,design,_=preflight()
    calibration_path="outputs/q2/p2_lb_national/calibration.json"
    theta=json.loads((ROOT/calibration_path).read_text("utf-8"))["best"]["parameters"]
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder=ROOT/"outputs/q2_empirical_support"/run_id
    folder.mkdir(parents=True)
    results,source_paths={},set(CODE+INPUTS+[calibration_path])
    references={(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    specs=[("legacy_v10",None,"legacy",0),
           ("scoped_legacy_income",.5,"legacy",0),
           ("scoped_energy_only",.5,"energy_only",0),
           ("scoped_finite_half",.5,"finite",.5),
           ("scoped_finite_full",.5,"finite",1),
           ("scoped_all_in_upper",.5,"all_in",0),
           ("scoped_priority_2016_control",.5,"finite",1),
           ("other_no_recovery",0.,"finite",1),
           ("other_all_remaining_recovery",1.,"finite",1)]
    for name, share, mode, available in specs:
        if share is None:
            model=NationalModel(data,design,theta,2014,detail=True)
            assumptions={"legacy_scope_and_finance_defects":"retained_as_comparison_only"}
        else:
            scoped,settings,pars,boundary,assumptions,paths=scope_inputs(data,design,theta,recovery_share=share,
                priority_start_year=2016 if name=="scoped_priority_2016_control" else 2015)
            source_paths.update(paths)
            policy,cells,tax=tariff_inputs(scoped,settings,mode=mode)
            model=NationalModel(scoped,settings,pars,2014,detail=True,revenue_policy=policy,operating_boundary=boundary)
            if mode=="finite":
                add_existing_support(model,cells,tax,available_fraction=available)
            assumptions.update(revenue_mode=mode,available_spending_fraction=available,
                initial_fund_cash_assumption=0,initial_arrears_assumption=0,
                new_project_support="excluded_in_this_existing_support_experiment",
                unknown_oil_tariff_and_own_use="coal_billing_proxy_not_observation")
        initial=dict(capacity_mw=model.initial_capacities,generation_mwh=model.initial_generation,
                     terminal_electricity_mwh=model.base_electric,parameters=model.theta)
        model.run(2018)
        metrics={}
        for t in ("gas","oil","biomass"):
            diagnostics=[]
            for row in model.paths:
                y=row["year"]
                # All cases evaluated against the same pure-category vintage.
                reference=references[y,"geothermal_biomass_other_renewables" if t=="biomass" else t]
                diagnostics.append(dict(year=y,model_mwh=row[t+"_generation_mwh"],observed_mwh=reference,
                    relative_error=row[t+"_generation_mwh"]/reference-1,
                    utilisation_hours=row[t+"_generation_mwh"]/row[t+"_capacity_mw"]))
            metrics[t]=dict(years=diagnostics,mape=fsum(abs(r["relative_error"]) for r in diagnostics)/len(diagnostics),
                autonomous_project_count=len([p for p in model.projects if p["tech"]==t and not p["initial_reconstruction"]]))
        results[name]=dict(initial=initial,assumptions=assumptions,metrics=metrics,paths=model.paths,
            projects=model.projects,finance=model.finance,behavior=model.behavior,
            operations=model.operations,balances=model.balances,
            fund_history=model.revenue_policy.history if model.revenue_policy else [])
        print(name,{t:round(v["mape"]*100,2) for t,v in metrics.items()},flush=True)
    source_paths.update(["scripts/run_q2_empirical_support.py","data/raw/q2_capacity_detail/research.py",
        "scripts/build_q2_electricity_scope.py","data/raw/q2_technology_scope/ei_2025_original.xlsx",
        "scripts/build_q2_revenue_evidence.py","data/raw/q2_capacity_detail/source_manifest.json",
        "data/raw/q2_fiscal/build_fiscal.py","data/raw/q2_fiscal/source_manifest.json",
        "data/processed/q2/revenue/nea_tariff_and_auxiliary_use.csv","data/catalog/q2_revenue_review.json",
        "data/raw/q2_fiscal/annual_renewable_levy.csv",EVIDENCE])
    review=json.loads((ROOT/"data/catalog/q2_revenue_review.json").read_text("utf-8"))
    source_paths.update(review["source_sha256"])
    for r in csv_rows("data/raw/q2_fiscal/annual_renewable_levy.csv"):
        if int(r["year"]) in YEARS and r["scope"]=="national":source_paths.add("data/raw/q2_fiscal/"+r["source_file"])
    report=dict(status="conditional_historical_mechanism_experiment_not_acceptance",run_id=run_id,
        years=YEARS,team_approved=False,evaluation_identity="training_subwindow_no_blind_validation",
        fixed_behavioral_parameters=True,reidentified_demand_from_changed_source=True,
        new_calibration=False,source_sha256={p:sha(p) for p in sorted(source_paths)},results=results)
    (folder/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    text=["# 2015—2018真实输入条件对照", "",
        "状态：局部机制实验；固定行为参数，修订口径后重新识别非电需求和统计桥。不是全国重新校准或盲测。", "",
        "| 对照 | 气电MAPE | 纯油电MAPE | 复合生物能源MAPE | 自主气/生物项目数 |",
        "|---|---:|---:|---:|---:|"]
    for name,result in results.items():
        m=result["metrics"]
        text.append(f"| {name} | {100*m['gas']['mape']:.2f}% | {100*m['oil']['mape']:.2f}% | {100*m['biomass']['mape']:.2f}% | {m['gas']['autonomous_project_count']} / {m['biomass']['autonomous_project_count']} |")
    text.extend(["", "所有组使用相同EI2025纯油目标；旧模型的油标签错误不能继续作为比较分母。新增项目包含窗口后才投产的队列，不能把本窗发电改善归于尚未投产项目。", "",
        "| 财政假设 | 四年实际模拟支付（亿元） | 2018年末模拟欠款（亿元） |",
        "|---|---:|---:|"])
    for name in ("scoped_finite_half","scoped_finite_full"):
        rows=results[name]["paths"]
        text.append(f"| {name} | {fsum(r['subsidy_paid_nominal_cny'] for r in rows)/1e8:.2f} | {rows[-1]['subsidy_arrears_nominal_cny']/1e8:.2f} |")
    text.extend(["", "财政行是给定资格、零期初欠款及支付上限假设下的模拟，不能当作中国企业实际收款或实际拖欠。气电技术电价不等同于财政补贴；既有补贴支付不自动赋予新项目未来资格。", "",
        "全部输入、代码哈希、逐年物理/现金/项目明细见同目录results.json；假设及未解决项见docs/sources/q2_empirical_support_experiment.md。未完成2019—2024收入接入、完整新项目政策、垃圾化石碳、长期情景和完整答题交付。", ""])
    (folder/"report.md").write_text("\n".join(text),encoding="utf-8")
    print(folder.relative_to(ROOT).as_posix())


if __name__=="__main__":
    main()
