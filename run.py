"""One offline-first entry point for the consolidated A problem workspace."""
from pathlib import Path
import argparse, json, os, subprocess, sys, tempfile, time, unittest

ROOT=Path(__file__).resolve().parent

def script(name,*args):
    return subprocess.call([sys.executable,'-B','-X','utf8',str(ROOT/'scripts'/name),*args],cwd=ROOT)

def tests():
    # Repository-local fixtures also work under restricted desktop environments.
    parent=ROOT/'tmp/tests';parent.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(parent)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    start=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    out=ROOT/'outputs/validation';out.mkdir(parents=True,exist_ok=True)
    record=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        passed=result.wasSuccessful(),seconds=time.perf_counter()-start,python=sys.version)
    (out/'tests.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result.wasSuccessful() else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['audit','catalog','test','attachments','verify','prototype','baseline','reproduce-lb','status','q1','q2','q3'])
    parser.add_argument('--output-dir',default=None)
    parser.add_argument('--config',default=None)
    parser.add_argument('--recipe',choices=['national','trade','international','ai_trade'],default='trade')
    args=parser.parse_args()
    os.chdir(ROOT)
    if args.command=='test':return tests()
    if args.command=='q3':
        if args.config is None or (ROOT/args.config).resolve()==ROOT/'workflow/q3_pr14_inputs.json':
            return script('run_q3_pr14.py','--output-dir',args.output_dir or 'outputs/q3_pr14/current')
        return script('run_q3.py','--config',args.config,'--output-dir',args.output_dir or 'outputs/q3/p3_yx')
    if args.command=='q1':
        if args.config is None or (ROOT/args.config).resolve()==ROOT/'workflow/q3_pr14_inputs.json':
            return script('build_q1_pr14.py','--output-dir',args.output_dir or 'outputs/q1/pr14_aligned')
        if (ROOT/args.config).resolve()!=ROOT/'workflow/q1_inputs.json':
            parser.error('Unknown Q1 config')
        return script('build_q1.py','--output-dir',args.output_dir or 'outputs/q1/p1_yx')
    if args.command=='q2':
        if args.config is None or (ROOT/args.config).resolve()==ROOT/'workflow/q2_pr14_integration.json':
            return script('run_q2_pr14.py','--output-dir',args.output_dir or 'outputs/q2_pr14/integrated')
        national_configs={ROOT/'workflow/q2_national_design.json',ROOT/'workflow/q2_inputs.json'}
        if args.config is None or (ROOT/args.config).resolve() in national_configs:
            if args.config and (ROOT/args.config).resolve()==ROOT/'workflow/q2_inputs.json':
                print('Q2 common entry: q2_inputs.json remains the legacy candidate inventory. '
                      'Execution uses the separately reviewed q2_national_design.json and '
                      'q2_national_input_review.json; no candidate-inventory use is promoted. '
                      'For inventory-only checks use scripts/run_q2.py explicitly.',flush=True)
            return script('run_q2_national.py','--output-dir',args.output_dir or 'outputs/q2/p2_lb_national')
        return script('run_q2.py','--config',args.config,'--output-dir',args.output_dir or 'outputs/q2/p2_lb')
    if args.command=='reproduce-lb':return script('reproduce_lb.py',args.recipe)
    jobs={
        'audit':[('audit_workspace.py',)],
        'catalog':[('build_workspace_catalog.py',)],
        'attachments':[('build_attachments.py',)],
        'verify':[(n,) for n in ['build_verified_assessment.py','build_energy_assessment.py','build_gas_assessment.py',
            'build_four_dimension_assessment.py','build_electricity_inputs.py','run_demand_hindcast.py','run_asset_lifecycle_case.py',
            'build_data_catalog.py','build_history_readiness.py']],
        'prototype':[('run_agent_prototype.py',),('run_operation_windows.py',)],
        'baseline':[('build_foundation.py','--no-plots')],
        'status':[('workflow_status.py','--check-formal-inputs')],
    }
    if args.command=='verify':
        code=script('workflow_status.py','--check-formal-inputs')
        if code:return code
    for job in jobs[args.command]:
        code=script(*job)
        if code:return code
    return 0

if __name__=='__main__':raise SystemExit(main())
