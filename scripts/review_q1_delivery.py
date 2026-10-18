"""Fresh Q1 delivery verification, including actual inputs/originals and new runs."""
from pathlib import Path
import csv, hashlib, json, re, subprocess, sys
import xml.etree.ElementTree as ET
import build_q1 as q1

ROOT=Path(__file__).resolve().parents[1]


def load(p):return json.loads(p.read_text(encoding='utf-8'))


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def validate_current_artifacts(folder, config):
    """Reject stale success even when a subsequent failed run preserved its outputs."""
    q1.preflight(config)
    m=load(folder/'run_manifest.json')
    latest=load(folder.parent/(folder.name+'.latest-attempt.json'))
    if (m.get('status')!='success' or m.get('owner')!='p1/lb' or latest.get('status')!='success'
            or not latest.get('output_valid_for_this_attempt') or not m.get('run_id')
            or m['run_id']!=latest.get('run_id') or digest(folder/'run_manifest.json')!=latest.get('manifest_sha256')):
        raise ValueError('No matching latest successful attempt')
    if (m.get('config_path')!='workflow/q1_inputs.json' or digest(ROOT/'workflow/q1_inputs.json')!=m.get('config_sha256')
            or m.get('inputs')!=config['inputs'] or m.get('sources')!=config['sources']
            or m.get('config')!=config['decisions']):
        raise ValueError('Manifest/config/input/source identity mismatch')
    expected={p:digest(ROOT/p) for p in q1.CODE_PATHS}
    if m.get('code_hashes')!=expected:raise ValueError('Manifest code identity mismatch')
    if not m.get('outputs') or any(digest(folder/name)!=h for name,h in m['outputs'].items()):
        raise ValueError('Output hash mismatch')
    return m


def validation_identity(config):
    paths={'workflow/q1_inputs.json','run.py'}
    paths.update(str(p.relative_to(ROOT)).replace('\\','/') for sub in ('scripts','src','tests') for p in (ROOT/sub).rglob('*.py'))
    paths.update(r['path'] for r in config['inputs'])
    paths.update(a['path'] for s in config['sources'].values() for a in s['artifacts'])
    return {p:digest(ROOT/p) for p in sorted(paths)}


