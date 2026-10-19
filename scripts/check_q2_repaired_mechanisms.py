"""Export actual post-repair counterexamples, independently of unit-test receipts."""
import csv
import json
from pathlib import Path

from run_q2_national import preflight,verify_latest,sha
from energy_model.q2_national import NationalModel

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/"outputs/q2/p2_lb_national"
    manifest=verify_latest(folder)
    data,design,_=preflight()
    theta=json.loads((folder/"calibration.json").read_text(encoding="utf-8"))["best"]["parameters"]
    models=[NationalModel(data,design,theta,2024) for _ in range(2)]
    projects=[]
    for m,cash in zip(models,(1e15,-1e15)):
        for g in m.generators.values():g.cash=cash
        m.step()
        projects.append([p for p in m.projects if not p["initial_reconstruction"]])
    approved=[sum(p["capacity_mw"] for p in v) for v in projects]
    assert approved[0]>0 and approved[1]==0
    m=NationalModel(data,design,theta,2024);m.drivers();m.mature()
    before=m.make_operation()["grid"]["power_mw"]
    m.cohorts.append(dict(tech="solar",status="active",capacity_mw=1e6))
    after=m.make_operation()["grid"]["power_mw"]
    assert before==after
    with (folder/"baseline_path.csv").open(encoding="utf-8") as f:rows=list(csv.DictReader(f))
    soc=max(abs(float(a["storage_closing_mwh"])-float(b["storage_opening_mwh"])-float(b["storage_retirement_loss_mwh"])) for a,b in zip(rows,rows[1:]))
    assert soc<1e-4
    unfunded=NationalModel(data,design,theta,2024,variant={"consumer_income_multiplier":0})
    for consumer in unfunded.consumers.values():consumer.cash=0
    unfunded.run(2025)
    demand=[r for r in unfunded.operations if r["kind"]=="demand" and r["sector"] in unfunded.consumer_by_name]
    requested=sum(r["requested_service_mwh"] for r in demand)*365
    unmet=sum(r["unmet_service_mwh"] for r in demand)*365
    served=sum(r["served_service_mwh"] for r in demand)*365
    assert requested>0 and abs(requested-unmet)<1e-3 and abs(served)<1e-3
    assert all(not c.queue for c in unfunded.consumers.values())
    finite=NationalModel(data,design,theta,2024);finite.drivers();finite.mature()
    original=finite.make_operation()["demands"]["existing_electric_services"]["input_capacity_mw"]
    finite.electric_activity*=10
    enlarged=finite.make_operation()["demands"]["existing_electric_services"]["input_capacity_mw"]
    assert original==enlarged
    with (folder/"accounts.csv").open(encoding="utf-8") as f:accounts=list(csv.DictReader(f))
    consumer_accounts=[r for r in accounts if r["kind"]=="consumer_operation" and r.get("energy_budget_cny")]
    budget_excess=max(max(0,float(r["energy_bill_cny"])-float(r["energy_budget_cny"])) for r in consumer_accounts)
    assert budget_excess<.01
    with (folder/"behavior.csv").open(encoding="utf-8") as f:behavior=list(csv.DictReader(f))
    audits=[r for r in behavior if r["kind"]=="joint_renewable_audit"]
    data_out=dict(run_id=manifest["run_id"],cash_probe_initial_cny=[1e15,-1e15],
        approved_new_generation_mw=approved,grid_increment_after_1TW_source_added_mw=after-before,
        max_cross_year_soc_residual_mwh=soc,
        max_financing_transfer_residual_cny=max(abs(float(r["financing_transfer_residual_cny"])) for r in rows),
        zero_consumer_funding=dict(requested_service_mwh=requested,served_service_mwh=served,unmet_service_mwh=unmet,
                                  new_devices=len([p for c in unfunded.consumers.values() for p in c.queue])),
        electric_device_capacity_increment_after_10x_demand_mw=enlarged-original,
        max_consumer_spending_over_budget_cny=budget_excess,
        joint_renewable_audit_rounds=len(audits),joint_renewable_rejected_rounds=sum(r["approved"]=="False" for r in audits),
        script_sha256=sha(Path(__file__)),model_hashes=manifest["code_hashes"],passed=True)
    out=ROOT/"outputs/q2_review/p2_lb_national/repaired_counterexamples.json"
    out.write_text(json.dumps(data_out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in data_out.items() if k!="model_hashes"},ensure_ascii=False))


if __name__=="__main__":main()
