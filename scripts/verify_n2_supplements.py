"""Check supplementary comparators, fixed-pipeline invariants and reproduction."""
from pathlib import Path
import json
import sys
import hashlib
import argparse
from summarize_n2_research import compare
from verify_n2_research import dominates

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'tmp/n2'


def read(path):return json.loads(path.read_text('utf-8'))
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser();p.add_argument('--primary',default='r9');p.add_argument('--fixed',default='r9_fixed');p.add_argument('--reproduction',default='r9_reproduction');args=p.parse_args()
    primary=BASE/args.primary;fixed_folder=BASE/args.fixed;repro_folder=BASE/args.reproduction
    r5=read(primary/'acceptance.json');protocol=read(primary/'protocol.json')
    rows=[]
    for c in protocol['conditions']:
        name=c['id'];a=read(primary/name/(name+'__anchored_guard.json'))
        controls={rule:read(primary/name/(name+'__'+rule+'.json')) for rule in protocol['rules'] if rule!='anchored_guard'}
        controls.update({rule:read(BASE/'r7'/name/(name+'__'+rule+'.json')) for rule in ['cost_order','capacity_ready','paired_myopic','paired_guard']})
        for rule,b in controls.items():
            if a['condition']!=b['condition']:raise ValueError('Mismatched comparator condition')
        candidate_vectors={}
        for y in a['services']:
            for s,v in y['services'].items():candidate_vectors[y['year'],s]=v['requested']
        for b in controls.values():
            for y in b['services']:
                for s,v in y['services'].items():
                    q=candidate_vectors[y['year'],s]
                    if abs(q-v['requested'])>max(1e-4,abs(q)*1e-10):raise ValueError('Service demand boundary changed across rules')
        # Physical trajectory grouping does not pretend to establish statistical
        # independence; finance-only variants can share the same dispatch.
        signature=[]
        for p in a['paths']:
            signature.append({k:round(v,3) if type(v) in (int,float) else v for k,v in p.items()
                if k=='year' or k.endswith('_capacity_mw') or k.endswith('_generation_mwh') or k=='positive_co2_t'})
        signature.extend({s:round(v['fraction'],9) for s,v in y['services'].items()} for y in a['services'])
        rows.append(dict(condition=name,dominated_by=[r for r,b in controls.items() if dominates(b,a)],
                         comparisons=[compare(a,b) for b in controls.values()],
                         physical_signature=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()))
    extended=dict(conditions=rows,nondominated=sum(not r['dominated_by'] for r in rows),
                  distinct_physical_trajectories=len({r['physical_signature'] for r in rows}),
                  required_nondominated=protocol['acceptance']['minimum_nondominated_conditions_against_all_controls'])
    extended['passed']=extended['nondominated']>=extended['required_nondominated']
    save(primary/'extended_comparison.json',extended)
    fixed=[]
    for p in sorted(fixed_folder.glob('*__*.json')):
        r=read(p)
        if r['summary']['generation_approved_cny']!=0 or r['summary']['infrastructure_approved_cny']!=0:
            raise ValueError('New investment leaked into fixed-pipeline ablation')
        if any(abs(x['max_residual'])>1e-6 or abs(x['construction_fund_residual_cny'])>.1 for x in r['paths']):
            raise ValueError('Fixed-pipeline conservation failure')
        fixed.append(dict(name=r['name'],new_generation_approved_cny=0,new_infrastructure_approved_cny=0,
                          maximum_service_fraction=r['summary']['maximum_service_fraction']))
    save(fixed_folder/'fixed_invariants.json',dict(passed=True,cases=fixed))
    pin=ROOT/'tmp/n2/pr14'
    sys.path[:0]=[str(pin/'scripts'),str(pin/'src')]
    from run_q2_portable import compare_reference
    a=read(primary/'W08_compound/W08_compound__anchored_guard.json')
    b=read(repro_folder/'W08_compound__anchored_guard.json')
    reproduction=compare_reference(a,b)
    save(repro_folder/'reproduction.json',reproduction)
    tests=read(BASE/'research_tests.json');legacy=read(BASE/'legacy_tests.json')
    result=dict(primary_protocol=args.primary,primary_gate_passed=r5['n2_empirical_gate_passed'],extended_comparison_passed=extended['passed'],
        distinct_physical_trajectories=extended['distinct_physical_trajectories'],reproduction_passed=reproduction['passed'],
        fixed_invariants_passed=True,implementation_tests_passed=tests['passed'],legacy_tests_passed=legacy['passed'],
        tests_run=tests['tests']+legacy['tests'],human_review='pending',n3_supported=False,
        system_hard_service_limit_passed_conditions=r5['counts']['hard_service_limit_passed'])
    result['n2_internal_empirical_candidate']=all(result[k] for k in ['primary_gate_passed','extended_comparison_passed','reproduction_passed','fixed_invariants_passed','implementation_tests_passed','legacy_tests_passed'])
    result['verifier_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['scripts/verify_n2_supplements.py','scripts/verify_n2_research.py','scripts/summarize_n2_research.py']}
    save(BASE/'final_acceptance.json',result)
    save(primary/'final_acceptance.json',result)
    print(json.dumps(result,indent=2))
    return 0 if result['n2_internal_empirical_candidate'] else 1


if __name__=='__main__':raise SystemExit(main())
