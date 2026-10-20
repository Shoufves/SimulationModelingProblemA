"""Run declared conditional research against isolated, hash-checked PR14."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import platform
import importlib.metadata

ROOT=Path(__file__).resolve().parents[1]
PIN=ROOT/'tmp/n2/pr14'
sys.path[:0]=[str(PIN/'src'),str(PIN/'scripts'),str(ROOT/'src')]
from q2_delivery_snapshot import load,decode,build_snapshot
from energy_model.q2_forward_current import activate_forward,forward_summary
from transition_research.retirement import activate,RULES


def save(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    protocol=load(ROOT/args.protocol)
    if len({c['id'] for c in protocol['conditions']}) != len(protocol['conditions']):
        raise ValueError('Duplicate condition identifiers')
    if len(set(protocol['rules']))!=len(protocol['rules']) or set(protocol['rules'])-set(RULES):
        raise ValueError('Duplicate or unknown rule')
    dest=ROOT/args.output;dest.mkdir(parents=True,exist_ok=False)
    manifest=load(PIN/'data/processed/q2_delivery/manifest.json')
    for name,h in manifest['code_sha256'].items():
        if hashlib.sha256((PIN/name).read_bytes()).hexdigest()!=h:
            raise ValueError('Upstream code changed: '+name)
    raw=load(PIN/'data/processed/q2_delivery/parsed_inputs.json')
    for name,key in [('parsed_inputs.json','inputs_sha256'),('q2_design.json','design_sha256')]:
        if hashlib.sha256((PIN/'data/processed/q2_delivery'/name).read_bytes()).hexdigest()!=manifest[key]:
            raise ValueError('Input changed: '+name)
    save(dest/'protocol.json',protocol)
    metadata=dict(baseline_commit='1b8f465783afe7505c8d4e65ec43ada18c311daf',
                  raw_originals_reverified=False,files={},python=sys.version,platform=platform.platform(),
                  dependencies={name:importlib.metadata.version(name) for name in ('mesa','numpy','scipy')},
                  upstream_manifest_sha256=hashlib.sha256((PIN/'data/processed/q2_delivery/manifest.json').read_bytes()).hexdigest())
    for name in [args.protocol,'scripts/run_n2_research.py','src/transition_research/retirement.py']:
        metadata['files'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        (dest/Path(name).name).write_bytes((ROOT/name).read_bytes())
    save(dest/'provenance.json',metadata)
    results=[]
    for condition in protocol['conditions']:
        for rule in protocol['rules']:
            t=time.perf_counter()
            name=condition['id']+'__'+rule
            record=decode(raw[condition.get('record','net58/25')])
            authority=int(condition.get('record','net58/25').split('/')[1])
            model,assumptions,_=build_snapshot(record,authority,condition.get('opening',{}))
            activate_forward(model,record['config'],dict(name=name,kind='research',**condition.get('scenario',{})),end_year=protocol['end_year'])
            activate(model,rule=rule,**protocol['method'],acceleration=condition['acceleration'])
            print('START',name,flush=True)
            try:
                model.run(protocol['end_year'])
            except Exception as exc:
                save(dest/'failure.json',dict(status='failed',case=name,error_type=type(exc).__name__,message=str(exc),
                    finished_cases=[r['name'] for r in results],year=model.year))
                raise
            summary=forward_summary(model)
            summary.update(maximum_service_fraction=max(v['fraction'] for y in model.research_services for v in y['services'].values()),
                retention_mw_year=sum(d['deferred_mw'] for d in model.research_decisions),
                retention_fee_cny=sum(d['fee_cny'] for d in model.research_decisions),
                forecast_solves=model.research_solves,
                forecast_count_unit=('annual_rollout_years_not_total_lp_solves' if rule=='rollout_guard' else 'dispatch_lp_calls'),
                final_initial_coal_mw=sum(c['capacity_mw'] for c in model.cohorts if c.get('research_due') and c['status']=='active'))
            result=dict(name=name,condition=condition,rule=rule,summary=summary,paths=model.paths,
                services=model.research_services,decisions=model.research_decisions,
                terminal_cohorts=model.cohorts,assumptions=assumptions)
            save(dest/(name+'.json'),result)
            brief=dict(name=name,**summary,elapsed_seconds=time.perf_counter()-t)
            results.append(brief);save(dest/'summary.json',results)
            print(name, 'cost_T',round(summary['discounted_resource_cost_cny']/1e12,6),
                  'retention_MWyr',round(summary['retention_mw_year']),
                  'seconds',round(brief['elapsed_seconds'],2),flush=True)
    save(dest/'completion.json',dict(status='completed_not_scientific_acceptance',runs=len(results)))


if __name__=='__main__':main()
