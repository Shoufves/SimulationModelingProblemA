"""Compare all scientific results with the exact reviewed commit, allowing only
the retirement classification correction and explicitly named delay metadata.
"""
import csv
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import subprocess
from compare_q3_runs import ledger_rows
from run_q3 import ROOT,load,dump,sha,verify_latest

REVIEWED='bf8590809004466d2f595407eb61ddd2b6b7e5a2'
RESULT_PATH='outputs/q3/p3_yx'


def reference():
    raw=subprocess.check_output(['git','show',REVIEWED+':'+RESULT_PATH+'/run_manifest.json'],cwd=ROOT)
    manifest=json.loads(raw)
    folder=ROOT/(RESULT_PATH+'.attempts')/manifest['run_id']
    if not folder.exists():
        folder=ROOT/'tmp/q3/review13/reference_bf85908';folder.mkdir(parents=True,exist_ok=True)
        for name in ['run_manifest.json',*manifest['outputs']]:
            if Path(name).name!=name:raise ValueError('Invalid archived artifact name')
            target=folder/name
            if not target.exists():target.write_bytes(subprocess.check_output(['git','show',REVIEWED+':'+RESULT_PATH+'/'+name],cwd=ROOT))
    if sha(folder/'run_manifest.json')!=hashlib.sha256(raw).hexdigest():raise ValueError('Reference manifest differs from reviewed commit')
    for name,digest in manifest['outputs'].items():
        if sha(folder/name)!=digest:raise ValueError('Changed reference artifact '+name)
    return folder,manifest


