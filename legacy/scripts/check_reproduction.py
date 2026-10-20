"""Run existing numerical/data entry points and keep concise execution evidence."""
from pathlib import Path
import argparse, importlib.metadata, json, platform, subprocess, sys, time

ROOT=Path(__file__).resolve().parents[1]
STEPS={
    'core':[['run.py','attachments'],['run.py','verify'],['run.py','prototype'],['run.py','baseline']],
    'yx':[['scripts/prepare_external_data.py'],['scripts/audit_data_package.py']],
    'lb':[['run.py','reproduce-lb','--recipe',r] for r in ('trade','international','ai_trade','national')],
}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('group',choices=[*STEPS,'all']);args=ap.parse_args()
    out=ROOT/'outputs/validation';out.mkdir(parents=True,exist_ok=True)
    env=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),packages={})
    for name in ('numpy','pandas','openpyxl','lxml','pypdf','pdfplumber','matplotlib','streamlit','scipy','mesa'):
        try:env['packages'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:env['packages'][name]=None
    (out/'environment.json').write_text(json.dumps(env,ensure_ascii=False,indent=2),encoding='utf-8')
    groups=list(STEPS) if args.group=='all' else [args.group]
    failures=[]
    for group in groups:
        results=[]
        for i,command in enumerate(STEPS[group]):
            start=time.perf_counter()
            proc=subprocess.run([sys.executable,'-B','-X','utf8',*command],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
            (out/f'{group}_{i+1}.log').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8')
            result=dict(command=command,returncode=proc.returncode,seconds=time.perf_counter()-start,log=f'{group}_{i+1}.log')
            results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
            if proc.returncode:failures.append(result)
        (out/f'reproduction_{group}.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return 1 if failures else 0

if __name__=='__main__':raise SystemExit(main())
