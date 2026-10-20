"""Deterministic H01 grids and finite, constrained policy experiments.

Selection is written before the test set is evaluated. A model failure is saved
with its partial ledgers and is never assigned a zero shortage or zero cost.
"""
from copy import deepcopy
import gzip
import hashlib
import json
from math import fsum, isfinite
from pathlib import Path
import time

from run_q2_national import dump, csv_write
from energy_model.q2_operations import Q2Error, number
from energy_model.q3_transition import TransitionModel, RULES, service_totals
from energy_model.q3_events import run_event, safety_metrics


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def save_detail(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(content,ensure_ascii=False,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode(),mtime=0))


def validate_protocol(config):
    t,p = config["transition"],config["policy"]
    for key in ("fixed_vR","fixed_vE","annual_retention_cost_fraction",
                "annual_public_asset_maintenance_fraction","public_budget_fraction_gdp","public_project_power_fraction","channel_fraction"):
        number(t[key],key,0,1)
    for key in ("vR","vE","epsilon_candidates"):
        if not t[key] or len(t[key])!=len(set(t[key])):raise Q2Error("invalid_input","Empty/duplicate grid "+key)
        for value in t[key]:number(value,key,0,1)
    for key in ("early_exit_window_years","information_horizon_years","gas_release_lead_years","gas_release_lifetime_years"):
        if type(t[key]) is not int or t[key]<1:raise Q2Error("invalid_input","Non-positive integer "+key)
    if any(type(v) is not int or v<0 for v in t["delay_years"]):raise Q2Error("invalid_input","Invalid delays")
    if t["rules"]!=list(RULES) or t["modes"]!=["full_response","fixed_projects"]:
        raise Q2Error("invalid_input","All H01 controls and experiment modes required")
    if t["evaluation_years"]!=[2030,2060]:raise Q2Error("invalid_input","Both evaluation nodes required")
    number(t["gas_release_capex_cny_per_mw"],"gas release capex",1)
    ids = [c["id"] for c in p["candidates"]]
    if len(ids)!=len(set(ids)) or "none" not in ids:raise Q2Error("invalid_input","Missing/duplicate policy comparator")
    for c in p["candidates"]:
        if c["rule"] not in RULES or set(c["actions"])-{"grid","storage","gas_release"}:
            raise Q2Error("invalid_input","Unknown candidate intervention")
    for key in ("carbon_limit_ratio","gross_cost_limit_ratio","service_limit"):
        number(p[key],key,0)
    if t["fixed_vR"] not in t["vR"] or t["fixed_vE"] not in t["vE"]:
        raise Q2Error("invalid_input","Fixed grid anchors must be explicit tested values")
    for s in config["sensitivity"]:
        if s["target"] not in {"transition.annual_retention_cost_fraction","transition.public_budget_fraction_gdp","transition.gas_release_capex_cny_per_mw"}:
            raise Q2Error("invalid_input","Unimplemented sensitivity")
        number(s["multiplier"],"sensitivity multiplier",1e-9)


def h01_cells(t):
    cells = {}
    for vR in t["vR"]:
        for delay in t["delay_years"]:
            cells.setdefault((vR,t["fixed_vE"],delay),[]).append("vR_x_L")
    for vE in t["vE"]:
        for delay in t["delay_years"]:
            cells.setdefault((t["fixed_vR"],vE,delay),[]).append("vE_x_L")
    return [dict(vR=a,vE=b,delay=c,grids=";".join(v)) for (a,b,c),v in cells.items()]


def dominates(a,b):
    keys=("worst_selection_service_fraction","net_resource_cost_cny","cumulative_combustion_co2_t")
    # Scale-aware tie band prevents solver roundoff from fabricating superiority.
    tol = lambda k:max(1e-10,1e-9*max(abs(a[k]),abs(b[k])))
    return all(a[k]<=b[k]+tol(k) for k in keys) and any(a[k]<b[k]-tol(k) for k in keys)


