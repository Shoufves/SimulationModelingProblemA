"""Reproduce supplementary novelty-effectiveness and transparent text diagnostics.

Does not modify scientific models, simulate new policy conditions, or predict
AI authorship. Run from the repository root; original evidence is hash checked.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.research_diagnostics import (
    pooled_source_exposure, factorial_attribution, deployment_signature, text_profile,
    verify_evidence_claims)

BASE = '7d52f439992503eac5978c6f218f5289fe3e2195'
Q1 = ROOT/'outputs/q1/p1_yx'
Q3 = ROOT/'outputs/q3/p3_yx'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def unchanged_baseline():
    """Verify scientific outputs, code and original admission files against base."""
    names = set()
    for directory in (Q1, ROOT/'outputs/q2/p2_lb_national', Q3):
        manifest = read(directory/'run_manifest.json')
        names.update(manifest['code_hashes'])
        names.update((directory/name).relative_to(ROOT).as_posix() for name in manifest['outputs'])
        names.add((directory/'run_manifest.json').relative_to(ROOT).as_posix())
    names.update(['workflow/q1_inputs.json','workflow/q2_national_design.json','workflow/q3_inputs.json',
        'data/catalog/q1_input_review.json','data/catalog/q2_national_input_review.json',
        'data/catalog/q3_input_review.json','data/sources.json','data/evidence_reviews.json',
        'workflow/model_inputs.json','outputs/q3_review/acceptance.json'])
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'只读工作区').iterdir() if p.is_file())
    result = {}
    for name in sorted(names):
        expected = subprocess.check_output(['git','rev-parse',BASE+':'+name],cwd=ROOT,text=True).strip()
        actual = subprocess.check_output(['git','hash-object','--no-filters',name],cwd=ROOT,text=True).strip()
        if actual != expected:
            raise ValueError('Baseline scientific artifact changed: '+name)
        result[name] = dict(git_blob=actual,sha256=sha(ROOT/name))
    return result


def source_analysis():
    # Run the unchanged substantive Q1 admission checks before the new use.
    from build_q1 import preflight
    config = read(ROOT/'workflow/q1_inputs.json')
    preflight(config)
    selected = {r['id']:r for r in config['inputs'] if r['id'] in ('pipeline','lng')}
    modes = {name:rows(ROOT/spec['path']) for name,spec in selected.items()}
    if len(modes) != 2:
        raise ValueError('Missing reviewed transport mode')
    result = pooled_source_exposure(modes)
    source_key = next(iter(selected['pipeline']['source_map'].values()))
    artifact = config['sources'][source_key]['artifacts'][0]
    from openpyxl import load_workbook
    wb = load_workbook(ROOT/artifact['path'],read_only=True,data_only=True)
    verified = []
    try:
        for mode, parts in modes.items():
            for r in parts:
                actual = wb[r['sheet']][r['cell']].value
                if not isinstance(actual,(int,float)) or not math.isclose(actual,float(r['value']),rel_tol=1e-12,abs_tol=1e-10):
                    raise ValueError('Original workbook cell mismatch: '+r['sheet']+'!'+r['cell'])
                verified.append(dict(mode=mode,sheet=r['sheet'],cell=r['cell'],value=actual))
    finally:
        wb.close()
    result['workbook_verification'] = dict(path=artifact['path'],sha256=sha(ROOT/artifact['path']),cells=verified)
    result['processed_inputs'] = {s['path']:sha(ROOT/s['path']) for s in selected.values()}
    return result


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def policy_analysis():
    groups = {}
    annual_hashes = {}
    signatures = {}
    for file in sorted(Q3.glob('annual_ledgers_*.jsonl.gz')):
        with gzip.open(file,'rt',encoding='utf-8') as f:
            for line in f:
                ident = re.match(r'\{"case":"([^"]+)"',line)
                if not ident or not ident[1].startswith('policy_'):
                    continue
                record = json.loads(line)
                case = record['case']
                signatures[case] = deployment_signature(record['public'])
                annual_hashes[case] = canonical({k:v for k,v in record.items() if k not in ('case','spec')})
                family = 'base' if re.fullmatch(r'policy_\d',case) else case.rsplit('_',1)[0]
                groups.setdefault(family,{}).setdefault(signatures[case],[]).append(case)
    event_hashes = {}
    for file in sorted(Q3.glob('event_ledgers_*.jsonl.gz')):
        with gzip.open(file,'rt',encoding='utf-8') as f:
            for line in f:
                record = json.loads(line)
                if record['case'].startswith('policy_'):
                    event_hashes[record['case']] = canonical({k:v for k,v in record.items() if k != 'case'})
    classes = []
    pairs = []
    for family, grouped in sorted(groups.items()):
        for signature, members in grouped.items():
            members = sorted(members)
            first = members[0]
            for other in members[1:]:
                if annual_hashes[first] != annual_hashes[other]:
                    raise ValueError('Same deployment, different full annual ledger: '+other)
                events = ([k for k in event_hashes if k.startswith(first+'_')]
                          if family == 'base' else [first])
                if not events:
                    raise ValueError('Missing event for equivalent policy')
                for event in events:
                    counterpart = other+event[len(first):]
                    if event_hashes[event] != event_hashes[counterpart]:
                        raise ValueError('Equivalent policy events differ: '+event)
                    pairs.append(dict(first=event,other=counterpart,canonical_sha256=event_hashes[event]))
            classes.append(dict(family=family,members=members,public_commitments=json.loads(signature),
                annual_ledger_sha256=annual_hashes[first]))
    candidates = rows(Q3/'policy_candidates.csv')
    players = ('grid','storage','gas')
    definitions = [('resource_cost_saving_cny','resource_cost_cny',True),
                   ('co2_reduction_t','cumulative_co2_t',True),
                   ('annual_max_loss_reduction','max_service_loss',True),
                   ('public_commitment_cny','public_commitment_cny',False)]
    attribution = {}
    for label,field,subtract in definitions:
        original = {frozenset(json.loads(r['actions'])):float(r[field]) for r in candidates}
        baseline = original[frozenset()]
        values = {k:baseline-v if subtract else v for k,v in original.items()}
        calculation = factorial_attribution(values,players)
        bound = max(1e-9,16*math.ulp(max(1,max(abs(v) for v in original.values()))))
        if abs(calculation['efficiency_residual']) > bound:
            raise ValueError('Shapley efficiency failed')
        calculation.update(unit=label,roundoff_bound=bound,
            nonzero_interactions=[k for k,v in calculation['anchored_interactions'].items() if abs(v)>bound])
        attribution[label] = calculation
    h01 = rows(Q3/'h01_results.csv')
    matched = {}
    design_settings = set()
    for r in h01:
        design_settings.add(tuple(r[k] for k in ('project_mode','family','split','vR','vE','delay')))
        key = tuple(r[k] for k in ('project_mode','split','vR','vE','delay'))
        rules = matched.setdefault(key,{})
        if r['rule'] in rules:
            prior = rules[r['rule']]
            for field in ('max_service_loss','resource_cost_cny','retired_early_mw','managed_natural_retired_mw','service_bound_passed'):
                if prior[field] != r[field]:
                    raise ValueError('Duplicated physical H01 condition has different outcome')
        rules[r['rule']] = r
    comparisons = []
    for key,rules in sorted(matched.items()):
        if len(rules) != 4:
            raise ValueError('Incomplete four-rule H01 match')
        for comparator in ('schedule','cost_order','replacement_ready'):
            rolling = rules['rolling_guard']; simple = rules[comparator]
            loss_delta = float(rolling['max_service_loss'])-float(simple['max_service_loss'])
            cost_delta = float(rolling['resource_cost_cny'])-float(simple['resource_cost_cny'])
            comparisons.append(dict(group=key,comparator=comparator,rolling_loss_minus_comparator=loss_delta,
                rolling_cost_minus_comparator_cny=cost_delta,
                risk_order='better' if loss_delta < -1e-7 else 'worse' if loss_delta > 1e-7 else 'tie',
                rolling_within_service_bound=rolling['service_bound_passed']=='True'))
    counts = {name:{order:sum(r['comparator']==name and r['risk_order']==order for r in comparisons)
        for order in ('better','worse','tie')} for name in ('schedule','cost_order','replacement_ready')}
    replacement = [r for r in comparisons if r['comparator']=='replacement_ready']
    h02 = rows(Q3/'h02_results.csv')
    h01_summary = dict(labelled_rows=len(h01),
        labelled_service_bound_failures=sum(r['service_bound_passed']!='True' for r in h01),
        rolling_unique_feasible=sum(r['rolling_within_service_bound'] for r in replacement),
        replacement_cost_lower=sum(r['rolling_cost_minus_comparator_cny'] < -1 for r in replacement),
        replacement_cost_higher=sum(r['rolling_cost_minus_comparator_cny'] > 1 for r in replacement),
        replacement_cost_tie=sum(abs(r['rolling_cost_minus_comparator_cny']) <= 1 for r in replacement),
        replacement_max_abs_cost_delta_cny=max(abs(r['rolling_cost_minus_comparator_cny']) for r in replacement))
    return dict(implementation_classes=classes,annual_cases_checked=len(annual_hashes),
        unique_baseline_deployments=sum(r['family']=='base' for r in classes),nominal_baseline_policies=len(candidates),
        h01_design_labelled_settings=len(design_settings),h01_unique_physical_settings=len(matched),
        h01_summary=h01_summary,
        h02_max_abs_J=max(abs(float(r[k])) for r in h02 for k in ('J_normal','J_frozen')),
        event_pairs=pairs,attribution=attribution,h01_matched_comparisons=comparisons,h01_risk_order_counts=counts,
        interpretation='Post-result explanatory analysis. Equivalence is verified only for the frozen original conditions; no prospective runtime saving or universal effectiveness is claimed.')


def textual_analysis():
    corpus_paths = ['只读工作区/final.md','只读工作区/gemini_final_idea.md',
        'docs/solutions/p1-yx-integration.md','outputs/q3/p3_yx/report.md']
    corpus = {p:(ROOT/p).read_text(encoding='utf-8') for p in corpus_paths}
    targets = {'q1_original':'outputs/q1/p1_yx/report.md','q3_original':'docs/solutions/p3-yx.md',
        'q1_manuscript':'docs/paper/q1-evidence-analysis.md','q3_manuscript':'docs/paper/q3-innovation-analysis.md'}
    results = {}
    for name,path in targets.items():
        comparison_corpus = {p:t for p,t in corpus.items() if p != path}
        results[name] = dict(path=path,sha256=sha(ROOT/path),
            corpus_files={p:sha(ROOT/p) for p in comparison_corpus},
            **text_profile((ROOT/path).read_text(encoding='utf-8'),comparison_corpus))
    return dict(targets=results,classification='descriptive_not_authorship_detection',
        ai_use_disclosure='AI assisted code, analysis, drafting, validation and Git actions in this session; human choices and actual signed checks must be recorded separately.',
        before_after_limit='Different lengths and purposes: descriptive version comparisons, not a controlled detector-reduction experiment.',
        external_detection='not_run_no_platform_or_threshold_specified',human_validation='pending_actual_human_signature')


def evidence_analysis(destination):
    registry = read(ROOT/'docs/research/q1-q3-evidence.json')
    manuscripts = {p:(ROOT/p).read_text(encoding='utf-8') for p in registry['manuscripts']}
    def resolve(source):
        path = (destination/source['generated']) if 'generated' in source else (ROOT/source['file'])
        if path.suffix == '.csv':
            selected = [r for r in rows(path) if all(r[k]==v for k,v in source['where'].items())]
            if len(selected) != 1:
                raise ValueError('Evidence selector is not unique: '+str(source))
            return float(selected[0][source['field']])
        value = read(path)
        for key in source['keys']:
            value = value[key]
        return len(value) if source.get('operation')=='length' else value
    verified = verify_evidence_claims(registry['claims'],manuscripts,resolve)
    return dict(passed=True,claims=verified,
        scope='Registered numerical phrases only; not a substitute for human interpretation or literature verification.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir',default='outputs/research_audit/q1_q3')
    parser.add_argument('--science-only',action='store_true')
    args = parser.parse_args()
    destination = (ROOT/args.output_dir).resolve()
    if not destination.is_relative_to(ROOT/'outputs/research_audit'):
        raise ValueError('Output must stay in outputs/research_audit')
    destination.mkdir(parents=True,exist_ok=True)
    expected_files = {'run_manifest.json','q1_source_exposure.json','q3_effectiveness.json',
        'unchanged_baseline.json','text_metrics.json','evidence_checks.json'}
    if any(p.name not in expected_files for p in destination.iterdir()):
        raise ValueError('Non-diagnostic files in output directory; choose a dedicated empty directory')
    dump(destination/'run_manifest.json',dict(passed=False,status='running'))
    try:
        protected = unchanged_baseline()
        q1 = source_analysis(); dump(destination/'q1_source_exposure.json',q1)
        q3 = policy_analysis(); dump(destination/'q3_effectiveness.json',q3)
        dump(destination/'unchanged_baseline.json',dict(base=BASE,passed=True,files=protected))
        if not args.science_only:
            dump(destination/'text_metrics.json',textual_analysis())
            dump(destination/'evidence_checks.json',evidence_analysis(destination))
        scripts = ['scripts/audit_q1_q3_research.py','src/energy_model/research_diagnostics.py']
        docs = ['docs/research/q1-q3-audit-targets.md','docs/research/q1-q3-literature.json',
            'docs/research/q1-q3-evidence.json','docs/paper/q1-evidence-analysis.md',
            'docs/paper/q3-innovation-analysis.md'] if not args.science_only else []
        result = dict(passed=not args.science_only,
            status='partial_science_only' if args.science_only else 'computational_diagnostics_passed_external_and_human_pending',
            base=BASE,code_hashes={p:sha(ROOT/p) for p in scripts},
            input_hashes={p:sha(ROOT/p) for p in docs},
            execution=dict(python=sys.version,python_hash_seed=os.environ.get('PYTHONHASHSEED','unset')),
            outputs={p.name:sha(p) for p in destination.iterdir() if p.is_file() and p.name!='run_manifest.json'},
            scientific_novelty='No global-first or novel-algorithm claim; application increments evaluated separately.',
            formal_aigc_detector_percent=None,external_plagiarism_percent=None,human_validation='pending')
    except Exception as exc:
        result = dict(passed=False,status='failed',error=type(exc).__name__+': '+str(exc))
    dump(destination/'run_manifest.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('outputs','code_hashes')},ensure_ascii=False))
    return 0 if result.get('passed') or (args.science_only and result['status']=='partial_science_only') else 1


if __name__ == '__main__':
    raise SystemExit(main())
