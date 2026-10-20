"""Combine completed local evidence; never issue the human C9 approval."""
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from run_q3 import ROOT,BASE,load,dump,sha,verify_latest

OUT=ROOT/'outputs/q3_review'

def main():
    dump(OUT/'acceptance.json',dict(passed=False,status='running',C9='pending_human_review'))
    try:
        manifest=verify_latest(ROOT/'outputs/q3/p3_yx')
        ledger=load(OUT/'ledger_checks.json');repro=load(OUT/'reproduction.json')
        tests=load(OUT/'tests.json');audit=load(OUT/'workspace_audit.json')
        formal=load(OUT/'formal_inputs.json');scan=load(OUT/'google_key_scan.json')['working_tree']
        q1=load(OUT/'q1_regression.json');q2=load(OUT/'q2_regression.json');protected=load(OUT/'protected_originals.json')
        if ledger['manifest_sha256']!=sha(ROOT/'outputs/q3/p3_yx/run_manifest.json'):raise ValueError('stale ledger review')
        if ledger['reviewer_sha256']!=sha(ROOT/'scripts/review_q3_delivery.py'):raise ValueError('ledger checker changed')
        if repro['checker_sha256']!=sha(ROOT/'scripts/compare_q3_runs.py'):raise ValueError('reproduction checker changed')
        if repro['left_manifest']!=ledger['manifest_sha256']:raise ValueError('different reproduction source')
        if repro['right_manifest']!=sha(OUT/'reproduction_manifest.json'):raise ValueError('changed reproduction receipt')
        checks={r['name']:r['passed'] for r in ledger['checks']}
        ancestry=subprocess.run(['git','merge-base','--is-ancestor',BASE,'HEAD'],cwd=ROOT).returncode==0
        conditions={
            'C1':ancestry and protected['passed'],
            'C2':checks['six_scenarios'] and load(ROOT/'outputs/q3/p3_yx/baseline_regression.json')['passed'],
            'C3':all(checks[k] for k in ('annual_cash_and_physics','public_budget','resource_cost_from_accounts','terminal_value_from_paid_assets','event_continuity','event_solver_residual')),
            'C4':checks['h01_all_grid_points'] and checks['fixed_committed_project_set'] and checks['actual_retirement_decisions'],
            'C5':checks['h02_independent_difference'],
            'C6':checks['selection_uses_no_test_outcome'] and checks['selection_test_disjoint'],
            'C7':tests['passed'] and tests['skipped']==0 and (ROOT/'tests/test_q3.py').exists(),
            'C8':tests['passed'] and audit['passed'] and formal['workflow_check']['passed'] and formal['formal_input_check']['passed'] and scan['passed'] and q1['passed'] and q2['passed'] and repro['passed'],
        }
        evidence={p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='acceptance.json'}
        result=dict(passed=all(conditions.values()),status='C1_C8_local_passed_C9_pending' if all(conditions.values()) else 'local_failed',
            generated_at=datetime.now(timezone.utc).isoformat(),base_sha=BASE,run_id=manifest['run_id'],
            C1_C8=conditions,C9='pending: two human approvals of the same final PR commit; at least one complete rerun',
            team_approved=False,official_attainment=False,scientific_scope='bounded conditional aggregate Q3 study',
            scientific_limits=['156/160 H01 points violate the frozen service bound','H02 and frozen response show zero shortage interaction',
                'Rolling rule ranking reverses on a predefined test case','No annual disaster calendar, province network, or real disaster probability is claimed',
                'Inherited Q2 calibration and observed-input limitations remain; reused test conditions are disclosed'],
            test_count=tests['tests'],reproduced_numeric_values=repro['numeric_values_compared'],
            executed_model_code_hashes=manifest['code_hashes'],evidence_sha256=evidence,
            provenance='Executed from the common base with disclosed uncommitted source; model hashes bind the results to the subsequently committed files.',
            checker_sha256=sha(Path(__file__)))
    except Exception as exc:result=dict(passed=False,status='failed',error=str(exc),C9='pending_human_review')
    dump(OUT/'acceptance.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('evidence_sha256','executed_model_code_hashes')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