def screen(rows, policy, *, carbon_ratio=None, cost_ratio=None):
    baseline = next(r for r in rows if r["policy_id"]=="none")
    carbon_ratio = policy["carbon_limit_ratio"] if carbon_ratio is None else carbon_ratio
    cost_ratio = policy["gross_cost_limit_ratio"] if cost_ratio is None else cost_ratio
    if baseline["status"]!="completed":
        return dict(selected=None,feasible=[],pareto=[],reason="baseline_failed",records=[])
    records=[]
    for r in rows:
        reasons=[]
        if r["status"]!="completed":reasons.append(r["status"])
        else:
            if r["cumulative_combustion_co2_t"]>baseline["cumulative_combustion_co2_t"]*carbon_ratio+1e-5:reasons.append("carbon")
            if r["discounted_resource_cost_cny"]>baseline["discounted_resource_cost_cny"]*cost_ratio+.01:reasons.append("cost")
            if max(r["worst_selection_service_fraction"],r["worst_annual_service_fraction"])>policy["service_limit"]+1e-10:reasons.append("service")
        records.append(dict(policy_id=r["policy_id"],feasible=not reasons,violations=";".join(reasons)))
    valid=[r for r in rows if next(z["feasible"] for z in records if z["policy_id"]==r["policy_id"])]
    frontier=[r for r in valid if not any(dominates(other,r) for other in valid)]
    selected=min(frontier,key=lambda r:(round(r["worst_selection_service_fraction"],10),r["net_resource_cost_cny"],r["cumulative_combustion_co2_t"],r["policy_id"])) if frontier else None
    return dict(selected=selected["policy_id"] if selected else None,feasible=[r["policy_id"] for r in valid],
                pareto=[r["policy_id"] for r in frontier],reason="feasible_finite_choice" if selected else "no_feasible_candidate",
                carbon_ratio=carbon_ratio,cost_ratio=cost_ratio,records=records)


def model_evidence(model):
    return dict(paths=model.paths,annual_services=model.annual_services,operations=model.operations,
        finance=model.finance,public_ledger=model.public_ledger,projects=model.projects,
        infrastructure=model.grid.queue,policy_projects=model.policy_queue,
        devices={c.name:c.queue for c in model.consumers.values()},
        terminal_cohorts=model.cohorts,terminal_device_cohorts={c.name:c.cohorts for c in model.consumers.values()},
        terminal_grid=model.grid.network,terminal_storage=model.storage_cohorts,
        operation_specs=model.operation_specs,
        decisions=model.decisions,forecasts=model.forecasts,applications=model.application_log,
        snapshots=model.snapshot_states,solver_stages=model.stages,balances=model.balances)


