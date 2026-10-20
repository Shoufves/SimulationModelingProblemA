"""Recompute unchanged historical-fit checks from a frozen research run.

This reports historical fit, not production admission or full answer completion.
All recorded sources must still match; a stale run cannot certify current code.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_q2_empirical_support import preflight,scope_inputs
from run_q2_national import loss
from energy_model.q2_statistics import bridge_diagnostics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(folder):
    result=json.loads((folder/'results.json').read_text('utf-8'))
    status=json.loads((folder/'status.json').read_text('utf-8'))
    if status['status']!='complete_conditional_experiment':
        raise ValueError('Incomplete research run')
    mismatched=[]
    for name,expected in result['source_sha256'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or digest(path)!=expected:
            mismatched.append(name)
    if mismatched:
        raise ValueError('Stale sources/code: '+', '.join(mismatched))
    data,design,_=preflight()
    cases={}
    for name in result['results']:
        path=folder/(name+'.json')
        case=json.loads(path.read_text('utf-8'))
        d,s,_,_,_,_=scope_inputs(data,design,case['parameters'],recovery_share=.5)
        for target in s['targets']:
            values=[d[y,target['observation']]*target['multiplier'] for y in s['training_years']
                    if (y,target['observation']) in d]
            target['scale']=target.get('absolute_scale') or sum(values)/len(values)*target['scale_from_training_mean_fraction']
        parts={}
        for split,years in [('training',s['training_years']),('already_seen_evaluation',s['evaluation_years'])]:
            value,components,_=loss(case['paths'],d,s,years,name)
            parts[split]=dict(loss=value,components=components)
        h={r['metric']:r for r in parts['already_seen_evaluation']['components']}
        train={r['metric']:r for r in parts['training']['components']}
        t=s['fit_acceptance']
        checks=dict(energy=h['primary_energy_tce']['mape']<=t['energy_mape'],
            generation=h['electricity_generation_mwh']['mape']<=t['generation_mape'],
            capacity=h['total_capacity_mw']['mape']<=t['capacity_mape'],
            wind_capacity=h['wind_capacity_mw']['mape']<=t['technology_capacity_mape'],
            solar_capacity=h['solar_capacity_mw']['mape']<=t['technology_capacity_mape'],
            structure=h['peo_share']['mae']<=t['peo_share_mae'],
            sparse_training_combustion=train['combustion_co2_t']['mape']<=t['combustion_mape_training_only'])
        for fuel in ('coal','oil','gas'):
            checks[fuel+'_share']=h[fuel+'_share']['n']==len(s['evaluation_years']) and h[fuel+'_share']['mae']<=t[fuel+'_share_mae']
            if fuel!='coal':checks[fuel+'_share_relative']=h[fuel+'_share']['mape']<=t['oil_gas_share_mape']
        bridge=[r for r in bridge_diagnostics(d,s) if r['split']=='already_seen_evaluation' and r['method']=='training_damped_trend']
        checks['statistical_bridge_historical_error']=bool(bridge) and max(abs(r['residual_share']) for r in bridge)<=t['peo_share_mae']
        persistence=[]
        for year in s['evaluation_years']:
            row=dict(year=year)
            for target in s['targets']:
                last=max(y for y in s['training_years'] if (y,target['observation']) in d)
                row[target['metric']]=d[last,target['observation']]*target['multiplier']
            persistence.append(row)
        baseline,baseline_parts,_=loss(persistence,d,s,s['evaluation_years'],'training_last_value')
        cases[name]=dict(file_sha256=digest(path),quality=parts,unchanged_fit_thresholds=t,
            fit_checks=checks,all_existing_fit_checks_passed=all(checks.values()),
            failed_checks=[k for k,v in checks.items() if not v],
            generation_by_technology=deepcopy(case['metrics']),
            persistence_baseline=dict(loss=baseline,components=baseline_parts),
            scientific_acceptance=False,team_approved=False,
            caveat='Existing aggregate checks do not certify all technology generation fits, future paths, policy identification or Q3/H01/H02.')
    return dict(reviewed_at=datetime.now(timezone.utc).isoformat(),
        reviewed_results_sha256=digest(folder/'results.json'),reviewer_sha256=digest(Path(__file__)),
        all_recorded_source_hashes_matched=True,evaluation_identity='already_seen_not_blind',cases=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    args=parser.parse_args()
    folder=(ROOT/args.folder).resolve()
    if not folder.is_relative_to(ROOT/'outputs'):
        raise ValueError('Review requires a repository output directory')
    output=review(folder)
    (folder/'fit_review.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
    lines=['# 当前收益实验的历史拟合复核','',
        '逐项核对来源与代码哈希，重新计算原有训练/评估指标和阈值。评估窗口已接触；不等于默认准入、正式预测或整题完成。','',
        '| 条件 | 原有阈值未通过项 | 评估损失 | 训练末值基线损失 |','|---|---|---:|---:|']
    for name,c in output['cases'].items():
        lines.append(f"| {name} | {', '.join(c['failed_checks']) or '无'} | {c['quality']['already_seen_evaluation']['loss']:.5f} | {c['persistence_baseline']['loss']:.5f} |")
    lines+=['','所有技术发电、装机、能源结构及稀疏排放指标见fit_review.json。原有聚合阈值没有覆盖所有技术发电误差，不能据聚合通过忽略分项失败。','']
    (folder/'fit_review.md').write_text('\n'.join(lines),'utf-8')
    print(json.dumps({k:v['failed_checks'] for k,v in output['cases'].items()},ensure_ascii=False))


if __name__=='__main__':main()
