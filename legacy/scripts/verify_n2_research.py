"""Evaluate frozen R3 acceptance; failures are never discarded or reweighted."""
from pathlib import Path
import argparse
import hashlib
import json
import math
from summarize_n2_research import compare


def read(path):return json.loads(path.read_text('utf-8'))


def dominates(a,b):
    pair=compare(a,b)
    safe=pair['maximum_service_fraction_regret']<=1e-8
    economic=pair['cost_change_fraction']<=1e-10
    carbon=pair['co2_change_fraction']<=1e-10
    strict=(pair['improved_cells']>0 or pair['cost_change_fraction'] < -1e-10 or pair['co2_change_fraction'] < -1e-10)
    return safe and economic and carbon and strict


def verify(directory):
    protocol=read(directory/'protocol.json');limits=protocol['acceptance']
    candidate_rule=protocol.get('candidate','rollout_guard')
    ph=hashlib.sha256((directory/'protocol.json').read_bytes()).hexdigest()
    errors=[];conditions=[];pairs=[];code_sets=[]
    for case in protocol['conditions']:
        folder=directory/case['id']
        if not (folder/'completion.json').exists():
            errors.append(case['id']+': incomplete');continue
        child=read(folder/'protocol.json')
        if child.get('parent_protocol_sha256')!=ph or child['conditions']!=[case] or child['rules']!=protocol['rules'] or child['method']!=protocol['method']:
            errors.append(case['id']+': protocol mismatch')
        provenance=read(folder/'provenance.json')
        code_sets.append({k:v for k,v in provenance['files'].items() if k.endswith('.py')})
        data={rule:read(folder/(case['id']+'__'+rule+'.json')) for rule in protocol['rules']}
        candidate=data[candidate_rule];reference=data[limits['reference']]
        for rule,result in data.items():
            label=case['id']+'/'+rule
            if [p['year'] for p in result['paths']]!=list(range(2025,protocol['end_year']+1)):
                errors.append(label+': incomplete annual path')
            if any(abs(r['max_residual'])>1e-6 or abs(r['cash_balance_residual_cny'])>max(.01,r['operating_resource_cost_cny']*1e-12)
                   or abs(r['construction_fund_residual_cny'])>.1 or abs(r['financing_transfer_residual_cny'])>.1 for r in result['paths']):
                errors.append(label+': conservation failure')
            for decision in result['decisions']:
                if not -1e-6<=decision['fee_cny']<=decision['budget_cny']+1e-5 or abs(decision['treasury_transfer_cny']+decision['contractor_receipt_cny'])>1e-6:
                    errors.append(label+': retention finance failure')
                if rule in ('rollout_guard','anchored_guard') and decision['reference'] is not None:
                    if any(v>decision['reference'][k]+1.0001e-8 for k,v in decision['chosen'].items()):
                        errors.append(label+': paired forecast rule violated')
            for row in result['paths']:
                fee=sum(d['fee_cny'] for d in result['decisions'] if d['year']==row['year'])
                if abs(row['resource_cost_cny']-row['operating_resource_cost_cny']-row['construction_cost_cny']-fee)>.02:
                    errors.append(label+': retention fee double counted or omitted')
            for cohort in result['terminal_cohorts']:
                if 'research_due' in cohort and not cohort['research_due']<=cohort['exit_year']<=cohort['research_deadline']<=cohort['research_natural']:
                    errors.append(label+': retirement deadline violation')
            if result['summary']['max_physical_residual']>1e-6:
                errors.append(label+': physical failure')
        current=compare(candidate,reference)
        for rule,result in data.items():
            if rule!=candidate_rule:pairs.append(compare(candidate,result))
        lookup={c['id']:c for c in reference['terminal_cohorts']}
        exit_delay=max(c['exit_year']-lookup[c['id']]['exit_year'] for c in candidate['terminal_cohorts'] if 'research_due' in c)
        times=read(folder/'summary.json');elapsed=next(r['elapsed_seconds'] for r in times if r['name']==candidate['name'])
        dominated=[rule for rule,result in data.items() if rule!=candidate_rule and dominates(result,candidate)]
        violations=[]
        for actual,maximum,name in [
            (current['maximum_service_fraction_regret'],limits['maximum_service_fraction_regret_each_condition'],'service'),
            (current['cost_change_fraction'],limits['maximum_cost_increase_fraction_each_condition'],'cost'),
            (current['co2_change_fraction'],limits['maximum_co2_increase_fraction_each_condition'],'CO2'),
            (current['terminal_managed_capacity_change_mw'],limits['maximum_terminal_managed_capacity_increase_mw'],'terminal_MW'),
            (exit_delay,limits['maximum_same_cohort_exit_delay_vs_reference_years'],'exit_date'),
            (elapsed,limits['maximum_wall_seconds_per_candidate_case'],'runtime')]:
            if not math.isfinite(actual) or actual>maximum:violations.append(name)
        conditions.append(dict(condition=case['id'],comparison=current,violations=violations,
            max_exit_delay_years=exit_delay,dominated_by=dominated,elapsed_seconds=elapsed,
            system_hard_service_limit_passed=candidate['summary']['maximum_service_fraction']<=protocol['method']['risk_limit']))
    if code_sets and any(x!=code_sets[0] for x in code_sets):errors.append('Different research code across validation cases')
    counts=dict(completed_conditions=len(conditions),
        positive_retention_saving=sum((c['comparison']['retention_reduction_fraction'] or 0)>1e-8 for c in conditions),
        at_least_five_percent_retention_saving=sum((c['comparison']['retention_reduction_fraction'] or 0)>=.05 for c in conditions),
        nondominated=sum(not c['dominated_by'] for c in conditions),
        hard_service_limit_passed=sum(c['system_hard_service_limit_passed'] for c in conditions))
    gates=dict(all_finished=len(conditions)==len(protocol['conditions']),technical=not errors,
        no_individual_violation=not any(c['violations'] for c in conditions),
        enough_material_improvements=counts['at_least_five_percent_retention_saving']>=limits['minimum_conditions_with_at_least_5_percent_retention_saving'],
        enough_positive_improvements=counts['positive_retention_saving']>=limits['minimum_conditions_with_positive_retention_saving'],
        enough_nondominated=counts['nondominated']>=limits['minimum_nondominated_conditions_against_all_controls'])
    report=dict(protocol_sha256=ph,gates=gates,counts=counts,technical_errors=errors,conditions=conditions,
        n2_empirical_gate_passed=all(gates.values()),n3_supported=False,human_review='pending',
        note='Internal conditional-method criteria only. Passing does not prove global novelty, system feasibility, or national policy validity.')
    (directory/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (directory/'comparisons.json').write_text(json.dumps(pairs,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('conditions',)},ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');args=p.parse_args()
    outcome=verify(Path(args.directory))
    raise SystemExit(0 if outcome['n2_empirical_gate_passed'] else 1)