def compare():
    before,old_manifest=reference();after=ROOT/RESULT_PATH;new_manifest=verify_latest(after)
    config=load(after/'frozen_config.json');tol=config['acceptance'];errors=[];count=0;max_relative=0.0
    def visit(a,b,path):
        nonlocal count,max_relative
        if len(errors)>=20:return
        if isinstance(a,bool) or isinstance(b,bool):
            if type(a)!=type(b) or a!=b:errors.append(path+' boolean')
        elif isinstance(a,(int,float)) and isinstance(b,(int,float)):
            count+=1;scale=max(1,abs(a),abs(b));difference=abs(a-b)
            bound=tol['absolute_numeric_tolerance']+tol['relative_numeric_tolerance']*scale
            if 'residual' in path:bound=max(bound,tol['cash_absolute_tolerance_cny'] if 'cny' in path else tol['physical_residual_mwh'])
            if not(math.isfinite(a) and math.isfinite(b)) or difference>bound:errors.append(dict(path=path,before=a,after=b,bound=bound))
            if 'residual' not in path:max_relative=max(max_relative,difference/scale)
        elif isinstance(a,dict) and isinstance(b,dict):
            if set(a)!=set(b):errors.append(dict(path=path,key_difference=sorted(set(a)^set(b))));return
            for key in a:visit(a[key],b[key],path+'/'+str(key))
        elif isinstance(a,list) and isinstance(b,list):
            if len(a)!=len(b):errors.append(path+' length');return
            for i,(x,y) in enumerate(zip(a,b)):visit(x,y,path+'/'+str(i))
        elif isinstance(a,str) and isinstance(b,str) and a!=b:
            try:x,y=json.loads(a),json.loads(b)
            except (ValueError,TypeError):errors.append(path+' text');return
            visit(x,y,path)
        elif a!=b:errors.append(path+' value')
    config_before=load(before/'frozen_config.json');normalized=json.loads(json.dumps(config))
    normalized['experiment_version']=config_before['experiment_version']
    normalized.pop('pr13_review_revision');normalized['h01'].pop('delay_targets')
    visit(config_before,normalized,'config_without_declared_metadata')
    natural_by_case={};corrections=[];case_counts={}
    for kind in ('annual','event'):
        cases=0
        for a,b in zip_longest(ledger_rows(before,kind),ledger_rows(after,kind)):
            if a is None or b is None:errors.append(kind+' case count');break
            cases+=1
            if kind=='annual':
                actual=[r for r in a['retirement'] if r['action']!='decision']
                natural=[r for r in actual if r['year']==r['natural_exit']]
                total=math.fsum(r['capacity_mw'] for r in natural);natural_by_case[a['case']]=total
                prior=a['paths'][-1]['q3_early_retired_mw']
                for row in a['paths']:
                    cumulative=math.fsum(r['capacity_mw'] for r in natural if r['year']<=row['year'])
                    row['q3_early_retired_mw']-=cumulative
                    row['q3_managed_natural_retired_mw']=cumulative
                for row in natural:row['action']='natural_retired'
                if a['spec']['study']=='h01':
                    mode='fixed_committed_generation' if a['spec']['fixed_pipeline'] else 'full_agent_response'
                    a['spec']['delay_target']=config['h01']['delay_targets'][mode]
                corrections.append(dict(case=a['case'],before_early_mw=prior,
                    after_early_mw=b['paths'][-1]['q3_early_retired_mw'],reclassified_natural_mw=total,
                    changed=total>tol['absolute_numeric_tolerance']))
            visit(a,b,kind+'/'+a['case'])
            if cases%40==0:print(f'PR13 invariant comparison {kind} {cases}',flush=True)
        case_counts[kind]=cases
    old_names={n for n in old_manifest['outputs'] if not n.endswith(('.gz','.png'))}
    new_names={n for n in new_manifest['outputs'] if not n.endswith(('.gz','.png'))}
    if old_names!=new_names:errors.append('Scientific table set changed')
    for name in sorted(old_names&new_names):
        if name=='frozen_config.json':continue
        if name.endswith('.json'):visit(load(before/name),load(after/name),name)
        elif name.endswith('.csv'):
            with (before/name).open(encoding='utf-8',newline='') as f,(after/name).open(encoding='utf-8',newline='') as g:
                for i,(a,b) in enumerate(zip_longest(csv.DictReader(f),csv.DictReader(g))):
                    if a is None or b is None:errors.append(name+' rows');break
                    case=a.get('case') or a.get('policy') or a.get('scenario')
                    natural=natural_by_case.get(case,0.0)
                    if 'retired_early_mw' in a:
                        a['managed_natural_retired_mw']=str(natural) if a['retired_early_mw'] else ''
                        if a['retired_early_mw']:a['retired_early_mw']=str(float(a['retired_early_mw'])-natural)
                    if 'q3_early_retired_mw' in a:a['q3_managed_natural_retired_mw']='0.0' # S0/SP/ST only
                    if name=='h01_results.csv':a['delay_target']=config['h01']['delay_targets'][a['project_mode']]
                    visit(a,b,f'{name}/{i}')
        elif name=='report.md':
            current=(after/name).read_text(encoding='utf-8').splitlines()
            added=[x for x in current if x.startswith('H01的delay_target明确区分L：')]
            if len(added)!=1:errors.append('Missing unique intervention/classification explanation')
            visit((before/name).read_text(encoding='utf-8').splitlines(),[x for x in current if x not in added],name)
        else:visit((before/name).read_text(encoding='utf-8'),(after/name).read_text(encoding='utf-8'),name)
    return dict(passed=not errors,status='classification_only_physics_costs_and_selection_unchanged' if not errors else 'failed',
        reviewed_sha=REVIEWED,old_manifest_sha256=sha(before/'run_manifest.json'),new_manifest_sha256=sha(after/'run_manifest.json'),
        case_counts=case_counts,numeric_values_compared=count,max_nonresidual_relative_difference=max_relative,
        affected_h01_cases=sum(r['changed'] and r['case'].startswith('h01') for r in corrections),retirement_corrections=corrections,
        policy_selection_unchanged=load(before/'policy_selection.json')==load(after/'policy_selection.json'),
        errors=errors,checker_sha256=sha(Path(__file__)),
        scope='All ledgers and scientific tables compared after only the declared classification correction and delay labels. Image bytes are not a scientific equality requirement.')


if __name__=='__main__':
    destination=ROOT/'outputs/q3_review/pr13_change_comparison.json'
    dump(destination,dict(passed=False,status='running'))
    try:result=compare()
    except Exception as exc:result=dict(passed=False,status='failed',error=str(exc))
    dump(destination,result)
    print(json.dumps({k:v for k,v in result.items() if k!='retirement_corrections'},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