class Campaign:
    def __init__(self, config, data, design, theta, out):
        self.config,self.data,self.design,self.theta,self.out=config,data,design,theta,out
        self.cases,self.events,self.timings,self.failures=[],[],[],[]
        self.count=0
        self.records={}
        self.event_cache={}
        self.event_cache_hits=0
        self.event_computations=0

    def annual(self, label, config=None, fixed_plan=None):
        config = self.config if config is None else config
        self.count+=1
        if self.count>self.config["compute_budget"]["max_transition_annual_runs"]:
            raise Q2Error("compute_budget","Frozen annual experiment count exceeded")
        print(f"Q3 transition {self.count}: {label['id']}",flush=True)
        start=time.perf_counter()
        row={**label,"status":"running"}
        model=None
        evidence=dict(label=label,config_sha256=digest(config),fixed_plan_sha256=digest(fixed_plan) if fixed_plan is not None else None)
        try:
            model=TransitionModel(self.data,self.design,self.theta,config,vR=label["vR"],vE=label["vE"],
                delay=label["delay"],rule=label["rule"],epsilon=label["epsilon"],fixed_plan=fixed_plan,actions=label.get("actions",()))
            model.run(config["end_year"])
            row.update(status="completed",**model.terminal_accounts())
            evidence["terminal_accounts"]=model.terminal_accounts()
            plan=model.export_plan()
            if fixed_plan is not None and digest(plan)!=digest(fixed_plan):
                # Status/remaining are final values on both sides. Exact equality
                # includes quantities, timing, device mix, costs and funding.
                raise Q2Error("fixed_set_mismatch","Replayed project set changed")
            row["capital_plan_sha256"]=digest(plan)
        except Exception as exc:
            status=getattr(exc,"status","error")
            row.update(status="failed",failure_kind=status,error=type(exc).__name__+": "+str(exc))
            self.failures.append(dict(id=label["id"],status=status,error=row["error"],
                expected_protocol_failure=status=="fixed_schedule_infeasible"))
            # Do not emit partial costs as a valid whole-horizon comparison.
            for key in list(row):
                if key in ("terminal_asset_value_cny","discounted_resource_cost_cny","net_resource_cost_cny","cumulative_combustion_co2_t","worst_annual_service_fraction"):
                    row.pop(key)
        if model is not None:evidence.update(model_evidence(model))
        evidence["outcome"]=row
        save_detail(self.out/"cases"/(label["id"]+".json.gz"),evidence)
        # The complete evidence is already on disk. Retain only the cloned
        # event states; avoid keeping every historical debt entry in memory.
        self.records[label["id"]]={"snapshots":evidence.get("snapshots",{})}
        self.timings.append(dict(id=label["id"],seconds=time.perf_counter()-start,status=row["status"]))
        self.cases.append(row)
        csv_write(self.out/"transition_case_status.csv",self.cases)
        dump(self.out/"transition_progress.json",dict(annual_runs=self.count,failures=self.failures,timings=self.timings))
        return row,model.export_plan() if model is not None and row["status"]=="completed" else None

    def evaluate(self, row, split, scenarios=("S0","SGW")):
        if row["status"]!="completed":return
        config=self.config
        snapshots=self.records[row["id"]]["snapshots"]
        selected=[e for e in config["events"] if e["split"]==split]
        detail=[]
        for event in selected:
            for year,op in sorted(snapshots.items()):
                for scenario in scenarios:
                    try:
                        key=digest(dict(operation=op,event=event,scenario=scenario,fraction=config["transition"]["channel_fraction"]))
                        if key in self.event_cache:
                            run=json.loads(gzip.decompress(self.event_cache[key]))
                            self.event_cache_hits+=1
                        else:
                            run=run_event(op,event,scenario,config["transition"]["channel_fraction"])
                            self.event_cache[key]=gzip.compress(json.dumps(run,sort_keys=True,separators=(",",":"),allow_nan=False).encode(),mtime=0)
                            self.event_computations+=1
                        metrics=safety_metrics(run,relative_tolerance=config["safety"]["relative_shortage_tolerance"],
                            absolute_tolerance=config["safety"]["absolute_shortage_tolerance_mwh"],recovery_periods=config["safety"]["recovery_periods"])
                    except Exception as exc:
                        failure=dict(id=row["id"],split=split,event=event["id"],year=year,scenario=scenario,
                                     error=type(exc).__name__+": "+str(exc),status=getattr(exc,"status","error"),expected_protocol_failure=False)
                        self.failures.append(failure)
                        row["status"]="event_failed"
                        save_detail(self.out/"events"/(row["id"]+"-"+split+".json.gz"),dict(completed=detail,failure=failure))
                        return
                    for r in metrics:
                        self.events.append(dict(id=row["id"],family=row["family"],event=event["id"],year=year,split=split,scenario=scenario,**r))
                    detail.append(dict(event=event["id"],year=year,scenario=scenario,**run))
        save_detail(self.out/"events"/(row["id"]+"-"+split+".json.gz"),detail)
        row["worst_"+split+"_service_fraction"]=max(r["unmet_fraction"] or 0 for r in self.events if r["id"]==row["id"] and r["split"]==split)

    def run(self):
        t=self.config["transition"]
        h01=[]
        for index,cell in enumerate(h01_cells(t)):
            variants=[(r,.01) for r in RULES if r!="anticipatory"]+[("anticipatory",e) for e in t["epsilon_candidates"]]
            reference=None
            for mode in t["modes"]:
                for rule,epsilon in variants:
                    label=dict(id=f"h01_{index}_{mode}_{rule}_{epsilon:g}",family="h01",mode=mode,**cell,rule=rule,epsilon=epsilon)
                    if mode=="fixed_projects" and reference is None:
                        raise Q2Error("missing_comparator","Cannot construct a fixed project set from a failed reference")
                    row,plan=self.annual(label,fixed_plan=reference if mode=="fixed_projects" else None)
                    if mode=="full_response" and rule=="fixed_schedule":reference=plan
                    h01.append(row)
            dump(self.out/"plans"/f"h01_cell_{index}.json",reference)
        # Test data are not evaluated before all selection artefacts are frozen.
        for row in h01:self.evaluate(row,"selection")
        epsilon_scores=[]
        for e in t["epsilon_candidates"]:
            rows=[r for r in h01 if r["mode"]=="full_response" and r["rule"]=="anticipatory" and r["epsilon"]==e]
            valid=all(r["status"]=="completed" for r in rows)
            violations=[]
            for row in rows:
                reference=next(r for r in h01 if r["mode"]=="full_response" and r["rule"]=="fixed_schedule" and
                    (r["vR"],r["vE"],r["delay"])==(row["vR"],row["vE"],row["delay"]))
                if row["status"]!="completed" or reference["status"]!="completed":violations.append(row["id"]+":failed");continue
                p=self.config["policy"]
                if max(row["worst_selection_service_fraction"],row["worst_annual_service_fraction"])>p["service_limit"]+1e-10:violations.append(row["id"]+":service")
                if row["cumulative_combustion_co2_t"]>reference["cumulative_combustion_co2_t"]*p["carbon_limit_ratio"]+1e-5:violations.append(row["id"]+":carbon")
                if row["discounted_resource_cost_cny"]>reference["discounted_resource_cost_cny"]*p["gross_cost_limit_ratio"]+.01:violations.append(row["id"]+":cost")
            epsilon_scores.append(dict(epsilon=e,valid=valid,admissible=valid and not violations,violations=violations,
                worst_selection_service_fraction=max(r["worst_selection_service_fraction"] for r in rows) if valid else None,
                net_resource_cost_cny=fsum(r["net_resource_cost_cny"] for r in rows) if valid else None))
        eligible=[r for r in epsilon_scores if r["admissible"]]
        eps=min(eligible,key=lambda r:(round(r["worst_selection_service_fraction"],10),r["net_resource_cost_cny"],r["epsilon"]))["epsilon"] if eligible else None
        policy=[]
        for candidate in self.config["policy"]["candidates"]:
            label=dict(id="policy_"+candidate["id"],policy_id=candidate["id"],family="policy",mode="full_response",
                vR=t["fixed_vR"],vE=t["fixed_vE"],delay=0,epsilon=.01,rule=candidate["rule"],actions=candidate["actions"])
            row,_=self.annual(label)
            self.evaluate(row,"selection",("S0","SG","SW","SGW"))
            policy.append(row)
        decision=screen(policy,self.config["policy"])
        lock=dict(status="selection_locked_before_test_evaluation",protocol_sha256=digest(self.config),
                  h01_epsilon=eps,h01_status="feasible_threshold" if eligible else "no_feasible_common_threshold",
                  h01_scores=epsilon_scores,policy=decision,
                  selection_records_sha256=digest([r for r in self.events if r["split"]=="selection"]),
                  test_identity=self.config["test_identity"])
        dump(self.out/"selection_lock.json",lock)
        lock_sha=digest(lock)
        for row in h01:self.evaluate(row,"test")
        for row in policy:self.evaluate(row,"test",("S0","SG","SW","SGW"))
        tradeoffs=[]
        for carbon in self.config["policy"]["tradeoff_carbon_ratios"]:
            for cost in self.config["policy"]["tradeoff_cost_ratios"]:
                tradeoffs.append(screen(policy,self.config["policy"],carbon_ratio=carbon,cost_ratio=cost))
        dump(self.out/"policy_tradeoffs.json",dict(designated=decision,alternative_bounds=tradeoffs,
            warning="Alternative bounds are sensitivity results, never a relaxation of the designated acceptance criteria"))
        sensitivity=[]
        sensitivity_rankings=[]
        for s in self.config["sensitivity"]:
            config=deepcopy(self.config)
            group,key=s["target"].split(".")
            config[group][key]*=s["multiplier"]
            rows=[]
            for candidate in config["policy"]["candidates"]:
                label=dict(id=s["id"]+"_"+candidate["id"],policy_id=candidate["id"],family="sensitivity",mode="full_response",
                    sensitivity=s["id"],parameter=s["target"],multiplier=s["multiplier"],vR=t["fixed_vR"],vE=t["fixed_vE"],
                    delay=0,epsilon=.01,rule=candidate["rule"],actions=candidate["actions"])
                row,_=self.annual(label,config=config)
                self.evaluate(row,"selection",("S0","SG","SW","SGW"))
                rows.append(row)
            chosen=screen(rows,config["policy"])
            # Same information split within each single-factor robustness run.
            dump(self.out/"sensitivity_locks"/(s["id"]+".json"),dict(protocol_change=s,decision=chosen))
            for row in rows:self.evaluate(row,"test",("S0","SG","SW","SGW"))
            sensitivity.extend(rows)
            sensitivity_rankings.append(dict(**s,selected=chosen["selected"],reason=chosen["reason"],pareto=";".join(chosen["pareto"]),
                same_selected_as_primary=chosen["selected"]==decision["selected"]))
        if digest(json.loads((self.out/"selection_lock.json").read_text(encoding="utf-8")))!=lock_sha:
            raise Q2Error("selection_changed","Selection changed after test exposure")
        comparisons=[]
        for row in h01:
            baseline=next(r for r in h01 if r["mode"]==row["mode"] and r["vR"]==row["vR"] and r["vE"]==row["vE"] and r["delay"]==row["delay"] and r["rule"]=="fixed_schedule")
            result=dict(id=row["id"],reference=baseline["id"],mode=row["mode"],rule=row["rule"],status=row["status"],grids=row["grids"])
            if row["status"]==baseline["status"]=="completed":
                for key in ("net_resource_cost_cny","cumulative_combustion_co2_t","terminal_asset_value_cny","worst_annual_service_fraction","worst_selection_service_fraction","worst_test_service_fraction"):
                    result["delta_"+key]=row[key]-baseline[key]
                result["fixed_capital_set_equal"]=row["capital_plan_sha256"]==baseline["capital_plan_sha256"]
            comparisons.append(result)
        for name,rows in (("h01_results",h01),("h01_comparisons",comparisons),("policy_results",policy),
                          ("sensitivity_results",sensitivity),("sensitivity_rankings",sensitivity_rankings),
                          ("transition_event_metrics",self.events),("transition_case_status",self.cases)):
            csv_write(self.out/(name+".csv"),rows)
        dump(self.out/"transition_failures.json",self.failures)
        dump(self.out/"transition_timing.json",dict(annual_runs=self.count,timings=self.timings,
            event_computations=self.event_computations,event_cache_hits=self.event_cache_hits,
            cache_identity="in-memory current-run exact full-operation/event/scenario hash; no reuse across code revisions"))
        unexpected=[f for f in self.failures if not f["expected_protocol_failure"]]
        complete=dict(experiments_completed=not unexpected,annual_runs=self.count,h01_cases=len(h01),policy_cases=len(policy),
            sensitivity_cases=len(sensitivity),fixed_project_failures=len(self.failures)-len(unexpected),
            unexpected_failures=len(unexpected),selected_policy=decision["selected"],selected_epsilon=eps,
            designated_policy_status=decision["reason"],team_approved=False)
        dump(self.out/"transition_completion.json",complete)
        return complete


def run_campaign(config,data,design,theta,out):
    validate_protocol(config)
    (out/"plans").mkdir(exist_ok=True)
    (out/"sensitivity_locks").mkdir(exist_ok=True)
    return Campaign(config,data,design,theta,out).run()
