"""Offline Q3 experiment, conservative failure receipts and finite case budget."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from run_q2_national import preflight as q2_preflight, load, sha, dump, csv_write, CODE as Q2_CODE
from energy_model.q2_national import NationalModel
from energy_model.q2_operations import Q2Error
from energy_model.q3_transition import TransitionModel, annual_metrics
from energy_model.q3_events import run_event, interaction, fingerprint

BASE='500436ffe8a9ecdf0ebcad3cdae87ef9deddbf93'
CODE=list(dict.fromkeys(Q2_CODE+['scripts/run_q3.py','src/energy_model/q3_transition.py','src/energy_model/q3_events.py']))


def preflight(config_path):
    c=load(config_path)
    if c['base_sha']!=BASE or c['scope']!='conditional_national_aggregate' or c['max_rounds']>10:
        raise Q2Error('invalid_input','Wrong base, scope or iteration budget')
    review_path=(ROOT/c['review']).resolve()
    if not review_path.is_relative_to(ROOT/'data/catalog') or sha(review_path)!=c['review_sha256']:
        raise Q2Error('unreviewed_input','Changed Q3 review')
    r=load(review_path)
    if r['status']!='author_reviewed_conditional_q3' or r['team_approved']:
        raise Q2Error('unreviewed_input','Q3 purposes withdrawn or false team approval')
    if set(r['allowed_uses'])!={'conditional_scenarios','conditional_events','h01','h02','bounded_policy_search'}:
        raise Q2Error('unreviewed_input','Q3 purpose missing')
    hashes={c['review']:sha(review_path)}
    for path,digest in r['products'].items():
        p=(ROOT/path).resolve()
        if not p.is_relative_to(ROOT) or p.is_relative_to(ROOT/'data/restricted') or sha(p)!=digest:
            raise Q2Error('changed_input','Changed/forbidden Q3 inherited product '+path)
        hashes[path]=digest
    for path,digest in r['inherited_code'].items():
        if path=='src/energy_model/q2_operations.py':continue # explicit optional free-SOC extension; regression checked
        if sha(ROOT/path)!=digest:raise Q2Error('changed_model','Unreviewed Q2 model change '+path)
    if set(c['scenarios'])!={'S0','SP','SG','ST','SW','SGW'} or c['scenarios']['S0']:
        raise Q2Error('invalid_input','Six named scenarios required')
    if c['initial_year']!=2024 or c['end_year']!=2060:
        raise Q2Error('invalid_input','National horizon changed')
    if len(c['policy']['candidates'])>c['search']['max_policy_candidates']:
        raise Q2Error('invalid_input','Policy search budget exceeded')
    if set(c['search']['selection_gas_offsets'])&set(c['search']['test_gas_offsets']):
        raise Q2Error('invalid_input','Selection/test overlap')
    for key in ('initial_year','end_year','snapshot_year'):
        if type(c[key])!=int:raise Q2Error('invalid_input','Non-integer year')
    for name,bounds in {'gas_loss_fraction':(0,1),'channel_a_share':(0,1),'wind_factor':(0,1),'solar_factor':(0,1),'hydro_factor':(0,1)}.items():
        v=c['event'][name]
        if type(v) not in (int,float) or not math.isfinite(v) or not bounds[0]<=v<=bounds[1]:raise Q2Error('invalid_input',name)
    for actions in c['policy']['candidates']:
        if len(actions)!=len(set(actions)) or set(actions)-{'grid','storage','gas'}:raise Q2Error('invalid_input','Invalid policy actions')
    for scenario,expected in {'SG':{'gas':True,'weather':False},'SW':{'gas':False,'weather':True},'SGW':{'gas':True,'weather':True}}.items():
        if c['scenarios'][scenario]!=expected:raise Q2Error('invalid_input','Scenario diff changed '+scenario)
    data,design,_=q2_preflight()
    theta=load(ROOT/'outputs/q2/p2_lb_national/calibration.json')['best']['parameters']
    return c,data,design,theta,hashes


def ledger(model):
    return dict(paths=model.paths,operations=model.operations,balances=model.balances,solver_stages=model.stages,
        accounts=model.finance,behavior=model.behavior,assets=model.assets,
        projects=model.projects,infrastructure=model.grid.queue,
        devices={k:v.queue for k,v in model.consumers.items()},public=model.public_ledger,
        retirement=model.retirement_log,public_approvals=model.approval_log)


def calculate_annual(payload):
    config,data,design,theta,spec=payload
    m=TransitionModel(data,design,theta,config,scenario=spec.get('scenario','S0'),
        h01=spec.get('h01'),policy=spec.get('policy',()),cost_multiplier=spec.get('cost_multiplier',1),
        fixed_pipeline=spec.get('fixed_pipeline',False)).run(spec.get('end_year',2060))
    return dict(spec=spec,metrics=annual_metrics(m),ledger=ledger(m),snapshots=m.snapshots)


def write_gzip(handle,record):
    handle.write((json.dumps(record,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode('utf-8'))


class LedgerArchive:
    """Deterministic small shards; never require a >100 MB Git blob."""
    def __init__(self,folder,kind):self.folder,self.kind,self.index,self.handle=folder,kind,0,None
    def __enter__(self):return self
    def write(self,data):
        if self.handle is None:
            self.index+=1
            self.handle=gzip.GzipFile(filename=str(self.folder/f'{self.kind}_ledgers_{self.index:03}.jsonl.gz'),mode='wb',mtime=0)
        self.handle.write(data)
        if self.handle.fileobj.tell()>24*1024*1024:
            self.handle.close();self.handle=None
    def __exit__(self,*args):
        if self.handle:self.handle.close()


def rank_key(loss,cost,label):
    # Differences below the predeclared numerical tolerance are ties, not a
    # scientific gain. Use the same stable comparison in every selection.
    return (round(loss,7),round(cost/1e9,3),label)


def baseline_check(paths,config):
    with (ROOT/'outputs/q2/p2_lb_national/baseline_path.csv').open(encoding='utf-8',newline='') as f:old=list(csv.DictReader(f))
    if len(old)!=len(paths):raise Q2Error('baseline_regression','Wrong baseline length')
    failed=[];max_relative=0.0
    for a,b in zip(paths,old):
        for k,v in a.items():
            if k not in b or not isinstance(v,(int,float)):continue
            expected=float(b[k]);error=abs(v-expected);scale=max(1,abs(v),abs(expected))
            # Financial cancellation residuals at trillion-CNY magnitude are
            # assessed against cash tolerance, not as tiny scientific outcomes.
            bound=(config['acceptance']['cash_absolute_tolerance_cny'] if 'residual' in k and 'cny' in k else
                config['acceptance']['absolute_numeric_tolerance']+config['acceptance']['relative_numeric_tolerance']*scale)
            if error>bound:failed.append(dict(year=a['year'],field=k,error=error,bound=bound))
            if 'residual' not in k:max_relative=max(max_relative,error/scale)
    if failed:raise Q2Error('baseline_regression',str(failed[:5]))
    return dict(passed=True,max_scientific_relative_difference=max_relative,years=len(paths))


def case_specs(c):
    specs=[dict(id=s,study='scenario',scenario=s,split='baseline') for s in ('S0','SP','ST')]
    h=c['h01']
    for fixed in (False,True):
        for family in ('vR','vE'):
            for speed in h['retirement_speeds' if family=='vR' else 'replacement_speeds']:
                for delay in h['delays']:
                    for rule in h['rules']:
                        options=dict(vR=speed if family=='vR' else h['fixed_retirement'],
                            vE=speed if family=='vE' else h['fixed_replacement'],delay=delay,rule=rule)
                        specs.append(dict(id=f'h01_{int(fixed)}_{family}_{speed}_{delay}_{rule}',study='h01',
                            family=family,split='selection',h01=options,fixed_pipeline=fixed,
                            end_year=h['fixed_pipeline_end'] if fixed else c['end_year']))
            for rule in h['rules']:
                options=dict(vR=h['test_retirement'] if family=='vR' else h['fixed_retirement'],
                    vE=h['test_replacement'] if family=='vE' else h['fixed_replacement'],delay=h['test_delay'],rule=rule)
                specs.append(dict(id=f'h01_test_{int(fixed)}_{family}_{rule}',study='h01',family=family,
                    split='test',h01=options,fixed_pipeline=fixed,end_year=h['fixed_pipeline_end'] if fixed else c['end_year']))
    for i,p in enumerate(c['policy']['candidates']):
        specs.append(dict(id=f'policy_{i}',study='policy',policy=p,split='selection'))
    for factor in c['policy']['test_cost_multipliers']:
        for i,p in enumerate(c['policy']['candidates']):
            specs.append(dict(id=f'policy_cost_{factor}_{i}',study='policy_cost',policy=p,
                cost_multiplier=factor,split='test'))
    return specs


def dominance(rows):
    for a in rows:
        a['dominated']=any(b['policy']!=a['policy'] and
            all(b[k]<=a[k] for k in ('worst_loss','resource_cost_cny','cumulative_co2_t')) and
            any(b[k]<a[k] for k in ('worst_loss','resource_cost_cny','cumulative_co2_t')) for b in rows)
    return rows


def run(config,data,design,theta,out):
    specs=case_specs(config);annual={};h01=[];scenario_paths=[];candidates=[]
    workers=max(1,min(4,int(os.environ.get('Q3_WORKERS','4'))))
    with LedgerArchive(out,'annual') as archive:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            jobs=((config,data,design,theta,s) for s in specs)
            for idx,result in enumerate(pool.map(calculate_annual,jobs)):
                spec=result['spec'];ident=spec['id'];m=result['metrics']
                write_gzip(archive,dict(case=ident,spec=spec,**result['ledger']))
                annual[ident]=dict(metrics=m,snapshots=result['snapshots'],spec=spec)
                if spec['study']=='scenario':
                    scenario_paths.extend(dict(scenario=ident,**r) for r in result['ledger']['paths'])
                    if ident=='S0':dump(out/'baseline_regression.json',baseline_check(result['ledger']['paths'],config))
                if spec['study']=='h01':h01.append(dict(case=ident,split=spec['split'],family=spec['family'],
                    project_mode='fixed_committed_generation' if spec['fixed_pipeline'] else 'full_agent_response',
                    **spec['h01'],**m,service_bound_passed=m['max_service_loss']<=config['policy']['annual_max_service_loss']))
                if spec['study']=='policy':candidates.append(dict(policy=ident,actions=spec['policy'],**m))
                if (idx+1)%8==0 or idx<3:print(f'annual {idx+1}/{len(specs)} {ident}',flush=True)
    csv_write(out/'scenario_paths.csv',scenario_paths);csv_write(out/'h01_results.csv',h01)
    csv_write(out/'policy_candidates.csv',candidates)
    # Pre-registered rule selection uses only selection cases; test rows do not
    # enter the ranking, even though all rules are disclosed on the test grid.
    rule_scores=[]
    for rule in config['h01']['rules']:
        rows=[r for r in h01 if r['rule']==rule and r['split']=='selection' and r['project_mode']=='full_agent_response']
        rule_scores.append(dict(rule=rule,worst_loss=max(r['max_service_loss'] for r in rows),
            total_cost=sum(r['resource_cost_cny'] for r in rows)))
    selected_rule=min(rule_scores,key=lambda x:rank_key(x['worst_loss'],x['total_cost'],x['rule']))['rule']
    dump(out/'h01_selection.json',dict(selected_rule=selected_rule,selection_scores=rule_scores,
        scope='finite disclosed grid; not universal superiority'))
    safety=[];comparisons=[];h02=[];policies=[];timings=[];diagnostic=[]
    base=annual['S0']['snapshots'][config['snapshot_year']]
    def collect(event,case,split,arc):
        write_gzip(arc,dict(case=case,split=split,**event))
        safety.extend(dict(case=case,split=split,scenario=event['scenario'],
            gas_min_inventory_mwh=event['gas_min_inventory_mwh'],storage_min_mwh=event['storage_min_mwh'],
            **m) for m in event['metrics'])
    cost_events=[]
    with LedgerArchive(out,'event') as arc:
        for offset in config['search']['selection_gas_offsets']+config['search']['test_gas_offsets']:
            split='selection' if offset in config['search']['selection_gas_offsets'] else 'test'
            arms={}
            for scenario in ('S0','SG','SW','SGW'):
                ev=run_event(base,config,scenario,gas_offset=offset);arms[scenario]=ev
                collect(ev,f'pair_{offset}_{scenario}',split,arc)
                if offset==0:comparisons.append(dict(scenario=scenario,scope='12-day continuous event',
                    resource_cost_cny=ev['resource_cost_cny'],co2_t=ev['combustion_co2_t'],
                    max_service_loss=max(m['loss_fraction'] for m in ev['metrics'] if m['loss_fraction'] is not None)))
            frozen={}
            for scenario in ('S0','SG','SW','SGW'):
                ev=run_event(base,config,scenario,gas_offset=offset,frozen_gas=arms['S0']['gas_response'])
                frozen[scenario]=ev;collect(ev,f'frozen_{offset}_{scenario}',split,arc)
            normal_j=interaction(arms);frozen_j=interaction(frozen)
            for service,j in normal_j.items():h02.append(dict(offset_days=offset,split=split,service=service,
                unit='MWh useful service',J_normal=j,J_frozen=frozen_j[service],response_contribution=j-frozen_j[service],
                snapshot_hash=arms['S0']['snapshot_hash'],frozen_response='gas-fired upward dispatch capped at paired S0 output'))
            timings.append(dict(offset_days=offset,split=split,worst_loss=max(x['loss_fraction'] for x in arms['SGW']['metrics'] if x['loss_fraction'] is not None)))
        # The worst selection timing is frozen before testing held-out conditions.
        worst=max((x for x in timings if x['split']=='selection'),key=lambda x:x['worst_loss'])['offset_days']
        for actions in ((),('grid',),('storage',),('withdrawal',),('grid','storage'),('storage','withdrawal')):
            ev=run_event(base,config,'SGW',gas_offset=worst,diagnostics=actions)
            collect(ev,'diagnostic_'+'+'.join(actions),'diagnostic_only',arc)
            diagnostic.append(dict(actions=actions,worst_loss=max(m['loss_fraction'] for m in ev['metrics'] if m['loss_fraction'] is not None),
                stock_unchanged=True,not_implementable_policy=True))
        for i,p in enumerate(config['policy']['candidates']):
            ident=f'policy_{i}';candidate=annual[ident]
            for split,offsets in (('selection',config['search']['selection_gas_offsets']),('test',config['search']['test_gas_offsets'])):
                for offset in offsets:
                    ev=run_event(candidate['snapshots'][config['snapshot_year']],config,'SGW',gas_offset=offset)
                    collect(ev,f'{ident}_{split}_{offset}',split,arc)
                    policies.append(dict(policy=ident,split=split,offset_days=offset,
                        snapshot_year=config['snapshot_year'],channel_share=config['event']['channel_a_share'],
                        event_worst_loss=max(m['loss_fraction'] for m in ev['metrics'] if m['loss_fraction'] is not None),
                        event_resource_cost_cny=ev['resource_cost_cny'],event_co2_t=ev['combustion_co2_t'],**candidate['metrics']))
            for share in config['search']['test_channel_shares']:
                ev=run_event(candidate['snapshots'][config['search']['snapshot_test_year']],config,'SGW',channel_share=share)
                collect(ev,f'{ident}_scope_{share}','test',arc)
                policies.append(dict(policy=ident,split='test',offset_days=0,snapshot_year=config['search']['snapshot_test_year'],channel_share=share,
                    event_worst_loss=max(m['loss_fraction'] for m in ev['metrics'] if m['loss_fraction'] is not None),
                    event_resource_cost_cny=ev['resource_cost_cny'],event_co2_t=ev['combustion_co2_t'],**candidate['metrics']))
            print(f'events policy {i+1}/{len(config["policy"]["candidates"])}',flush=True)
        for ident,candidate in annual.items():
            if candidate['spec']['study']!='policy_cost':continue
            ev=run_event(candidate['snapshots'][config['snapshot_year']],config,'SGW',gas_offset=worst)
            collect(ev,ident,'cost_sensitivity',arc)
            cost_events.append(dict(case=ident,kind='policy_cost',factor=candidate['spec']['cost_multiplier'],
                actions=candidate['spec']['policy'],event_worst_loss=max(m['loss_fraction'] for m in ev['metrics'] if m['loss_fraction'] is not None),**candidate['metrics']))
    baseline=annual['S0']['metrics'];tradeoffs=[]
    for split in ('selection','test'):
        group=[]
        for i in range(len(config['policy']['candidates'])):
            rows=[r for r in policies if r['policy']==f'policy_{i}' and r['split']==split];m=annual[f'policy_{i}']['metrics']
            loss=max(r['event_worst_loss'] for r in rows)
            checks=dict(event=loss<=config['policy']['event_max_service_loss'],
                annual=m['max_service_loss']<=config['policy']['annual_max_service_loss'],
                carbon=m['cumulative_co2_t']<=baseline['cumulative_co2_t']*config['policy']['carbon_ratio_limit'],
                cost=m['resource_cost_cny']<=baseline['resource_cost_cny']*config['policy']['resource_cost_ratio_limit'],
                public=m['max_annual_public_fraction']<=1+1e-10)
            group.append(dict(policy=f'policy_{i}',split=split,worst_loss=loss,feasible=all(checks.values()),failed_constraints=[k for k,v in checks.items() if not v],**m))
        tradeoffs+=dominance(group)
    feasible=[r for r in tradeoffs if r['split']=='selection' and r['feasible']]
    selected=min(feasible,key=lambda r:rank_key(r['worst_loss'],r['resource_cost_cny'],r['policy']))['policy'] if feasible else None
    dump(out/'policy_selection.json',dict(selected=selected,status='finite_candidate_selected' if selected else 'no_feasible_candidate',
        selected_rule=selected_rule,selection_worst_timing=worst,test_not_used_for_selection=True))
    for scenario in ('S0','SP','ST'):comparisons.append(dict(annual[scenario]['metrics'],scenario=scenario,scope='2025-2060 annual path'))
    csv_write(out/'scenario_comparison.csv',comparisons);csv_write(out/'safety_metrics.csv',safety)
    csv_write(out/'h02_results.csv',h02);csv_write(out/'timing_search.csv',timings);csv_write(out/'bottleneck_diagnostics.csv',diagnostic)
    csv_write(out/'policy_results.csv',policies);csv_write(out/'policy_tradeoffs.csv',tradeoffs)
    sensitivity=cost_events
    sensitivity += [dict(case=f'timing_{r["offset_days"]}',kind='held_out_timing',**r) for r in timings]
    csv_write(out/'sensitivity.csv',sensitivity)
    gaps=[dict(id='G1',scope='interpretation',status='inherited_limit',detail='Single-node conditional model; no province/network reliability or annual disaster probabilities'),
        dict(id='G2',scope='input',status='explicit_hypothesis',detail='Source A, weather, permits, public costs, risk limits are bounded conditional assumptions, not measured events'),
        dict(id='G3',scope='validation',status='inherited_limit',detail='Q2 already-seen evaluation, gas/oil/biomass generation residuals and carbon boundary persist'),
        dict(id='G4',scope='technology',status='excluded_quantified_claim',detail='No funded hydrogen/CCUS or AI/employment benefit claimed without eligible initial state'),
        dict(id='G5',scope='time',status='separate_scopes',detail='Event losses are separate tests; no annual disaster calendar is assumed or event cash fed back into annual paths'),
        dict(id='C9',scope='team',status='pending',detail='Two human reviews of final SHA required; no agent approval'),
        dict(id='OPT',scope='policy',status='selected' if selected else 'no_feasible_candidate',detail=str(selected))]
    csv_write(out/'gaps_and_conflicts.csv',gaps)
    summary=dict(annual_cases=len(specs),h01_cases=len(h01),h02_rows=len(h02),policy_event_cases=len(policies),
        selected_policy=selected,selected_rule=selected_rule,all_model_cases_executed=True,
        max_annual_residual=max(v['metrics']['max_residual'] for v in annual.values()),
        official_attainment=False,team_approved=False,scope='Issue12 conditional aggregate study')
    dump(out/'experiment_coverage.json',summary)
    report(out,summary,comparisons,h02,tradeoffs,diagnostic)
    return summary


def report(out,s,comparisons,h02,tradeoffs,diagnostic):
    lines=['# 问题三：有界条件情景与政策实验','',
        '共同 base `'+BASE+'`。全部结果沿用问题二模型的聚合、已接触评估及统计边界；不作真实灾害概率或官方认证。','',
        f'执行{s["annual_cases"]}条年度路径、{s["h01_cases"]}个H01点、{s["policy_event_cases"]}个政策事件点。',
        f'选择集优选规则：`{s["selected_rule"]}`；可行政策：`{s["selected_policy"]}`。None表示给定边界无可行方案，不放宽约束。','',
        '## 场景结果','', '| 情景/范围 | 最大服务缺供率 | 资源费用（元，范围内） |','|---|---:|---:|']
    for r in comparisons:lines.append(f'|{r["scenario"]} / {r["scope"]}|{r["max_service_loss"]:.6%}|{r["resource_cost_cny"]:.6g}|')
    lines+=['','长期路径和12天事件绝不相加。各服务单位分开；最大归一缺供率只作同条件筛选。恢复为缺供清零连续24小时，未恢复以右删失保留。',
        '','## H01/H02 与创新','',
        'H01分开vR×L与vE×L，固定已承诺发电项目和完整主体响应分表；前者仅移动同一组清洁在建项目的投运时点，终端设备继续按vE更新。退出最多延期3年且不越自然寿命，无免费延寿。滚动规则与固定日程、成本规则、当前设备可用后退出规则同信息比较。',
        'H02报告正常与限制气电向上调整两组J。冻结不增加资源、不降低服务或重置库存；J本身不等于传播证明。',
        f'本次最大绝对J为{max(abs(r["J_normal"]) for r in h02):.6g} MWh（不同服务不相加）；最大响应贡献为{max(abs(r["response_contribution"]) for r in h02):.6g} MWh。',
        '有限时序枚举和滚动安全审查为已有文档方法的工程实现；不声称算法首创。预先指定检验条件不用于选择，但因实现修复已再次运行，不冒称未接触盲测。零效应或排名不稳均保留。',
        '','## 五方面建议与可实施边界','',
        '| 方向 | 动作与证据 | 支付、工期及限制 |','|---|---|---|',
        '|能源结构|按h01_results检查退出节奏和配套滞后|有限保留费、自然寿命、三年延期上限；不延到2060后规避|',
        '|多能调度|按h02_results和bottleneck_diagnostics检查共享气源、储能、电网|诊断增容不是政策；正式新增进入付款队列，空储能不生成能源|',
        '|储备应急|按policy_results检查来源分散与提取瓶颈|假设合同有费用、两年生效；不把提高提取率当新增库存|',
        '|市场机制|SP只改碳价，保留既有覆盖/配额与结算|非覆盖终端不虚构征税；公共投资有共同年度上限|',
        '|科技应用|ST仅改新储能成本；部署见storage候选|成本下降为外部条件，设备要融资建设；无证据不量化氢/CCUS突破|',
        '','完整资金、建设、退出、连续燃料/设备和守恒账在annual_ledgers_*.jsonl.gz与event_ledgers_*.jsonl.gz。',
        '复现：`python -B -X utf8 run.py q3 --config workflow/q3_inputs.json --output-dir outputs/q3/p3_yx`。',
        '两位成员正式评审待完成；本文件不签发团队验收。']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,4))
    for split,marker in (('selection','o'),('test','x')):
        rows=[r for r in tradeoffs if r['split']==split]
        ax.scatter([r['resource_cost_cny']/1e12 for r in rows],[r['worst_loss']*100 for r in rows],label=split,marker=marker)
    ax.set(xlabel='2025-2060 resource cost (trillion 2024 CNY)',ylabel='Worst event service loss (%)',title='Finite policy candidates; no probability weights')
    ax.legend();fig.tight_layout();fig.savefig(out/'policy_tradeoffs.png',dpi=140);plt.close(fig)


def verify_latest(out):
    out=Path(out);latest=load(out.parent/(out.name+'.latest-attempt.json'));m=load(out/'run_manifest.json')
    if not latest.get('valid') or m['status']!='success_conditional_study' or latest['run_id']!=m['run_id'] or latest['manifest_sha256']!=sha(out/'run_manifest.json'):
        raise Q2Error('stale_success','Latest Q3 attempt is not valid')
    if m['code_hashes']!={p:sha(ROOT/p) for p in CODE}:raise Q2Error('changed_code','Q3 code changed')
    config_path=ROOT/m['config_path']
    if sha(config_path)!=m['config_sha256']:raise Q2Error('changed_input','Q3 config changed')
    _,_,_,_,hashes=preflight(config_path)
    if m['input_hashes']!=hashes:raise Q2Error('changed_input','Q3 inputs changed')
    for name,digest in m['outputs'].items():
        if sha(out/name)!=digest:raise Q2Error('changed_output',name)
    return m


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--config',default='workflow/q3_inputs.json');p.add_argument('--output-dir',default='outputs/q3/p3_yx')
    args=p.parse_args(argv);out=(ROOT/args.output_dir).resolve();cfg=(ROOT/args.config).resolve()
    if out.parent!=ROOT/'outputs/q3':raise ValueError('Q3 output must be directly under outputs/q3')
    if not cfg.is_relative_to(ROOT):raise ValueError('Config outside repository')
    latest=out.parent/(out.name+'.latest-attempt.json');out.parent.mkdir(parents=True,exist_ok=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');start=time.perf_counter()
    # Mark invalid before admission; yesterday's success cannot mask a failure.
    dump(latest,dict(run_id=run_id,status='running',valid=False))
    if out.exists():
        old=load(out/'run_manifest.json')
        if old.get('owner')!='p3/yx':raise ValueError('Refusing to replace unowned output')
        previous=out.parent/(out.name+'.attempts')/old['run_id'];previous.parent.mkdir(exist_ok=True)
        shutil.move(str(out),str(previous))
    out.mkdir();manifest=dict(run_id=run_id,owner='p3/yx',status='running',base_sha=BASE,team_approved=False,
        config_path=cfg.relative_to(ROOT).as_posix(),command=[Path(sys.argv[0]).name,*sys.argv[1:]],python=sys.version)
    dump(out/'run_manifest.json',manifest)
    try:
        config,data,design,theta,hashes=preflight(cfg)
        manifest.update(config_sha256=sha(cfg),input_hashes=hashes,code_hashes={p:sha(ROOT/p) for p in CODE},
            git_sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip(),
            dirty=bool(subprocess.run(['git','status','--porcelain'],cwd=ROOT,capture_output=True,text=True).stdout),
            dependencies={k:importlib.metadata.version(k) for k in ('numpy','scipy','mesa','pandas','matplotlib')})
        dump(out/'frozen_config.json',config)
        summary=run(config,data,design,theta,out)
        manifest.update(status='success_conditional_study',coverage=summary)
        returncode=0
    except Exception as exc:
        manifest.update(status='failed',error_type=type(exc).__name__,error=str(exc),failure_status=getattr(exc,'status','execution_error'))
        print(json.dumps({k:manifest[k] for k in ('status','error_type','error')},ensure_ascii=False),flush=True);returncode=1
    finally:
        manifest['elapsed_seconds']=time.perf_counter()-start
        manifest['outputs']={f.name:sha(f) for f in sorted(out.iterdir()) if f.is_file() and f.name!='run_manifest.json'}
        dump(out/'run_manifest.json',manifest)
        dump(latest,dict(run_id=run_id,status=manifest['status'],valid=manifest['status']=='success_conditional_study',manifest_sha256=sha(out/'run_manifest.json')))
    print(json.dumps(dict(status=manifest['status'],seconds=manifest['elapsed_seconds'])),flush=True)
    return returncode


if __name__=='__main__':raise SystemExit(main())
