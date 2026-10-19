"""Independent second check of national outputs, reproducibility and protected work.

The audit recomputes identities from exported rows in a fresh process. It never
changes error thresholds or confers another team member's approval.
"""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"));sys.path.insert(0,str(ROOT/"src"))
from run_q2_national import verify_latest,load,dump,sha,CODE,INPUTS


def read(path):
    with Path(path).open(encoding="utf-8",newline="") as f:return list(csv.DictReader(f))


def main():
    out=ROOT/"outputs/q2_review/p2_lb_national"
    out.mkdir(parents=True,exist_ok=True)
    report=dict(passed=False,status="running",checks=[],team_approved=False,
        completion_scope="Q2 author conditional aggregate research candidate; no official/all-GHG/probabilistic certification")
    # Replace stale success BEFORE reading inputs or running any check.
    dump(out/"verification.json",report)
    start=time.perf_counter()
    def check(name,passed,detail,blocking=True):
        report["checks"].append(dict(name=name,passed=bool(passed),detail=detail))
        dump(out/"verification.json",report)
        if not passed and blocking:raise ValueError(name)
    def command(name,args,expected=0,env=None):
        report["running_check"]=name
        dump(out/"verification.json",report)
        r=subprocess.run([sys.executable,"-B","-X","utf8",*args],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",env=env)
        (out/(name+".log")).write_text(r.stdout+r.stderr,encoding="utf-8")
        check(name,r.returncode==expected,dict(returncode=r.returncode,expected=expected,tail=(r.stdout+r.stderr)[-500:]))
    try:
        folder=ROOT/"outputs/q2/p2_lb_national"
        manifest=verify_latest(folder)
        check("latest_national_results_match_code_inputs_sources",True,manifest["run_id"])
        # Existing full regression is a separate receipt, checked for current test code.
        regression=load(ROOT/"outputs/q2_review/p2_lb/verification.json")
        tests=load(ROOT/"outputs/q2_review/p2_lb/tests.json")
        check("full_regression_tests_no_skip",regression["passed"] and tests["passed"] and tests["skipped"]==0,tests)
        check("regression_covers_current_mechanisms",all(regression["code_hashes"].get(p)==sha(ROOT/p) for p in
            ("tests/test_q2_national.py","src/energy_model/q2_national.py","src/energy_model/q2_finance.py","src/energy_model/q2_operations.py","src/energy_model/q2_admission.py")),"Fresh full regression includes mechanism counterexamples")
        import importlib.metadata
        expected=dict(numpy="2.3.5",scipy="1.16.3",mesa="3.3.1",pandas="3.0.1",matplotlib="3.10.7")
        report["dependencies"]={p:importlib.metadata.version(p) for p in expected}
        check("frozen_dependency_versions",report["dependencies"]==expected,report["dependencies"])
        protected=["data/sources.json","data/evidence_reviews.json","workflow/model_inputs.json"]
        protected += [p.relative_to(ROOT).as_posix() for p in (ROOT/"只读工作区").iterdir() if p.is_file()]
        protected += [p.name for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in {".xlsx",".pdf"}]
        hashes={}
        for rel in protected:
            original=subprocess.run(["git","show","804ec15ee43874303986a7ad91b2cde05c65b124:"+rel],cwd=ROOT,capture_output=True)
            if original.returncode:raise ValueError("Missing protected base object "+rel)
            expected=hashlib.sha256(original.stdout).hexdigest()
            if sha(ROOT/rel)!=expected:raise ValueError("Protected original changed "+rel)
            hashes[rel]=expected
        check("official_originals_and_Q1_contracts_equal_common_base",True,hashes)
        q1=load(ROOT/"outputs/q1/p1_yx/run_manifest.json")
        check("q1_18_scientific_outputs_preserved",len(q1["outputs"])==18 and all(sha(ROOT/"outputs/q1/p1_yx"/n)==v for n,v in q1["outputs"].items()),list(q1["outputs"]))
        calibration=load(folder/"calibration.json")
        # Failed fit remains a failed acceptance check, but must not prevent
        # independent replication and accounting checks from being executed.
        check("frozen_empirical_thresholds_passed",calibration["quality"]["acceptance"]["all_thresholds_passed"],calibration["quality"]["acceptance"],blocking=False)
        check("all_grid_trials_accounted",calibration["successful_trials"]==calibration["search_budget"]==load(folder/"frozen_design.json")["search_budget"],calibration["search_budget"])
        eval_emission=next(r for r in calibration["quality"]["already_seen_evaluation"]["components"] if r["metric"]=="combustion_co2_t")
        check("missing_emissions_holdout_not_fabricated",eval_emission["n"]==0 and eval_emission["mape"] is None,eval_emission)
        baseline=read(folder/"baseline_path.csv")
        check("full_2025_2060_path",[int(r["year"]) for r in baseline]==list(range(2025,2061)),len(baseline))
        operations=read(folder/"operations.csv")
        physical=[]
        for year in range(2025,2061):
            row=next(r for r in baseline if int(r["year"])==year)
            fuel=[r for r in operations if r["kind"]=="fuel" and int(r["year"])==year]
            expected=sum(float(r["combustion_co2_t"])*365 for r in fuel)
            scale=max(1,float(row["combustion_co2_t"]))
            if abs(expected-float(row["combustion_co2_t"]))/scale>1e-10:raise ValueError("Exported emissions ledger "+str(year))
            if abs(float(row["positive_co2_t"])-float(row["net_removals_t"])-float(row["net_co2_t"]))>1e-4:raise ValueError("Net CO2 "+str(year))
            physical.append(dict(year=year,combustion_residual_t=expected-float(row["combustion_co2_t"]),
                LP_max_residual_mwh=float(row["max_residual"]),cash_residual_cny=float(row["cash_balance_residual_cny"])))
        check("exported_combustion_and_net_CO2_reconcile",True,physical)
        check("small_physical_residuals",max(r["LP_max_residual_mwh"] for r in physical)<.001,max(r["LP_max_residual_mwh"] for r in physical))
        check("cash_and_ETS_transfers_reconcile",all(abs(float(r["cash_balance_residual_cny"]))<.1 and abs(float(r["ets_balance_cny"]))<.001 for r in baseline),"National annual CNY residual < 0.1; ETS residual < 0.001")
        check("construction_commitments_funded",all(abs(float(r["construction_fund_residual_cny"]))<.1 for r in baseline),"Reserved funding equals sum of unpaid project commitments")
        check("infrastructure_and_financing_ledgers",all(abs(float(r["infrastructure_fund_residual_cny"]))<.1 and abs(float(r["financing_transfer_residual_cny"]))<.1 for r in baseline),"Independent infrastructure escrow and sponsor/shareholder/lender transfers")
        check("cross_year_storage_continuity",all(abs(float(a["storage_closing_mwh"])-float(b["storage_retirement_loss_mwh"])-float(b["storage_opening_mwh"]))<1e-4 for a,b in zip(baseline,baseline[1:])),"New storage enters empty; retirement disposal explicitly deducted")
        accounts=read(folder/"accounts.csv")
        consumer_rows=[r for r in accounts if r["kind"]=="consumer_operation" and r.get("energy_budget_cny")]
        check("all_four_service_budgets_fund_energy",len(consumer_rows)==36*4 and all(
            float(r["energy_bill_cny"])<=float(r["energy_budget_cny"])+.01 and
            abs(float(r["consumer_cash_balance_residual_cny"]))<.1 for r in consumer_rows),
            dict(rows=len(consumer_rows),cash_tolerance_cny=.1,basis="Same absolute roundoff bound as national cash ledger; multi-trillion CNY balances"))
        for actor in sorted({r["actor"] for r in consumer_rows}):
            ledger=[r for r in accounts if r["actor"]==actor and r.get("closing_cash_cny")]
            for left,right in zip(ledger,ledger[1:]):
                if abs(float(left["closing_cash_cny"])-float(right["opening_cash_cny"]))>.01:
                    raise ValueError("Consumer cash discontinuity: "+actor)
        device_payments=[r for r in accounts if r["kind"]=="device_finance_and_construction"]
        check("device_payments_and_retained_cash_reconcile",len(device_payments)==36*4 and all(
            abs(float(r["device_cash_balance_residual_cny"]))<.01 and float(r["closing_cash_cny"])>=-.01 and
            abs(float(r["actor_cash_transfer_cny"])+float(r["construction_receipt_cny"]))<.01 for r in device_payments),len(device_payments))
        device_projects=load(folder/"device_project_queue.json")
        for p in device_projects:
            if p["online"]!=p["decision"]+1 or p["paid_cost_cny"]<=0:
                raise ValueError("Unpaid or instantaneous device commissioning")
        for payment in device_payments:
            total=sum(p["paid_cost_cny"] for p in device_projects if p["actor"]==payment["actor"] and p["decision"]==int(payment["year"]))
            if abs(total-float(payment["amount_cny"]))>.01:raise ValueError("Device queue funding mismatch")
        check("all_service_device_queues_paid_and_delayed",bool(device_projects),len(device_projects))
        behavior=read(folder/"behavior.csv")
        construction=[]
        for approval in (r for r in behavior if r["kind"]=="approval"):
            year=int(approval["year"]);tech=approval["project"].split('/')[1]
            proposal=next(r for r in behavior if r["kind"]=="investment_proposal" and int(r["year"])==year and r["actor"]==tech)
            limit=float(proposal["construction_limit_mw"])
            total=sum(float(r["approved_mw"]) for r in behavior if r["kind"]=="approval" and int(r["year"])==year and r["project"].split('/')[1]==tech)
            construction.append(dict(year=year,tech=tech,approved_mw=total,construction_limit_mw=limit,
                ratio=total/limit,exceeds=total>limit+1e-7))
        check("hard_construction_ceiling_all_annual_approvals",bool(construction) and not any(r["exceeds"] for r in construction),
              dict(approvals=len(construction),exceedances=sum(r["exceeds"] for r in construction),max_ratio=max(r["ratio"] for r in construction)))
        dump(out/"construction_limit_checks.json",dict(run_id=manifest["run_id"],code_hashes=manifest["code_hashes"],checks=construction))
        for year in range(2025,2061):
            approvals={r["project"].split('/')[1]:float(r["approved_mw"]) for r in behavior
                       if r["kind"]=="approval" and int(r["year"])==year and r["project"].split('/')[1] in {"wind","solar"}}
            if not approvals:continue
            audits=[r for r in behavior if r["kind"]=="joint_renewable_audit" and int(r["year"])==year and r["approved"]=="True"]
            if len(audits)!=1:raise ValueError("Missing final joint renewable approval")
            capacities=json.loads(audits[0]["capacities_mw"])
            npvs=json.loads(audits[0]["incremental_npvs_cny_per_mw"])
            if capacities!=approvals or not all(v>0 for v in npvs.values()):raise ValueError("Unaudited renewable portfolio")
        check("renewable_approvals_match_final_joint_sales_audit",True,"Every approved project checked with the other same-batch projects present")
        projects=load(folder/"project_queue.json")
        for p in projects:
            if p["initial_reconstruction"]:continue
            funding=[r for r in accounts if r["kind"]=="project_finance" and r["project"]==p["id"]]
            if len(funding)!=1:raise ValueError("Missing unique project finance "+p["id"])
            r=funding[0]
            if abs(sum(float(r[k]) for k in ("equity_cny","shareholder_equity_cny","debt_draw_cny"))-p["cost"])/max(1,p["cost"])>1e-12:
                raise ValueError("Project funding mismatch "+p["id"])
        check("every_new_generator_has_equity_and_loan_funding",True,len([p for p in projects if not p["initial_reconstruction"]]))
        assets=read(folder/"assets.csv")
        pre1991=[r for r in assets if r.get("tech")=="nuclear" and int(r["online_year"])<1991]
        check("no_pre1991_nuclear_cohort",not pre1991,len(pre1991))
        target=read(folder/"targets_2030_2060.csv")
        required={"primary_energy_tce","nonfossil_share_proxy","positive_co2_t","peak_year","peak_value","energy_intensity_reduction_vs_2005",
            "carbon_intensity_reduction_vs_2005","carbon_intensity_reduction_vs_2025","neutralisation_ratio","net_co2_t"}
        check("question2_all_target_metrics",all(required.issubset({r["metric"] for r in target if int(r["year"])==y}) for y in (2030,2060)),sorted(required))
        coverage=load(folder/"experiment_coverage.json")
        check("all_sensitivity_runs_successful",coverage["executed"]==coverage["successful"] and not load(folder/"sensitivity_failures.json"),coverage)
        sensitivity=read(folder/"sensitivity.csv")
        factor_labels={r["label"] for r in sensitivity if r["kind"]=="one_factor"}
        check("all_three_required_factors_two_sides",len(factor_labels)==6,sorted(factor_labels))
        check("Morris_and_joint_sampling_executed",coverage["morris_trajectories"]==6 and coverage["joint_sample_size"]==12,
              dict(morris=len(read(folder/"morris_effects.csv")),joint_samples=coverage["joint_sample_size"]))
        # Reproduce with a different process and PYTHONHASHSEED, not a second call in this interpreter.
        import os
        env=dict(os.environ,PYTHONHASHSEED="7919")
        command("fresh_process_reproduction",["run.py","q2","--config","workflow/q2_inputs.json","--output-dir","outputs/q2/p2_lb_national_reproduction"],env=env)
        other=verify_latest(ROOT/"outputs/q2/p2_lb_national_reproduction")
        check("all_scientific_artifacts_byte_identical",manifest["outputs"]==other["outputs"],dict(artifacts=len(manifest["outputs"]),hash_seed=7919))
        # This audit's copied output is a local failure probe, not the primary delivery.
        import shutil
        probe=ROOT/"outputs/q2/p2_lb_national_failure_probe"
        if probe.exists():
            old=load(probe/"run_manifest.json")
            destination=probe.parent/(probe.name+".attempts")/(old["run_id"]+"-pre-audit")
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(probe),str(destination))
        shutil.copytree(folder,probe)
        shutil.copyfile(folder.parent/(folder.name+".latest-attempt.json"),probe.parent/(probe.name+".latest-attempt.json"))
        cell="import sys;sys.path.insert(0,'scripts');import run_q2_national as r;sys.argv=['probe','--output-dir','outputs/q2/p2_lb_national_failure_probe'];r.preflight=lambda:(_ for _ in ()).throw(ValueError('injected admission failure'));r.main()"
        command("admission_failure_probe",["-c",cell],expected=1)
        rejected=False
        try:verify_latest(probe)
        except ValueError:rejected=True
        check("latest_failure_not_hidden_by_old_success",rejected and load(probe/"run_manifest.json")["status"]=="failed","Original success preserved under probe .attempts; primary delivery untouched")
        verify_latest(folder)
        all_passed=all(c["passed"] for c in report["checks"])
        report.update(passed=all_passed,status="repaired_conditional_Q2_candidate_review_ready" if all_passed else "implementation_verified_empirical_acceptance_failed",implementation_and_declared_checks_complete=all_passed,
            closed_implementation_gaps=["Finite paid equipment for all four service proxies",
                "Consumer energy budgets and retained cash constrain device purchases",
                "Shared demand elasticity schedule and final joint renewable approval",
                "Audit running/failure state replaces stale success before checks",
                "Hard annual construction cap enforced at request and final approval including repeat requests",
                "Missing input before preflight records failed ownership and permits retry",
                "Required source/status/allowed-use/operations and observation lineage fail closed",
                "Common Issue7 entry invokes the separately admitted national candidate"],
            independent_review_still_required=True,scientific_limits=["Already-seen evaluation reused for disclosed model revisions",
                "No same-scope emissions holdout", "PEO/nonfossil and process/sink bridges conditional",
                "Representative day does not validate annual reliability", "Not all-GHG neutrality",
                "Aggregate grid and finance parameters are explicit research assumptions; no independent national mechanism certification"])
    except Exception as exc:
        report.update(status="failed",error=f"{type(exc).__name__}: {exc}")
    finally:
        report.pop("running_check",None)
        report["elapsed_seconds"]=time.perf_counter()-start
        report["current_hashes"]={p:sha(ROOT/p) for p in CODE+INPUTS+["tests/test_q2_national.py","scripts/review_q2_national_delivery.py"]}
        dump(out/"verification.json",report)
    print(json.dumps(dict(passed=report["passed"],status=report["status"],checks=len(report["checks"]),error=report.get("error")),ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
