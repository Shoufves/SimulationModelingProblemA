"""Rebuild selected lb tables offline in an isolated compatibility directory.

The canonical evidence tree is read-only to the legacy scripts. Their original
relative paths are materialized as ordinary copies, never writable hard links.
No private/household row extraction or download recipe is offered here.
"""
from pathlib import Path
import argparse, csv, hashlib, json, os, shutil, subprocess, sys, uuid

ROOT=Path(__file__).resolve().parents[1]
LIB='A题_lb/A题完整资料包/A题资料库/'
RECIPES={
 'national':('scripts/prepare_data.py','scripts/enrich_data.py'),
 'trade':('专项补查_20261017/替代与扩展_20261017/alternatives/extract_and_verify.py',),
 'international':('补充收集_20261017/international/prepare_scenario_data.py',),
 'ai_trade':('专项补查_20261017/ai_trade/build_tables.py',),
}

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(recipe):
    aliases=json.loads((ROOT/'data/catalog/path_aliases.json').read_text(encoding='utf-8'))
    parent=ROOT/'tmp/reproduce_lb';parent.mkdir(parents=True,exist_ok=True)
    directory=(parent/(recipe+'-'+uuid.uuid4().hex)).resolve()
    directory.mkdir()
    if not directory.is_relative_to(parent.resolve()):raise ValueError('Unsafe scratch path')
    # Copy only the dependency region used by the selected recipe.
    prefixes={'national':('scripts/','raw/','data/','extracted/','sources.json','数据文件目录'),
        'trade':('专项补查_20261017/替代与扩展_20261017/alternatives/',),
        'international':('补充收集_20261017/international/',),
        'ai_trade':('专项补查_20261017/ai_trade/',)}[recipe]
    baseline={}
    for old,new in aliases.items():
        if not old.startswith(LIB) or new.startswith('data/restricted/'):continue
        tail=old[len(LIB):]
        if not any(tail.startswith(prefix) for prefix in prefixes):continue
        target=directory/tail;source=ROOT/new
        target.parent.mkdir(parents=True,exist_ok=True)
        generated_table=source.suffix=='.csv' and (tail.startswith('data/') or '/data/' in tail or '/derived/' in tail)
        if source.suffix=='.csv':baseline[tail]=(new,digest(source))
        # The expected outputs must be absent at execution start. Otherwise an
        # unchanged old output could falsely appear to have been reproduced.
        if not generated_table:shutil.copyfile(source,target)
    # Block any attempted network access even if a retained script later changes.
    guard=directory/'_offline_guard';guard.mkdir()
    (guard/'sitecustomize.py').write_text('import socket\ndef deny(*a, **k):\n    raise RuntimeError("Offline reproduction: network disabled")\nsocket.create_connection=deny\nsocket.socket.connect=deny\nsocket.socket.connect_ex=deny\n',encoding='utf-8')
    env=dict(os.environ,PYTHONPATH=str(guard),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    log=[]
    status=0
    for script in RECIPES[recipe]:
        proc=subprocess.run([sys.executable,'-B','-X','utf8',str(directory/script)],cwd=directory,env=env,
            text=True,encoding='utf-8',errors='replace',capture_output=True)
        log.append(dict(script=script,returncode=proc.returncode,stdout=proc.stdout,stderr=proc.stderr))
        if proc.returncode:status=proc.returncode;break
    comparisons=[]
    for tail,(canonical,oldhash) in baseline.items():
        # Compare generated structured tables, not raw downloaded CSV datasets.
        if not (tail.startswith('data/') or '/data/' in tail or '/derived/' in tail):continue
        p=directory/tail
        if not p.is_file():
            comparisons.append(dict(path=canonical,byte_equal=False,table_equal=False,reason='expected output was not generated'))
            continue
        with p.open(encoding='utf-8-sig',newline='') as f:newrows=list(csv.reader(f))
        with (ROOT/canonical).open(encoding='utf-8-sig',newline='') as f:oldrows=list(csv.reader(f))
        comparisons.append(dict(path=canonical,byte_equal=digest(p)==oldhash,table_equal=newrows==oldrows))
    report=dict(recipe=recipe,status='passed' if status==0 and comparisons and all(c['table_equal'] for c in comparisons) else 'failed',
        comparisons=comparisons,execution=log,
        expected_outputs_absent_before_execution=True,
        scope='Offline reproduction of saved extraction recipes; not independent source verification or national simulation.')
    out=ROOT/'outputs/validation';out.mkdir(parents=True,exist_ok=True)
    (out/f'lb_reproduce_{recipe}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Safe, bounded removal of only our freshly created temporary directory.
    if directory.parent!=parent.resolve():raise ValueError('Unsafe cleanup path')
    shutil.rmtree(directory)
    print(json.dumps({k:v for k,v in report.items() if k!='execution'},ensure_ascii=False,indent=2))
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('recipe',choices=RECIPES)
    args=parser.parse_args();raise SystemExit(run(args.recipe))