def main():
    out=ROOT/'outputs/q1/p1_lb';replica=ROOT/'outputs/q1/lb_reproduction'
    evidence=ROOT/'outputs/q1_review/revision1/delivery';evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'final_verification.json').write_text(json.dumps(dict(passed=False,status='running',
        scope='No successful current verification receipt until all checks finish')),encoding='utf-8')
    checks=[]
    def check(name,passed,detail):checks.append(dict(check=name,passed=bool(passed),detail=detail))
    # Never use a saved tests.json or an old manifest as evidence of a new execution.
    try:
        config=load(ROOT/'workflow/q1_inputs.json');q1.preflight(config)
        before=validation_identity(config)
        fresh=[]
        jobs=[('tests',['run.py','test']),('audit',['run.py','audit']),('key_scan',['scripts/scan_google_keys.py'])]
        for label,args in jobs:
            result=subprocess.run([sys.executable,'-B','-X','utf8',*args],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
            (evidence/(label+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
            fresh.append(dict(command=args,returncode=result.returncode))
            if result.returncode:raise ValueError('Fresh check failed: '+label)
        for folder in (out,replica):
            prior=load(folder/'run_manifest.json').get('run_id') if (folder/'run_manifest.json').exists() else None
            result=subprocess.run([sys.executable,'-B','-X','utf8','run.py','q1','--output-dir',folder.relative_to(ROOT).as_posix()],
                                  cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
            (evidence/(folder.name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
            if result.returncode:raise ValueError('Fresh Q1 run failed: '+folder.name)
            m=validate_current_artifacts(folder,config)
            if m['run_id']==prior:raise ValueError('Fresh run did not replace run identity')
            fresh.append(dict(command=m['command'],returncode=0,run_id=m['run_id'],manifest_sha256=digest(folder/'run_manifest.json')))
        q1.preflight(config)
        if before!=validation_identity(config):raise ValueError('Inputs/code changed during verification')
        check('fresh_checks_and_input_identity',True,dict(identity=before,runs=fresh))
    except (ValueError,OSError,KeyError,TypeError) as exc:
        result=dict(passed=False,scope='Fresh delivery verification failed; previous outputs are not current success evidence',
                    error=str(exc),checks=checks)
        (evidence/'final_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False));return 1
    required={'history.csv','indicators.csv','energy_roles.csv','model_handoff.csv','gaps_and_conflicts.csv','static_balance.json','report.md',
              'coverage.csv','regional_comparison.csv','import_origins.csv','demand_trends.svg','cost_sensitivity.svg','regional_shares.svg',
              'price_trends.svg','energy_assessment.csv','synergy_assessment.csv','renewable_regions.csv','technology_region_capacities.csv'}
    manifests=[]
    for folder in (out,replica):
        m=validate_current_artifacts(folder,config);manifests.append(m)
        check(folder.name+'_success',m['status']=='success' and m['owner']=='p1/lb',m['counts'])
        check(folder.name+'_output_set',set(m['outputs'])==required,sorted(m['outputs']))
        check(folder.name+'_output_hashes',all(digest(folder/name)==h for name,h in m['outputs'].items()),m['outputs'])
        check(folder.name+'_code_current',all(digest(ROOT/name)==h for name,h in m['code_hashes'].items()),m['code_hashes'])
        check(folder.name+'_config_current',digest(ROOT/m['config_path'])==m['config_sha256'],m['config_sha256'])
    compared=[dict(file=name,match=(out/name).read_bytes()==(replica/name).read_bytes(),sha256=digest(out/name)) for name in sorted(required)]
    check('independent_directory_reproduction',all(r['match'] for r in compared),compared)
    (evidence/'reproduction.json').write_text(json.dumps(dict(passed=all(r['match'] for r in compared),compared_files=len(compared),
        excluded='run_manifest.json: output command and run metadata intentionally differ',checks=compared),ensure_ascii=False,indent=2),encoding='utf-8')
    history=rows(out/'history.csv');indicators=rows(out/'indicators.csv');ids={r['record_id'] for r in history}
    check('unique_history_keys',len(ids)==len(history),len(history))
    check('four_dimensions_have_quantitative_evidence',{r['dimension'] for r in indicators if r['value']!=''}=={'保障','低碳','经济','协调'},
        {dim:sum(r['dimension']==dim for r in indicators) for dim in ('保障','低碳','经济','协调')})
    check('indicator_inputs_resolve',all(s in ids for r in indicators for s in r['input_refs'].split(';') if s),len(indicators))
    roles=rows(out/'energy_roles.csv')
    check('nine_energies_and_three_support_roles',{r['energy'] for r in roles}=={'煤炭','石油','天然气','水电','核电','风电','光伏','生物质','氢能','储能','输送','CCUS'},len(roles))
    hand=rows(out/'model_handoff.csv')
    check('handoff_refs_resolve',all(s in ids for r in hand for s in r['candidate_refs'].split(';') if s),len(hand))
    numeric=[r for r in hand if r['record_kind']=='numeric_observation_candidate']
    check('handoff_numeric_values',numeric and all(r['value'] and r['unit'] and r['year'] and r['formal_initialization'] for r in numeric),len(numeric))
    price_rows=[r for r in history if r['dataset']=='prices']
    check('price_quarantine_not_admitted',all(r['status'] in ('archived_reference','reviewed_release') and
        r['source_key'] in ('yx:WB_PINK_SHEET_STABLE','q1:Q1_WB_PINK_JANUARY_2024','q1:Q1_WB_PINK_FEB_2025') for r in price_rows),
          'Old archived source plus individually reviewed PDF releases; anomalous Europe 2024 excluded')
    check('anomalous_price_cell_excluded',not any(r['variable']=='Natural gas, Europe' and r['year']=='2024' for r in price_rows),'2024 2.00 USD/MMBtu rejected; NEA TTF separately labelled')
    assessment=rows(out/'energy_assessment.csv');synergies=rows(out/'synergy_assessment.csv')
    check('per_energy_four_dimension_evidence',len(assessment)==36 and all(r['input_refs'] and set(r['input_refs'].split(';'))<=ids for r in assessment),len(assessment))
    check('synergy_conditions_and_evidence',{r['synergy_id'] for r in synergies}=={f'SYN{i:02d}' for i in range(1,9)} and len(synergies)==8 and all(r['applicable_conditions'] and r['tradeoff_or_failure'] and r['next_model_test'] and set(r['input_refs'].split(';'))<=ids for r in synergies),len(synergies))
    report=(out/'report.md').read_text(encoding='utf-8')
    targets=re.findall(r'\]\(([^)]+)\)',report)
    check('report_links_resolve',all((out/path).is_file() for path in targets),targets)
    for name in ('demand_trends.svg','cost_sensitivity.svg','regional_shares.svg','price_trends.svg'):
        root=ET.parse(out/name).getroot();check(name+'_valid_svg',root.tag.endswith('svg'),digest(out/name))
    # Original cell-check receipts remain historical evidence in round3, not current execution gates.
    validation=ROOT/'outputs/validation'
    for filename in ('tests.json','workspace_audit.json'):
        r=load(validation/filename);check(filename,r['passed'],r.get('tests',len(r.get('checks',[]))))
        (evidence/filename).write_bytes((validation/filename).read_bytes())
    base='7a65d068d19eea2f7dd8161a618a3ad8d66f98b8'
    contracts=['data/sources.json','data/evidence_reviews.json','workflow/model_inputs.json']
    original_checks=[]
    for name in contracts:
        original=subprocess.check_output(['git','show',base+':'+name],cwd=ROOT)
        original_checks.append(dict(file=name,unchanged=original==(ROOT/name).read_bytes()))
    check('original_admission_contracts_unchanged',all(r['unchanged'] for r in original_checks),original_checks)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    ancestry=subprocess.run(['git','merge-base','--is-ancestor',base,head],cwd=ROOT,capture_output=True)
    check('requested_base_is_ancestor',ancestry.returncode==0,
          dict(base=base,head=head,branch=branch or 'detached review checkout'))
    result=dict(passed=all(r['passed'] for r in checks),scope='Engineering and provenance checks only; not proof that all three Q1 subquestions are complete; not external acceptance A7',checks=checks,
                files=dict(history=len(history),indicators=len(indicators),handoff=len(hand),numeric_candidates=len(numeric)),
                pending_external_review='Two real reviewers must approve the same final PR head before merge; local checks do not grant approval')
    (evidence/'final_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],checks=len(checks),failed=[r['check'] for r in checks if not r['passed']],files=result['files']),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
