"""Read-only binding and accounting review; no scientific fit thresholds."""
from collections import defaultdict
from datetime import datetime,timezone
from hashlib import sha256
from math import fsum
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/"outputs/q2_current_delivery/20261020T004752442611Z"


def load(path):
    return json.loads(path.read_text("utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    status=load(FOLDER/"status.json")
    assert status["status"]=="complete_conditional_scenarios"
    design=load(FOLDER/"design.json")
    master=load(FOLDER/"results.json")
    snapshot=load(FOLDER/"source_snapshot.json")
    assert snapshot==master["source_sha256"]
    mismatches=[p for p,h in snapshot.items() if digest(ROOT/p)!=h]
    assert not mismatches,mismatches
    expected={s["name"]:s for s in design["scenarios"]}
    assert len(expected)==len(master["results"])==50
    assert set(expected)=={r["name"] for r in master["results"]}
    rows={}
    path_cache={}
    maximum=defaultdict(float)
    file_hashes={}
    errors=defaultdict(float)
    fund_errors=defaultdict(float)
    opening_refs={}
    for item in master["results"]:
        name=item["name"]
        assert item["status"]=="success",name
        path=FOLDER/item["result_file"]
        file_hashes[path.name]=digest(path)
        assert file_hashes[path.name]==item["result_sha256"],name
        case=load(path)
        raw=dict(expected[name])
        opening=raw.pop("opening_variant",{})
        authority=raw.pop("authority",25)
        mode=raw.pop("thermal_mode","net58")
        assert case["spec"]==raw and case["opening_variant"]==opening,name
        assert case["authority"]==authority and case["thermal_mode"]==mode,name
        assert case["historical_parameter_run"]==design["historical_runs"][mode]
        assert case["independent_observed_initial_state"]
        paths=case["paths"]
        assert [r["year"] for r in paths]==list(range(2025,2061))
        assert case["initial_path"]["year"]==2024
        assert case["initial_path"]["total_capacity_mw"]==3349220
        byyear={r["year"]:r for r in paths}
        path_cache[name]=paths
        # Directly recompute stock, aggregate-operation, carbon and finance
        # identities, reporting rounding residuals without new acceptance gates.
        opgen=defaultdict(list)
        opdemand=defaultdict(list)
        cash=defaultdict(list)
        sector=defaultdict(list)
        gasimport=defaultdict(list)
        for op in case["operations"]:
            if op["kind"]=="generation":
                opgen[op["year"],op["plant"]].append(op["output_mwh"]*365)
            elif op["kind"]=="demand":
                opdemand[op["year"]].append(op["unmet_service_mwh"]*365)
                sector[op["sector"]].append(op["unmet_service_mwh"]*365)
            elif op["kind"]=="fuel" and op["fuel"]=="gas":
                gasimport[op["year"]].append(op["import_mwh"]*365)
        for entry in case["finance"]:
            cash[entry["year"]].append(entry.get("cash_delta_cny",0))
        for r in paths:
            y=r["year"]
            for key,value in r.items():
                if "residual" in key and isinstance(value,(int,float)):
                    maximum[key]=max(maximum[key],abs(value))
            for tech in ("coal","gas","oil","biomass","hydro","nuclear","wind","solar"):
                errors["operation_generation_mwh"]=max(errors["operation_generation_mwh"],
                    abs(fsum(opgen[y,tech])-r[tech+"_generation_mwh"]))
            errors["operation_unmet_mwh"]=max(errors["operation_unmet_mwh"],
                abs(fsum(opdemand[y])-r["unmet_service_mwh"]))
            errors["whole_operation_cash_cny"]=max(errors["whole_operation_cash_cny"],
                abs(fsum(cash[y])+r["ets_net_transfer_cny"]-
                    (r["external_service_income_cny"]-r["operating_resource_cost_cny"])))
            errors["carbon_t"]=max(errors["carbon_t"],
                abs(r["positive_co2_t"]-r["combustion_co2_t"]-r["other_positive_co2_t"]))
            errors["net_carbon_t"]=max(errors["net_carbon_t"],
                abs(r["net_co2_t"]-r["positive_co2_t"]+r["net_removals_t"]))
            errors["capacity_mw"]=max(errors["capacity_mw"],
                abs(r["total_capacity_mw"]-fsum(r[t+"_capacity_mw"] for t in
                    ("coal","gas","oil","biomass","hydro","nuclear","wind","solar"))-
                    r["supplementary_capacity_mw"]))
        for f in case["subsidy_fund_history"]:
            fund_errors["cash_identity_cny"]=max(fund_errors["cash_identity_cny"],abs(
                f["opening_cash_cny"]+f["levy_receipts_cny"]+f["treasury_transfer_cny"]-
                f["paid_cny"]-f["closing_cash_cny"]))
            fund_errors["arrears_identity_cny"]=max(fund_errors["arrears_identity_cny"],abs(
                f["opening_arrears_cny"]+f["new_entitlement_cny"]-f["paid_cny"]-f["closing_arrears_cny"]))
            fund_errors["maximum_expenditure_limit_excess_cny"]=max(
                fund_errors["maximum_expenditure_limit_excess_cny"],
                f["paid_cny"]-f["expenditure_limit_cny"])
        future_gas=[p for p in case["projects"] if p["tech"]=="gas" and p["decision_year"]>=2025]
        if raw.get("freeze_new_gas"):assert not future_gas
        sheet=case["initial_path"]["opening_balance_sheet"]
        opening_refs[name]=dict(generator_capacity_mw=case["initial_path"]["generator_capacity_mw"],
            debt_cny=fsum(s["debt_cny"] for s in sheet),
            cash_cny=fsum(s["unrestricted_cash_cny"] for s in sheet),
            equity_cny=fsum(s["opening_equity_cny"] for s in sheet))
        rows[name]=dict(summary=case["summary"],gas_projects_2025_onward=len(future_gas),
            gas_approved_mw=fsum(p["capacity_mw"] for p in future_gas),
            gas_import_mwh_2028_2030=fsum(fsum(gasimport[y]) for y in (2028,2029,2030)),
            unmet_by_sector_mwh={s:fsum(v) for s,v in sector.items() if fsum(v)},
            first_unmet_year=next((r["year"] for r in paths if r["unmet_service_mwh"]>1),None),
            targets=case["targets"],peak=case["peak"])
    for name in ("SG","SW","SGW","SG_volume_only","SG_price_only"):
        assert path_cache["S0"][:3]==path_cache[name][:3],name
    baseline=rows["S0"]
    base_paths=path_cache["S0"]
    s0points={str(r["year"]):r for r in base_paths if r["year"] in (2025,2030,2060)}
    physical_metrics=("cumulative_positive_co2_t","cumulative_unmet_service_mwh",
                      "terminal_capacity_mw")
    zero_response={}
    for name in ("SP","SG_volume_only","S0_freeze_gas"):
        zero_response[name]={k:rows[name]["summary"][k]-baseline["summary"][k] for k in physical_metrics}
    # Verify experiment hashes again after reading all case files.
    assert not [p for p,h in snapshot.items() if digest(ROOT/p)!=h]
    assert file_hashes=={p:digest(FOLDER/p) for p in file_hashes}
    result=dict(status="completed_read_only_binding_and_accounting_review",
        created_utc=datetime.now(timezone.utc).isoformat(),folder=FOLDER.relative_to(ROOT).as_posix(),
        cases=50,source_files=len(snapshot),source_hash_mismatches=mismatches,
        source_snapshot_sha256=digest(FOLDER/"source_snapshot.json"),
        master_results_sha256=digest(FOLDER/"results.json"),result_file_sha256=file_hashes,
        baseline_points=s0points,reported_maximum_residuals=dict(maximum),
        independently_recomputed_identity_residuals=dict(errors),
        independently_recomputed_fund_residuals=dict(fund_errors),opening_accounts=opening_refs,
        all_case_results=rows,zero_response_diagnostics=zero_response,
        paired_effects=master["paired_effects"],policy_frontier=master["policy_frontier"],
        interpretation_limits=[
            "No additional fitting threshold or scientific acceptance gate was introduced.",
            "Opening match is an initial condition, not historical-fit validation.",
            "Reported peak 2024 uses the disclosed historical CO2 scope bridge, not an observed official BTR2024 point.",
            "No gas investment in the baseline makes the H02 investment-freeze comparison uninformative about that channel.",
            "Zero gas-volume stress response means this tested volume boundary did not bind; it is not a universal safety result.",
            "Finite-horizon discounted resource cost is not terminal-asset-value-adjusted lifecycle cost.",
            "GDP infrastructure funding is a disclosed financing envelope, not measured grid-company available cash.",
            "Policy frontier is restricted to the finite tested candidates; all projections remain conditional."])
    out=ROOT/"outputs/validation/current_delivery_review_20261020.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")
    print(out)
    print(json.dumps(dict(cases=50,source_files=len(snapshot),residuals=dict(errors),
        S0=baseline["summary"],S0_unmet_sector=baseline["unmet_by_sector_mwh"],
        policy_frontier=master["policy_frontier"]),ensure_ascii=False,indent=2))


if __name__=="__main__":main()
