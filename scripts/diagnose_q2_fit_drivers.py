"""Separate stock residuals and investment-economics gaps without new payments."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'src'))
from review_q2_revenue_candidate import review
from run_q2_empirical_support import preflight,scope_inputs
from energy_model.q2_national import LIFE,LEAD


def diagnose(folder):
    verified=review(folder)
    data,design,_=preflight();results={}
    groups={'hydro_including_pumped':'hydro_capacity_mw','nuclear':'nuclear_capacity_mw',
            'wind':'wind_capacity_mw','solar':'solar_capacity_mw'}
    for name in verified['cases']:
        case=json.loads((folder/(name+'.json')).read_text('utf-8'))
        d,s,*_=scope_inputs(data,design,case['parameters'],recovery_share=.5)
        stocks=[]
        for row in case['paths']:
            year=row['year'];components=[]
            for group,obs in groups.items():
                model=row[group+'_capacity_mw'];actual=d[year,obs]
                components.append(dict(group=group,model_mw=model,observed_mw=actual,residual_mw=model-actual))
            model_rest=row['total_capacity_mw']-sum(c['model_mw'] for c in components)
            observed_rest=d[year,'total_capacity_mw']-sum(c['observed_mw'] for c in components)
            components.append(dict(group='all_remaining_generation_and_recovery',model_mw=model_rest,
                observed_mw=observed_rest,residual_mw=model_rest-observed_rest))
            residual=row['total_capacity_mw']-d[year,'total_capacity_mw']
            if abs(sum(c['residual_mw'] for c in components)-residual)>1e-6:raise ValueError('Stock residual decomposition failed')
            stocks.append(dict(year=year,total_residual_mw=residual,components=components))
        economics=[]
        rate=s['assumptions']['discount_rate']
        for p in case['behavior']:
            if p['kind']!='investment_proposal':continue
            tech=p['actor'];annuity=p.get('expected_operating_pv_factor')
            if annuity is None:
                annuity=(1-(1+rate)**(-LIFE[tech]))/rate/(1+rate)**(LEAD[tech]-1)
            equivalent=max(0,-p['npv_cny_per_mw'])/annuity
            economics.append(dict(year=p['year'],technology=tech,npv_cny_per_mw=p['npv_cny_per_mw'],
                energy_only_npv_cny_per_mw=p['energy_only_npv_cny_per_mw'],support_npv_cny_per_mw=p['new_support_npv_cny_per_mw'],
                expected_net_annual_margin_cny_per_mw=p['expected_new_project_margin_cny_per_mw'],
                expected_operating_pv_factor=annuity,
                break_even_equal_annual_extra_net_margin_cny_per_mw=equivalent,
                requested_mw=p['requested_mw'],construction_limit_mw=p['construction_limit_mw'],
                finance_limit_mw=p['finance_limit_mw'],cash_cny=p['cash_cny']))
        results[name]=dict(capacity_residual_decomposition=stocks,investment_economics=economics,
            support_fund=[{key:row[key] for key in ('year','levy_receipts_cny','treasury_transfer_cny',
                'expenditure_limit_cny','new_entitlement_cny','paid_cny','closing_arrears_cny','closing_cash_cny')}
                for row in case['fund_history']],
            fit_checks=verified['cases'][name]['fit_checks'],generation_by_technology=case['metrics'])
    return dict(created_at=datetime.now(timezone.utc).isoformat(),
        status='diagnostic_not_new_calibration_or_policy_payment',cases=results,
        interpretation=['Capacity residuals are mutually exclusive observed aggregate groups; the remainder is not claimed to be pure coal',
            'Extra annual margin is an algebraic break-even equivalent over the assumed full project life, not an entitlement, subsidy quote or actual capacity fee',
            'Zero financing, negative NPV and construction constraints are separately reported; no cash/capacity is added',
            'All authority cases retained; already-seen evaluation was not used to select a case'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder');args=parser.parse_args()
    folder=(ROOT/args.folder).resolve()
    if not folder.is_relative_to(ROOT/'outputs'):raise ValueError('Expected output folder')
    result=diagnose(folder)
    (folder/'driver_diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
    lines=['# 装机与投资误差分解','',
        '所有承诺额度组分别报告。装机差为模型减观测；其他组含余下全部发电/回收类别，不能直接改名为纯煤电。','',
        '| 条件 | 年 | 总装机差 MW | 水电含抽蓄 | 核电 | 风电 | 光伏 | 其余类别 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,c in result['cases'].items():
        for r in c['capacity_residual_decomposition']:
            if r['year'] in (2021,2024):lines.append(f"| {name} | {r['year']} | {r['total_residual_mw']:.1f} | "+' | '.join(f"{x['residual_mw']:.1f}" for x in r['components'])+' |')
    lines+=['','## 气电收益与融资：补贴遗漏不能代替逐项核查','',
        '| 条件 | 年 | 预期年净收益 元/kW | 盈亏平衡还需年净收益 元/kW | 已有专项支持NPV 元/kW | 可融资新建 MW | 提议新建 MW |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name,c in result['cases'].items():
        for r in c['investment_economics']:
            if r['technology']=='gas' and r['year'] in (2015,2021,2024):
                lines.append(f"| {name} | {r['year']} | {r['expected_net_annual_margin_cny_per_mw']/1000:.2f} | "
                    f"{r['break_even_equal_annual_extra_net_margin_cny_per_mw']/1000:.2f} | {r['support_npv_cny_per_mw']/1000:.2f} | "
                    f"{r['finance_limit_mw']:.1f} | {r['requested_mw']:.1f} |")
    lines+=['','## 已实际进入模型的有限补贴基金','',
        '以下为条件模型的名义金额；模拟应计、支付和欠款不是企业实际到账观测。它们不能与社会资源成本重复相加。','',
        '| 条件 | 年 | 收入 亿元 | 当年新增应计 亿元 | 实付 亿元 | 年末欠款 亿元 | 年末现金 亿元 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name,c in result['cases'].items():
        for row in c['support_fund']:
            if row['year'] in (2021,2024):
                amounts=[row['levy_receipts_cny']+row['treasury_transfer_cny'],row['new_entitlement_cny'],
                         row['paid_cny'],row['closing_arrears_cny'],row['closing_cash_cny']]
                lines.append(f"| {name} | {row['year']} | "+' | '.join(f'{v/1e8:.2f}' for v in amounts)+' |')
    lines+=['','各技术逐年NPV、单独支持价值、现金与融资/建设限制见JSON。盈亏平衡所需年净收益是纯代数诊断，不是给模型添加的财政补贴或政策承诺。',
        '专项支持NPV为0只表示本接口没有额外给气电新能源补贴，不能推出真实容量收入为0；既有NEA收入等价均价可能已含部分固定收入，尚未取得同口径拆分。',
        '本候选2019—2024电价仍为2018名义价格延续，煤油气交付成本也是技术参考下的条件路径，不能把净收益缺口直接全归为政府支持不足。即使项目NPV转正，现金或融资不足仍能阻止新建。','']
    (folder/'driver_diagnostic.md').write_text('\n'.join(lines),'utf-8')
    print(folder.relative_to(ROOT).as_posix()+'/driver_diagnostic.md')


if __name__=='__main__':main()
