"""Derive review tables without changing the frozen experiment or selecting anew."""
import csv
import json
from pathlib import Path
from run_q3 import load, dump, verify_latest, rank_key

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/q3/p3_yx'

def rows(name):
    with (OUT/name).open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))

def main():
    manifest=verify_latest(OUT)
    h=rows('h01_results.csv'); groups=[]; comparisons=[]
    for mode in sorted({r['project_mode'] for r in h}):
        for family in ('vR','vE'):
            for split in ('selection','test'):
                subset=[r for r in h if (r['project_mode'],r['family'],r['split'])==(mode,family,split)]
                scores=[]
                for rule in sorted({r['rule'] for r in subset}):
                    points=[r for r in subset if r['rule']==rule]
                    scores.append(dict(rule=rule,worst_loss=max(float(r['max_service_loss']) for r in points),
                        sum_cost_cny=sum(float(r['resource_cost_cny']) for r in points),
                        points=len(points),service_failures=sum(r['service_bound_passed']!='True' for r in points)))
                ranked=sorted(scores,key=lambda r:rank_key(r['worst_loss'],r['sum_cost_cny'],r['rule']))
                groups.append(dict(mode=mode,family=family,split=split,rule_ranking=ranked))
                for row in subset:
                    if row['rule']!='rolling_guard':continue
                    same=[r for r in subset if all(r[k]==row[k] for k in ('vR','vE','delay'))]
                    for ref in same:
                        if ref['rule']=='rolling_guard':continue
                        comparisons.append(dict(case=row['case'],reference=ref['rule'],
                            loss_reduction=float(ref['max_service_loss'])-float(row['max_service_loss']),
                            cost_reduction_cny=float(ref['resource_cost_cny'])-float(row['resource_cost_cny'])))
    p=rows('policy_tradeoffs.csv');base=next(r for r in p if r['policy']=='policy_0' and r['split']=='selection')
    selected=load(OUT/'policy_selection.json')['selected']
    best=next(r for r in p if r['policy']==selected and r['split']=='selection')
    sensitivity=[]
    for factor in (.5,1.5):
        subset=[r for r in rows('sensitivity.csv') if r['kind']=='policy_cost' and float(r['factor'])==factor]
        ranked=sorted(subset,key=lambda r:rank_key(float(r['event_worst_loss']),float(r['resource_cost_cny']),r['case']))
        sensitivity.append(dict(factor=factor,ranking=[r['case'] for r in ranked],all_event_loss_zero=all(float(r['event_worst_loss'])==0 for r in subset)))
    result=dict(run_id=manifest['run_id'],h01_groups=groups,rolling_guard_pairs=comparisons,
        h01_service_failed_points=sum(r['service_bound_passed']!='True' for r in h),h01_total=len(h),
        policy=dict(selected=selected,cost_reduction_cny=float(base['resource_cost_cny'])-float(best['resource_cost_cny']),
            cost_reduction_fraction=1-float(best['resource_cost_cny'])/float(base['resource_cost_cny']),
            cumulative_co2_reduction_t=float(base['cumulative_co2_t'])-float(best['cumulative_co2_t']),
            cumulative_co2_reduction_fraction=1-float(best['cumulative_co2_t'])/float(base['cumulative_co2_t']),
            public_commitment_cny=float(best['public_commitment_cny']),
            all_candidates_feasible=all(r['feasible']=='True' for r in p),
            test_ranking=[r['policy'] for r in sorted((r for r in p if r['split']=='test'),key=lambda r:rank_key(float(r['worst_loss']),float(r['resource_cost_cny']),r['policy']))]),
        cost_sensitivity=sensitivity,
        interpretation='Ranking is descriptive within the frozen finite conditions. Zero loss and J imply no demonstrated shortage-interaction or security improvement. Test cases were reused after implementation repairs.')
    dump(ROOT/'outputs/q3_review/findings.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rolling_guard_pairs','h01_groups')},ensure_ascii=False))

if __name__=='__main__':main()
