"""Reproduce the PR13 review case without changing any frozen model parameters."""
import json
from pathlib import Path
from run_q3 import ROOT, preflight, dump, sha
from energy_model.q3_transition import TransitionModel, annual_metrics


def probe():
    c,data,design,theta,_=preflight(ROOT/'workflow/q3_inputs.json')
    results=[]
    for rule,end in (('cost_order',2029),('schedule',2028)):
        model=TransitionModel(data,design,theta,c,h01=dict(vR=.02,vE=.25,delay=0,rule=rule)).run(end)
        exits=[r for r in model.retirement_log if r['action']!='decision']
        strict=sum(r['capacity_mw'] for r in exits if r['year']<r['natural_exit'])
        natural=sum(r['capacity_mw'] for r in exits if r['year']==r['natural_exit'])
        metrics=annual_metrics(model)
        ok=abs(strict-metrics['retired_early_mw'])<.0001 and all(r['action']==('early_retired' if r['year']<r['natural_exit'] else 'natural_retired') for r in exits)
        if rule=='cost_order':ok=ok and strict==0 and natural>0
        else:ok=ok and strict>0 and natural==0
        results.append(dict(rule=rule,end_year=end,passed=ok,reported_early_mw=metrics['retired_early_mw'],
            recomputed_strict_early_mw=strict,recomputed_managed_natural_mw=natural,exits=exits))
    return dict(passed=all(r['passed'] for r in results),cases=results,
        config_sha256=sha(ROOT/'workflow/q3_inputs.json'),model_sha256=sha(ROOT/'src/energy_model/q3_transition.py'))


if __name__=='__main__':
    result=probe();dump(ROOT/'outputs/q3_review/retirement_probe.json',result)
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['passed'] else 1)
