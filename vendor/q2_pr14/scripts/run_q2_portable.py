"""Question 2 offline re-execution from verified extracted input snapshots.

This is a new explicitly scoped adapter, not a bypass of the original runner's
raw-source checks. The compact mode verifies its own input/code hashes; complete
raw-document checks use run_q2_current_delivery.py in the full archive.
AI-assisted: OpenAI Codex/GPT-6, 2026-10-20; release date unavailable.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import sys
import math

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
from q2_delivery_snapshot import load,save,sha,decode,build_snapshot
from energy_model.q2_forward_current import activate_forward,forward_summary
from run_q2_national import targets,csv_write


def compare_reference(actual, expected):
    """Strict structure/discrete values; bounded roundoff for continuous fields."""
    report = dict(passed=True, differences=[], failures=[], numeric_fields=0,
                  tolerances=dict(relative=1e-12, cny_absolute=0.02,
                                  other_absolute=1e-6, cny_cap=0.02, other_cap=1e-3))

    def fail(path, reason):
        report['failures'].append(dict(path=path, reason=reason))

    def visit(a, b, path='', key=''):
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                fail(path, 'field sets differ')
            # Check conservation independently, even when both outputs agree.
            for label, row in (('actual', a), ('reference', b)):
                for field, limit in (
                    ('max_residual', 1e-6),
                    ('cash_balance_residual_cny', max(.01, abs(row.get('operating_resource_cost_cny', 0))*1e-12))):
                    if field in row:
                        value = row[field]
                        if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
                            fail(path+'/'+field, label+' conservation threshold exceeded')
            for k in sorted(set(a) & set(b)):
                visit(a[k], b[k], path+'/'+k, k)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                fail(path, 'list lengths differ')
            for i, (x, y) in enumerate(zip(a, b)):
                visit(x, y, path+'/'+str(i), key)
        elif (isinstance(a, (int, float)) and not isinstance(a, bool)
              and isinstance(b, (int, float)) and not isinstance(b, bool)):
            report['numeric_fields'] += 1
            if not math.isfinite(a) or not math.isfinite(b):
                fail(path, 'non-finite number')
                return
            discrete = key in {'year', 'peak_year', 'status'} or (type(a) is int and type(b) is int)
            money = key.endswith('_cny')
            absolute, cap = (.02, .02) if money else (1e-6, 1e-3)
            tolerance = 0 if discrete else min(cap, max(absolute, 1e-12*max(abs(a), abs(b))))
            delta = abs(a-b)
            if delta:
                report['differences'].append(dict(path=path, actual=a, expected=b,
                    absolute_difference=delta, tolerance=tolerance))
            if delta > tolerance:
                fail(path, 'numeric tolerance exceeded')
        elif type(a) is not type(b) or a != b:
            fail(path, 'type or nonnumeric value differs')

    visit(actual, expected)
    report['passed'] = not report['failures']
    report['exact_match'] = report['passed'] and not report['differences']
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--only",nargs="*");p.add_argument("--end-year",type=int,default=2060);p.add_argument("--verify-reference",action="store_true");args=p.parse_args()
    if not 2025 <= args.end_year <= 2060:p.error('--end-year must be within 2025..2060')
    data=ROOT/"data/processed/q2_delivery";manifest=load(data/"manifest.json")
    for rel,h in manifest["code_sha256"].items():
        if sha(ROOT/rel)!=h:raise ValueError("Code hash mismatch: "+rel)
    if sha(data/"parsed_inputs.json")!=manifest["inputs_sha256"] or sha(data/"q2_design.json")!=manifest["design_sha256"]:raise ValueError("Input snapshot mismatch")
    raw=load(data/"parsed_inputs.json");specs=load(data/"q2_design.json")["scenarios"]
    if args.only is not None:
        missing=set(args.only)-{s["name"] for s in specs}
        if missing:raise ValueError("Unknown Q2 cases: "+str(missing))
        specs=[s for s in specs if s["name"] in args.only]
    if not specs:raise ValueError("No cases selected")
    output=ROOT/"outputs/q2_portable"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ");output.mkdir(parents=True)
    print(output.relative_to(ROOT),flush=True);results=[]
    for original in specs:
        spec=dict(original);name=spec["name"];mode=spec.pop("thermal_mode","net58");authority=spec.pop("authority",25)
        opening=spec.pop("opening_variant",{})
        record=decode(raw[f"{mode}/{authority}"])
        model,assumptions,_=build_snapshot(record,authority,opening)
        activate_forward(model,record["config"],spec,end_year=args.end_year);model.run(args.end_year)
        tar,peak=targets(model.paths,model.data,model.design) if args.end_year==2060 else ([],{})
        result=dict(name=name,paths=model.paths,targets=tar,peak=peak,summary=forward_summary(model),
            evidence_mode=manifest["mode"],assumptions={**assumptions,**model.forward_assumptions})
        reference_path=ROOT/"data/processed/q2_delivery/reference_paths"/(name+".json")
        if args.verify_reference:
            ref=load(reference_path);expected=[r for r in ref["paths"] if r["year"]<=args.end_year]
            expected_result=dict(name=ref['name'], paths=expected, targets=ref['targets'] if args.end_year==2060 else [], peak=ref['peak'] if args.end_year==2060 else {})
            comparison=compare_reference({k:result[k] for k in expected_result},expected_result)
            result['reference_comparison']=comparison
            result['reference_exact_match']=comparison['exact_match']
            if not comparison['passed']:
                save(output/(name+'.json'),result)
                save(output/'verification.json',dict(status='failed',failed_case=name,
                    results=results,comparison=comparison,input_manifest_sha256=sha(data/'manifest.json'),raw_originals_reverified=False))
                return 1
        save(output/(name+".json"),result);csv_write(output/(name+"_path.csv"),model.paths)
        results.append(dict(name=name,status="success",reference_exact_match=result.get("reference_exact_match"),reference_comparison=result.get('reference_comparison'),summary=result["summary"]))
        print(name,"success",flush=True)
    save(output/"verification.json",dict(status="passed",cases=len(results),results=results,input_manifest_sha256=sha(data/"manifest.json"),raw_originals_reverified=False))
    print("COMPLETE",len(results),flush=True)
    return 0


if __name__=="__main__":raise SystemExit(main())
