"""Verify parser-cache isolation against full uncached candidate trajectories."""
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"scripts"),str(ROOT/"src")]
from q2_competition_factory import build
from q2_corrected_factory import preflight,save,sha,training_loss
from q2_verified_input_cache import install
import run_q2_empirical_support as empirical
import build_q2_project_costs as costs


def main():
    base = ROOT/"outputs/q2_revenue_recalibration/20261019T225922280430Z"
    pairs = ROOT/"outputs/q2_project_competition_pairs/20261020T000557617231Z"
    sources = dict(json.loads((pairs/"results.json").read_text("utf-8"))["source_sha256"])
    for p in ("scripts/q2_verified_input_cache.py",Path(__file__).relative_to(ROOT).as_posix()):
        sources[p] = sha(p)
    d,s,_ = preflight()
    config = json.loads((base/"design.json").read_text("utf-8"))
    params = json.loads((base/"training_selection.json").read_text("utf-8"))["scenarios"]["25"]["parameters"]
    start = perf_counter()
    original,*_ = build(d,s,config,params,25,end_year=2024)
    uncached = perf_counter()-start
    restore = install(sources)
    times = []
    try:
        for i in range(2):
            start = perf_counter()
            current,*_ = build(d,s,config,params,25,end_year=2024)
            times.append(perf_counter()-start)
            for field in ("paths","finance","behavior","operations","projects","assets","balances",
                          "thermal_fuel_ledger","project_forecasts","project_operation_accounts"):
                if getattr(current,field)!=getattr(original,field):
                    raise ValueError("Cached build differs: "+field)
            if current.year_end_operation()!=original.year_end_operation() or training_loss(current)!=training_loss(original):
                raise ValueError("Cached state or score differs")
            # Simulate a consumer mutating a returned parsed value. Cached
            # originals and the next full model must remain unaffected.
            fiscal = empirical.fiscal_observations()
            fiscal[next(iter(fiscal))]["actual"] = "99999999999999"
            cost = costs.extract()
            cost["parameters"]["coal"]["fixed_usd_2018_per_net_mw_year"] = 0.
        if costs.extract()["parameters"]["coal"]["fixed_usd_2018_per_net_mw_year"]<=0:
            raise ValueError("Cached cost was mutated")
    finally:
        restore()
    if any(sha(p)!=h for p,h in sources.items()):
        raise ValueError("Review sources changed")
    result = dict(status="passed",reviewed_at=datetime.now(timezone.utc).isoformat(),
        full_2015_2024_fields_and_scores_exact=True,mutable_returns_isolated=True,
        uncached_seconds=uncached,cached_first_seconds=times[0],cached_repeat_seconds=times[1],
        source_sha256=sources,scope="Worker-local pure evidence readers only; no parameters or state cached")
    path = ROOT/"outputs/validation/project_input_cache_review_20261020.json"
    save(path,result)
    print(json.dumps({k:v for k,v in result.items() if k!="source_sha256"}))


if __name__=="__main__":
    main()
