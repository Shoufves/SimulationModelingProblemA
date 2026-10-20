"""Independent engineering and ledger checks; preserve historical receipts."""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/q123_alignment'
BASE='35e3bc55098e6c2b97f2899e5905e135cd0e2ce6'


def load(path):return json.loads(path.read_text('utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
def csv_write(path,records):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for r in records for k in r)))
        writer.writeheader();writer.writerows(records)


def execute(name,args,side_effects=()):
    saved={p:(ROOT/p).read_bytes() if (ROOT/p).exists() else None for p in side_effects}
    start=time.perf_counter()
    try:
        with (OUT/(name+'.log')).open('w',encoding='utf-8') as stream:
            process=subprocess.run([sys.executable,'-B','-X','utf8',*args],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        for p in side_effects:
            if (ROOT/p).is_file():
                (OUT/(name+'_'+Path(p).name)).write_bytes((ROOT/p).read_bytes())
    finally:
        for p,data in saved.items():
            if data is not None:(ROOT/p).write_bytes(data)
            elif (ROOT/p).exists():(ROOT/p).unlink()
    result=dict(passed=process.returncode==0,exit_code=process.returncode,seconds=time.perf_counter()-start,arguments=args)
    print(name,result['passed'],flush=True)
    return result


def checks():
    results={}
    jobs=[('main_tests',['run.py','test'],['outputs/validation/tests.json']),
          ('alignment_tests',['-m','unittest','discover','-s','tests/alignment','-v'],[]),
          ('n2_tests',['-m','unittest','discover','-s','tests/research','-v'],[]),
          ('workspace_audit',['scripts/audit_workspace.py'],['outputs/validation/workspace_audit.json']),
          ('formal_inputs',['scripts/workflow_status.py','--check-formal-inputs'],
           ['outputs/workflow/status.json','outputs/workflow/status.md','outputs/workflow/next_prompt.md']),
          ('key_scan',['scripts/scan_google_keys.py'],[])]
    for name,args,effects in jobs:
        results[name]=execute(name,args,effects)
        save(OUT/'checks.json',dict(passed=all(r['passed'] for r in results.values()),checks=results))
    return all(r['passed'] for r in results.values())


def preservation():
    allowed={'run.py','tests/test_q2_pr14_integration.py','README.md','WORKFLOW.md','docs/RUNNING.md',
             'docs/DATA_GUIDE.md','docs/IMPLEMENTATION_ROADMAP.md','docs/ROUND_LOG.md','.gitignore','.gitattributes',
             'data/catalog/datasets_unified.csv','outputs/q2_pr14/integrated/latest.json'}
    tree=subprocess.check_output(['git','ls-tree','-rzl',BASE],cwd=ROOT).split(b'\0')
    failures=[];count=0;restricted=0
    for item in tree:
        if not item:continue
        info,path=item.split(b'\t',1);path=path.decode('utf8')
        _,kind,oid,size=info.decode().split()
        if kind!='blob' or path in allowed:continue
        file=ROOT/path
        if path.startswith('data/restricted/'):
            restricted+=1
            if not file.is_file() or file.stat().st_size!=int(size):failures.append(path)
            continue
        if not file.is_file():failures.append(path);continue
        content=file.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        count+=1
        if actual!=oid:failures.append(path)
    result=dict(passed=not failures,base=BASE,checked_original_files=count,restricted_metadata_only=restricted,
                exceptions=sorted(allowed),changed_protected_files=failures)
    save(OUT/'preservation.json',result)
    return result


def ledgers(folder,kind):
    for path in sorted(folder.glob(kind+'_ledgers_*.jsonl.gz')):
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line in stream:yield json.loads(line)


def analyse():
    # A fresh process is required for this branch: import the pinned runtime.
    sys.path.insert(0,str(ROOT/'scripts'))
    import run_q3_pr14 as runner
    from q3_pr14.services import service_key
    from run_q2_pr14 import verify_latest as verify_q2
    current=ROOT/'outputs/q3_pr14/current';replica=ROOT/'tmp/q3_pr14/reproduction'
    primary=runner.verify_latest(current);repeated=runner.verify_latest(replica)
    folder=current/load(current/'latest.json')['attempt']
    other=replica/load(replica/'latest.json')['attempt']
    q2=verify_q2(ROOT/'outputs/q2_pr14/aligned_validation')
    expected=runner.protocol.case_specs(runner.preflight())
    annual_ids=[];service_rows=[];summaries=[];retirements=0;max_residual=0.;event_count=0
    failures=[]
    record=runner.decode(runner.load(ROOT/'data/processed/q2_delivery/parsed_inputs.json')['net58/25'])
    discount=runner.make_model(runner.preflight(),{}).a['discount_rate']
    for case in ledgers(folder,'annual'):
        annual_ids.append(case['case']);by=defaultdict(lambda:[0.,0.])
        for r in case['operations']:
            if r['kind']=='demand':
                item=by[r['year'],service_key(r)]
                item[0]+=r['requested_service_mwh']*365;item[1]+=r['unmet_service_mwh']*365
        worst=max(u/q for q,u in by.values() if q)
        domestic=max((u/q for (y,s),(q,u) in by.items() if q and s!='electricity_exports'),default=0.)
        if case['case'] in ('S0','SP','ST'):
            service_rows.extend(dict(scenario=case['case'],year=y,service=s,requested=q,unmet=u,fraction=u/q if q else 0.) for (y,s),(q,u) in by.items())
        paths=case['paths'];total=math.fsum(r['resource_cost_cny'] for r in paths)
        discounted=math.fsum(r['resource_cost_cny']/(1+discount)**(r['year']-2024) for r in paths)
        summaries.append(dict(case=case['case'],resource_cost_cny=total,discounted_resource_cost_cny=discounted,
            discount_rate=discount,max_service_fraction=worst,max_domestic_service_fraction=domestic,
            aggregate_display_fraction=max(r['unmet_service_mwh']/r['requested_service_mwh'] for r in paths),
            cumulative_positive_co2_t=math.fsum(r['positive_co2_t'] for r in paths),end_year=paths[-1]['year']))
        for path in paths:
            max_residual=max(max_residual,abs(path['max_residual']))
            if path['q3_public_commitment_cny']>path['q3_public_budget_cny']+.1:
                failures.append([case['case'],'public budget'])
            for field in ('construction_fund_residual_cny','financing_transfer_residual_cny','infrastructure_fund_residual_cny'):
                if abs(path[field])>.1:failures.append([case['case'],path['year'],field])
        early=natural=0.
        for r in case['retirement']:
            if r['action'] in ('early_retired','natural_retired'):
                retirements+=1
                correct=r['year']<r['natural_exit'] if r['action']=='early_retired' else r['year']==r['natural_exit']
                if not correct or r['year']>r['deadline']:failures.append([case['case'],'retirement lifetime'])
                if r['action']=='early_retired':early+=r['capacity_mw']
                else:natural+=r['capacity_mw']
        if abs(early-paths[-1]['q3_early_retired_mw'])>1e-6 or abs(natural-paths[-1]['q3_managed_natural_retired_mw'])>1e-6:
            failures.append([case['case'],'retirement totals'])
    if annual_ids!=[s['id'] for s in expected]:failures.append(['annual case grid'])
    for event in ledgers(folder,'event'):
        event_count+=1;max_residual=max(max_residual,event['max_residual'])
        data=event['rows']
        for name in {r['store'] for r in data['additional_storage']}:
            seq=[r for r in data['additional_storage'] if r['store']==name]
            if len(seq)!=48 or any(abs(a['closing_mwh']-b['opening_mwh'])>1e-6 for a,b in zip(seq,seq[1:])):
                failures.append([event['case'],'additional SOC continuity'])
        if any(r['closing_mwh']<-1e-6 for kind in ('fuel','storage','additional_storage') for r in data[kind]):
            failures.append([event['case'],'negative stock'])
    if event_count!=118 or max_residual>1e-6:failures.append(['event count or conservation',event_count,max_residual])
    # All outputs, including every ledger, must be byte-identical between runs.
    # SVG/PNG metadata is kept separate from scientific determinism.
    names=set(primary['outputs'])
    different=[n for n in sorted(names) if n in repeated['outputs'] and primary['outputs'][n]!=repeated['outputs'][n]]
    if names!=set(repeated['outputs']) or different:failures.append(['reproduction',different])
    csv_write(OUT/'annual_common_metrics.csv',summaries)
    csv_write(OUT/'scenario_service_fractions.csv',service_rows)
    h01=rows(folder/'h01_results.csv');h02=rows(folder/'h02_results.csv');selection=load(folder/'policy_selection.json')
    q1=load(ROOT/'outputs/q1/pr14_aligned/alignment_manifest.json')
    for p,digest in q1['input_hashes'].items():
        if sha(ROOT/p)!=digest:failures.append(['Q1 input changed',p])
    for name,digest in q1['outputs'].items():
        if sha(ROOT/'outputs/q1/pr14_aligned'/name)!=digest:failures.append(['Q1 output changed',name])
    if sha(ROOT/'outputs/q1/pr14_aligned/indicators.csv')!=sha(ROOT/'outputs/q1/p1_yx/indicators.csv'):
        failures.append(['Q1 indicators changed'])
    result=dict(passed=not failures,failures=failures,annual_cases=len(annual_ids),event_cases=event_count,
        h01_cases=len(h01),h01_service_failures=sum(r['service_bound_passed']=='False' for r in h01),
        h02_rows=len(h02),max_abs_h02_J=max(abs(float(r['J_normal'])) for r in h02),
        max_abs_h02_response=max(abs(float(r['response_contribution'])) for r in h02),
        selected_policy=selection['selected'],selected_rule=selection['selected_rule'],
        max_physical_residual=max_residual,retirement_records_checked=retirements,
        q2_cases=len(q2['cases']),q2_historical_training_rerun=False,q1=q1['coverage'],
        reproduction=dict(primary=str(folder.relative_to(ROOT)),replica=str(other.relative_to(ROOT)),
            compared_outputs=len(names),different_outputs=different,all_scientific_outputs_exact=not different),
        evidence=dict(q3_manifest=sha(folder/'manifest.json'),q3_reproduction_manifest=sha(other/'manifest.json'),
                      q1_manifest=sha(ROOT/'outputs/q1/pr14_aligned/alignment_manifest.json')),
        scope='engineering, conditional cases and reproducibility; not nationwide empirical validation or human approval')
    save(OUT/'scientific_checks.json',result)
    save(OUT/'reproduction_manifest.json',repeated)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('checks','results','accept'));args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.mode=='checks':return 0 if checks() else 1
    if args.mode=='results':return 0 if analyse()['passed'] else 1
    preserved=preservation();checks_record=load(OUT/'checks.json');science=load(OUT/'scientific_checks.json')
    result=dict(passed=preserved['passed'] and checks_record['passed'] and science['passed'],
        base=BASE,historical_training_rerun=False,team_approved=False,
        checks=checks_record,science= science,
        verification_code_hashes={p:sha(ROOT/p) for p in (
            'run.py','scripts/check_q123_alignment.py','scripts/build_q1_pr14.py',
            'tests/test_q2_pr14_integration.py','tests/alignment/test_pr14_alignment.py')},
        evidence_hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='acceptance.json'})
    save(OUT/'acceptance.json',result);print(json.dumps(dict(passed=result['passed']),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
