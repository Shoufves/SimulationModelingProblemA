"""PR13 review-2 evidence: real LP counterexample and fresh/archived accounting."""
from copy import deepcopy
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PIN=ROOT/'tmp/n2/pr14'
sys.path[:0]=[str(PIN/'src'),str(PIN/'scripts'),str(ROOT/'src'),str(ROOT/'tests/research')]
from q2_delivery_snapshot import decode,build_snapshot
from run_q2_portable import compare_reference
from compare_n2_reproduction import compare_reproduction,cumulative_cost_tolerance
from test_pr14_retirement import feedstock_dispatch_pair
from transition_research.retirement import services


def read(path):
    blob=path.read_bytes()
    return json.loads(gzip.decompress(blob) if path.suffix=='.gz' else blob)


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='tmp/n2/pr13_review2')
    args=parser.parse_args();out=ROOT/args.root
    op,retired,keep,release=feedstock_dispatch_pair()
    before,after=services(keep),services(release)
    probe=dict(inputs=dict(retained=op,retired=retired),outputs=dict(retained=keep,retired=release),
               service_vectors=dict(retained=before,retired=after),
               old_aggregate_unmet=[sum(v['unmet'] for k,v in row.items() if k.startswith('nonenergy')) for row in (before,after)],
               gas_fraction_regret=after['nonenergy_feedstock/gas']['fraction']-before['nonenergy_feedstock/gas']['fraction'])
    probe['passed']=probe['gas_fraction_regret']==1 and probe['old_aggregate_unmet'][0]==probe['old_aggregate_unmet'][1]
    save(out/'feedstock_counterexample.json',probe)

    # Actual archived W08, with an explicitly labelled synthetic one-ULP change.
    old_w08=read(ROOT/'outputs/research_n2/r9/W08_compound/W08_compound__anchored_guard.json.gz')
    adjacent=deepcopy(old_w08)
    total=old_w08['summary']['discounted_resource_cost_cny']
    adjacent['summary']['discounted_resource_cost_cny']=math.nextafter(total,math.inf)
    one_ulp=compare_reproduction(adjacent,old_w08)
    corrupt=deepcopy(old_w08);corrupt['summary']['discounted_resource_cost_cny']=total+1.
    real_deviation=compare_reproduction(corrupt,old_w08)
    save(out/'roundoff_counterexample.json',dict(kind='deterministic_mutation_of_actual_archive_not_independent_run',
         one_ulp=one_ulp,one_cny=real_deviation,passed=one_ulp['passed'] and not real_deviation['passed']))

    raw=read(PIN/'data/processed/q2_delivery/parsed_inputs.json')
    protocol=read(out/'primary/protocol.json')
    records=[];accounting=[];material=[]
    for case in protocol['conditions']:
        key=case.get('record','net58/25')
        model,_,_=build_snapshot(decode(raw[key]),int(key.split('/')[1]),case.get('opening',{}))
        discount=model.a['discount_rate']
        for rule in protocol['rules']:
            name=case['id']+'__'+rule
            current=read(out/'primary'/case['id']/(name+'.json'))
            old=read(ROOT/'outputs/research_n2/r9'/case['id']/(name+'.json.gz'))
            # New service identities and forecast vectors intentionally differ.
            # Compare common actual paths, summary, actual choices and cohorts.
            def common(r):
                decisions=[{k:d[k] for k in ('year','rule','due','retained','deferred_mw','fee_cny','budget_cny')}
                           for d in r['decisions']]
                return dict(summary=r['summary'],paths=r['paths'],decisions=decisions,terminal_cohorts=r['terminal_cohorts'])
            comparison=compare_reproduction(common(current),common(old))
            records.append(dict(name=name,**comparison))
            computed=math.fsum(row['resource_cost_cny']/(1+discount)**(row['year']-2024) for row in current['paths'])
            actual=current['summary']['discounted_resource_cost_cny']
            accounting.append(dict(name=name,discount_rate=discount,recomputed_cny=computed,reported_cny=actual,
                difference_cny=abs(computed-actual),tolerance_cny=cumulative_cost_tolerance(computed,actual),
                passed=abs(computed-actual)<=cumulative_cost_tolerance(computed,actual)))
            cells=[dict(year=y['year'],service=s,**v) for y in current['services'] for s,v in y['services'].items()
                   if s.startswith('nonenergy_feedstock/')]
            if any({s for s in y['services'] if s.startswith('nonenergy_feedstock/')} !=
                   {'nonenergy_feedstock/coal','nonenergy_feedstock/oil','nonenergy_feedstock/gas'} for y in current['services']):
                raise ValueError('Missing material identity: '+name)
            material.append(dict(name=name,cells=len(cells),maximum_fraction=max(c['fraction'] for c in cells)))
    save(out/'previous_revision_comparison.json',dict(
        scope='Common actual paths, summary, decisions and terminal cohorts; changed service/forecast schema excluded explicitly',
        records=records,all_common_fields_equivalent=all(r['passed'] for r in records)))
    save(out/'independent_accounting.json',dict(records=accounting,passed=all(r['passed'] for r in accounting)))
    save(out/'material_observed_scope.json',dict(records=material,
         all_three_materials_present=True,all_material_demand_met=all(r['maximum_fraction']<=1e-8 for r in material)))

    protected=['src/energy_model','tests','workflow/model_inputs.json','data/sources.json','data/evidence_reviews.json','只读工作区']
    changed=subprocess.check_output(['git','diff','--name-only','af4529b','--',*protected],cwd=ROOT,text=True,encoding='utf-8').splitlines()
    legacy_changes=[p for p in changed if not p.startswith('tests/research/')]
    save(out/'legacy_test_reuse.json',dict(passed=not legacy_changes,tests=339,executed_this_revision=False,
        baseline='af4529bfa7d163052b4412b850a66a4895479a6e',protected_changes=legacy_changes,
        receipt_sha256=hashlib.sha256((ROOT/'outputs/research_n2/legacy_tests.json').read_bytes()).hexdigest(),
        scope='Unchanged legacy implementation and tests; 22 research tests freshly executed separately'))
    passed=probe['passed'] and one_ulp['passed'] and not real_deviation['passed'] and all(r['passed'] for r in accounting) and not legacy_changes
    save(out/'review_checks.json',dict(passed=passed,common_results_equivalent=all(r['passed'] for r in records),
         counterexample_passed=probe['passed'],roundoff_probe_passed=one_ulp['passed'] and not real_deviation['passed'],
         accounting_passed=all(r['passed'] for r in accounting),legacy_reuse_verified=not legacy_changes))
    print(json.dumps(dict(passed=passed,primary_paths=len(records),common_results_equivalent=all(r['passed'] for r in records))))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
