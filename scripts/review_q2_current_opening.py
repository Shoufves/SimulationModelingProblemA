"""Verify the independent current-state factory and three forward openings."""
from datetime import datetime,timezone
from hashlib import sha256
from math import fsum
from pathlib import Path
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
from run_q2_national import preflight
from q2_current_factory import build
from energy_model.q2_forward_current import activate_forward


def main():
    source=ROOT/"outputs/q2_revenue_recalibration/20261020T001729054583Z"
    config=json.loads((source/"design.json").read_text("utf-8"))
    parameters=json.loads((source/"training_selection.json").read_text("utf-8"))["scenarios"]["25"]["parameters"]
    data,design,_=preflight()
    paths=["scripts/q2_current_factory.py","tests/test_q2_current_factory.py",
           "docs/sources/q2_current_initial_state.md","src/energy_model/q2_forward_current.py"]
    hashes={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    result=subprocess.run([sys.executable,"-B","-m","unittest","discover",
        "-s","tests","-p","test_q2_current_factory.py"],cwd=ROOT,capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    cases={}
    for name,variant in {
        "base":{},
        "low_debt_no_queue":{"opening_debt_asset_ratio":.3,"future_initial_pipeline_multiplier":0},
        "older_high_debt":{"initial_age_multiplier":1.2,"opening_debt_asset_ratio":.7,
                            "opening_subsidy_arrears_multiplier":1.5}}.items():
        m,assumptions,sources=build(data,design,config,parameters,25,opening_variant=variant)
        initial=dict(capacities_mw=m.initial_capacities,opening=m.opening_balance_sheet,
            fund_cash_cny=m.revenue_policy.fund.cash,
            fund_arrears_cny=fsum(c.amount_cny for c in m.revenue_policy.fund.payables),
            construction_escrow_cny=m.construction_fund,
            support_positions=len(m.revenue_policy.positions),
            retained_lifetime_mwh=fsum(p["prior_lifetime_mwh"] for p in m.revenue_policy.positions))
        activate_forward(m,config,{"name":name},end_year=2027)
        m.run(2027)
        for row in m.paths:
            for key in ("cash_balance_residual_cny","construction_fund_residual_cny",
                        "financing_transfer_residual_cny"):
                assert abs(row[key])<.1,(name,row["year"],key,row[key])
            assert abs(row["max_residual"])<1e-4
        cases[name]=dict(initial=initial,assumptions=assumptions,paths=m.paths,
            subsidy_replay=m.opening_subsidy_replay,
            opening_debt_serviced=any(f["kind"]=="debt_service" and f["project"].startswith("opening/2024/")
                                     for f in m.finance),
            sources=sources)
        assert cases[name]["opening_debt_serviced"]
    assert cases["base"]["initial"]["capacities_mw"]==cases["low_debt_no_queue"]["initial"]["capacities_mw"]
    assert hashes=={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    receipt=dict(status="passed_conditional_current_opening",created_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=hashes,tests=result.stderr,cases=cases,
        limits=["financial openings and thermal subtypes are disclosed reconstruction priors",
                "exact 2024 opening match does not validate historical fit",
                "inactive thermal remainder is not productive coal",
                "unconsolidated grid/consumer/supplemental finance retains existing model assumptions"])
    out=ROOT/"outputs/validation/current_opening_review_20261020.json"
    out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")
    print(out)


if __name__=="__main__":main()
