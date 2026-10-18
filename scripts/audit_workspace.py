"""Verify consolidation, protected originals, provenance, links and data keys."""
from pathlib import Path
from collections import defaultdict
import ast, csv, hashlib, json, re, zipfile
from scan_google_keys import scan_workspace

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/'archive/organization_20261017'

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def is_external_history(r):
    """Only the six recorded foreign-problem removals are clone-external history."""
    known={
        '104132baece63e54fcc8238d414bd31e8c6c0923402380ba41674b1eda812981',
        '5f98ef37a4052c58e7e514f77c5fb9463d14f1a3af36468e82489585efebdff0',
        '2bd051219c2cb3d6bb9fb22b2f6a29d1434aa0405aa5168216a747d8f6569abc',
        'c947f403767334b85afc1792eee46f2b74d0271a99af628b3fdd8c95cd7ddd1d',
        '75fdd54aa2f880b9e4e1e7539e4e4760f582917407afca41a29a6329533e7e49',
        '375d44e233362586ed4699abe3d95e691ace96fda880a55737f57087189a1776'}
    parts=r.get('target','').replace('\\','/').split('/')
    prefix='A题_lb/A题完整资料包/2026年第二届全国大学生仿真建模应用挑战赛赛题/'
    return (r.get('action')=='external_duplicate' and r.get('sha256') in known
        and len(parts)==3 and parts[0]=='..' and parts[1] in ('B题','C题')
        and parts[2] not in ('','.','..') and r.get('path')==prefix+'/'.join(parts[1:]))


def main():
    checks=[]
    def check(name,passed,detail):checks.append(dict(check=name,passed=bool(passed),detail=detail))
    plan=json.loads((AUDIT/'file_disposition.json').read_text(encoding='utf-8'))
    archives=[]
    for name in ('edited_originals.zip','prior_results.zip'):
        p=AUDIT/name
        if p.exists():
            with zipfile.ZipFile(p) as z:
                archives.append({n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()})
    missing=[];modified=[];retained=0;external_history=[]
    for r in plan:
        if not r['target']:continue
        if is_external_history(r):
            external_history.append(dict(path=r['path'],historical_target=r['target'],sha256=r['sha256'],
                status='historical_foreign_duplicate; external presence not checked'))
            continue
        p=(ROOT/r['target']).resolve()
        if not p.is_relative_to(ROOT):missing.append(r['path']+' (unexpected external target)');continue
        if not p.is_file():missing.append(r['path']);continue
        h=sha(p)
        stored_copy=(r.get('representation')=='offline_html'
            and r['target'].startswith('data/raw/') and p.suffix=='.html'
            and h==r.get('stored_sha256') and p.stat().st_size==r.get('stored_bytes'))
        if h!=r['sha256'] and not stored_copy and not any(d.get(r['target'])==r['sha256'] for d in archives):
            modified.append(r['path'])
        retained+=1
    check('retained_files_match_inventory',not missing and not modified,dict(resolved_original_paths=retained,missing=missing,unrecoverable_modifications=modified,external_historical_records=external_history))
    key_scan=scan_workspace()
    check('working_tree_google_api_keys_absent',key_scan['passed'],key_scan)
    check('protected_directory_unchanged',all(sha(ROOT/r['target'])==r['sha256'] for r in plan if r['action']=='protect'),3)
    official=[r for r in plan if '/' not in r['path'] and not r['path'].startswith('~$')]
    check('five_official_originals_unchanged',len(official)==5 and all(sha(ROOT/r['path'])==r['sha256'] for r in official),[r['path'] for r in official])
    check('three_workspaces_consolidated',not any((ROOT/p).exists() for p in ('A题_mmj','A题_lb','script','分析整理')),'one A workspace')
    foreign=[p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and any(x in ('B题','C题') for x in p.relative_to(ROOT).parts)]
    check('no_B_C_payload',not foreign,foreign)
    refs=json.loads((ROOT/'data/catalog/final_references.json').read_text(encoding='utf-8'))
    absent=[k for k,v in refs.items() if not (ROOT/v['path']).is_file()]
    check('all_final_references_resolve',not absent,dict(count=len(refs),missing=absent))
    readerv=ROOT/'docs/final_阅读版.md'
    reader_missing=[]
    if readerv.exists():
        for key,path in re.findall(r'^\[([^\]]+)\]:\s*<([^>]+)>',readerv.read_text(encoding='utf-8'),re.M):
            if not (readerv.parent/path).is_file():reader_missing.append(dict(key=key,path=path))
    check('final_reader_links_resolve',readerv.exists() and not reader_missing,reader_missing)
    syntax=[]
    for folder in ('scripts','src','tests','tools','apps'):
        for p in (ROOT/folder).rglob('*.py'):
            try:ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
            except Exception as e:syntax.append(dict(path=str(p),error=str(e)))
    check('retained_python_syntax',not syntax,syntax)
    with (ROOT/'data/processed/unified/nbs_history.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    keys=[tuple(r[k] for k in ('edition','family','year','region','variable','unit')) for r in rows]
    check('unified_data_keys_unique',len(keys)==len(set(keys)),len(keys))
    check('unified_rows_trace_to_files',all((ROOT/r['dataset_path']).is_file() and r['source_locator'] and r['source_key'] for r in rows),len(rows))
    check('scope_not_promoted',all(r['blocked_for']=='national_ABM_initialization_and_calibration_without_input_review' for r in rows),'formal admission still governed by model_inputs and evidence_reviews')
    ds=list(csv.DictReader((ROOT/'data/catalog/datasets_unified.csv').open(encoding='utf-8-sig',newline='')))
    quarantined=[r for r in ds if 'transmission_lines_candidate' in r['path'] or 'worldbank_energy' in r['path']]
    check('known_quarantine_preserved',bool(quarantined) and all(r['status']=='quarantined' for r in quarantined),[r['path'] for r in quarantined])
    raw=defaultdict(list)
    for p in (ROOT/'data/raw').rglob('*'):
        if p.is_file():raw[sha(p)].append(p.relative_to(ROOT).as_posix())
    dupes=[v for v in raw.values() if len(v)>1]
    check('raw_exact_duplicates_removed',not dupes,dupes)
    result=dict(scope='Workspace preservation and engineering checks only; not completion of final research.',
        passed=all(r['passed'] for r in checks),checks=checks,
        original_files=len(plan),removed_files=sum(r['action'] in ('deduplicate','external_duplicate','delete_generated') for r in plan),
        removed_bytes=sum(r['bytes'] for r in plan if r['action'] in ('deduplicate','external_duplicate','delete_generated')))
    out=ROOT/'outputs/validation';out.mkdir(parents=True,exist_ok=True)
    (out/'workspace_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
