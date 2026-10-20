"""Independently recompute Q3 acceptance from exported ledgers and receipts."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import sys
import math

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_q3 import verify_latest,load,sha,dump,rank_key,csv_write


def read_csv(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def records(folder,kind):
    paths=sorted(folder.glob(kind+'_ledgers*.jsonl.gz'))
    if not paths:raise ValueError('Missing '+kind+' ledgers')
    for p in paths:
        with gzip.open(p,'rt',encoding='utf-8') as stream:
            for line in stream:yield json.loads(line)


def reconcile_retirement(record,metrics,config):
    """Derive actual exit dates from annual asset states, not reported counters."""
    exits={}
    for asset in sorted(record['assets'],key=lambda r:r['year']):
        if asset.get('kind')=='device' or not asset.get('q3_decision') or asset['status']!='retired':continue
        exits.setdefault(asset['id'],dict(year=asset['year'],natural=asset['exit_year'],mw=asset['capacity_mw']))
    events=[r for r in record['retirement'] if r['action']!='decision']
    if len(events)!=len(exits) or {r['cohort'] for r in events}!=set(exits):
        raise ValueError('Retirement events differ from actual asset exits')
    def same(a,b):
        return abs(float(a)-float(b))<=config['acceptance']['absolute_numeric_tolerance']+config['acceptance']['relative_numeric_tolerance']*max(abs(float(a)),abs(float(b)))
    for event in events:
        actual=exits[event['cohort']]
        if actual['year']>actual['natural']:raise ValueError('Actual asset exits after natural lifetime')
        expected='early_retired' if actual['year']<actual['natural'] else 'natural_retired'
        if event['action']!=expected:raise ValueError('Incorrect retirement classification: '+event['cohort'])
        if event['year']!=actual['year'] or event['natural_exit']!=actual['natural'] or not same(event['capacity_mw'],actual['mw']):
            raise ValueError('Retirement event contradicts asset history')
    for row in record['paths']:
        early=math.fsum(x['mw'] for x in exits.values() if x['year']<=row['year'] and x['year']<x['natural'])
        natural=math.fsum(x['mw'] for x in exits.values() if x['year']<=row['year'] and x['year']==x['natural'])
        if not same(row['q3_early_retired_mw'],early) or not same(row['q3_managed_natural_retired_mw'],natural):
            raise ValueError('Yearly cumulative retirement metric differs from actual exits')
    if not same(metrics['retired_early_mw'],early) or not same(metrics['managed_natural_retired_mw'],natural):
        raise ValueError('Terminal retirement metric differs from actual exits')
    return dict(early_retired_mw=early,managed_natural_retired_mw=natural,
        early_exit_events=sum(x['year']<x['natural'] for x in exits.values()),
        natural_exit_events=sum(x['year']==x['natural'] for x in exits.values()))


def audit(folder):
    m=verify_latest(folder);c=load(folder/'frozen_config.json');checks=[]
    def check(name,passed,detail):
        checks.append(dict(name=name,passed=bool(passed),detail=detail))
        if not passed:raise ValueError(name+': '+str(detail))
    check('frozen_base',m['base_sha']=='500436ffe8a9ecdf0ebcad3cdae87ef9deddbf93',m['base_sha'])
    coverage=load(folder/'experiment_coverage.json')
    assumptions=load(ROOT/'workflow/q2_national_design.json')['assumptions']
    metric_rows={r['case']:r for r in read_csv(folder/'h01_results.csv')}
    metric_rows.update({r['policy']:r for r in read_csv(folder/'policy_candidates.csv')})
    metric_rows.update({r['scenario']:r for r in read_csv(folder/'scenario_comparison.csv') if r['scope']=='2025-2060 annual path'})
    metric_rows.update({r['case']:r for r in read_csv(folder/'sensitivity.csv') if r['kind']=='policy_cost'})
    annual=set();max_cash=0;max_physical=0;max_public=0;early=0
    fixed_reference=None;fixed_cases=0;max_cost_residual=0;max_terminal_residual=0;retirement_cases=[];delay_cases=0
    for r in records(folder,'annual'):
        paths=r['paths'];case=r['case'];annual.add(case)
        retirement_cases.append(dict(case=case,**reconcile_retirement(r,metric_rows[case],c)))
        if r['spec']['study']=='h01':
            mode='fixed_committed_generation' if r['spec']['fixed_pipeline'] else 'full_agent_response'
            target=c['h01']['delay_targets'][mode]
            if r['spec']['delay_target']!=target or metric_rows[case]['delay_target']!=target:raise ValueError('H01 delay target mislabeled')
            if mode=='full_agent_response':
                for project in r['infrastructure']:
                    if project['online']-project['decision']!=assumptions[project['kind']+'_lead_years']+r['spec']['h01']['delay']:
                        raise ValueError('H01 infrastructure delay differs from declared target')
            delay_cases+=1
        if case=='S0':
            fixed_reference={x['id']:{k:x[k] for k in ('tech','capacity_mw','decision_year','cost','online_year')} for x in r['projects'] if x['initial_reconstruction']}
        if r['spec'].get('fixed_pipeline'):
            fixed_cases+=1
            if set(x['id'] for x in r['projects'])!=set(fixed_reference):raise ValueError('fixed project membership '+case)
            for x in r['projects']:
                expected=fixed_reference[x['id']]
                for key in ('tech','capacity_mw','decision_year','cost'):
                    if x[key]!=expected[key]:raise ValueError('fixed project changed '+case+' '+key)
                delay=r['spec']['h01']['delay'] if x['tech'] in ('wind','solar','hydro','nuclear') else 0
                if x['online_year']!=expected['online_year']+delay:raise ValueError('fixed project timing '+case)
            if r['infrastructure']:raise ValueError('new infrastructure in fixed control')
        check('year_sequence/'+case,[p['year'] for p in paths]==list(range(2025,paths[-1]['year']+1)),len(paths))
        for p in paths:
            for key in ('cash_balance_residual_cny','financing_transfer_residual_cny','infrastructure_fund_residual_cny','construction_fund_residual_cny'):
                max_cash=max(max_cash,abs(p[key]))
                if abs(p[key])>c['acceptance']['cash_absolute_tolerance_cny']+abs(p['resource_cost_cny'])*c['acceptance']['cash_relative_tolerance']:
                    raise ValueError(case+' cash '+key)
            if abs(p['positive_co2_t']-p['net_removals_t']-p['net_co2_t'])>.001:raise ValueError('carbon identity')
            max_physical=max(max_physical,p['max_residual'])
            amount=sum(x['amount_cny'] for x in r['public'] if x['year']==p['year'])
            if abs(amount-p['q3_public_commitment_cny'])>.1:raise ValueError('public ledger != path')
            max_public=max(max_public,amount/p['q3_public_budget_cny'])
            maintenance=math.fsum(x['amount_cny'] for x in r['public'] if x['year']==p['year'] and x['action']=='retention_maintenance')
            actual_cost=math.fsum(x.get('resource_cost_cny',0) for x in r['accounts'] if x['year']==p['year'])+maintenance
            error=abs(actual_cost-p['resource_cost_cny']);max_cost_residual=max(max_cost_residual,error)
            if error>c['acceptance']['cash_absolute_tolerance_cny']+abs(actual_cost)*c['acceptance']['cash_relative_tolerance']:raise ValueError('resource cost double count '+case)
            for x in (x for x in r['public'] if x['year']==p['year']):
                if abs(x['treasury_transfer_cny']+x.get('escrow_transfer_cny',0)+x.get('contractor_transfer_cny',0))>.1:raise ValueError('public transfer imbalance')
        for p in r['projects']:
            if not p['initial_reconstruction'] and p['online_year']<=p['decision_year']:raise ValueError('instant generation')
            if p['status']=='commissioned' and p['remaining']>.01:raise ValueError('unpaid generation')
        for p in r['infrastructure']:
            if p['online']<=p['decision']:raise ValueError('instant infrastructure')
            if p['online']<=paths[-1]['year'] and p['remaining']>.01:raise ValueError('unpaid infrastructure')
        for p in r['retirement']:
            if p['action']=='decision':
                if p['exit']>min(p['natural_exit'],p['deadline']):raise ValueError('illegal exit extension')
                if p['deadline']-p['request_year']>c['h01']['max_deferral_years']:raise ValueError('unbounded defer')
                early+=1
        end=paths[-1]['year'];terminal=0.0
        for x in r['assets']:
            if x['year']!=end or x['status']!='active':continue
            if x.get('kind')=='device':
                cost=x.get('paid_cost_cny',x['capacity']*assumptions['device_capex_cny_per_service_mw'])
                terminal+=cost*max(0,x['exit']-end)/max(1,x['exit']-x['online'])
            else:
                terminal+=x['capacity_mw']*x['book_cost_cny_per_mw']*max(0,x['exit_year']-end)/max(1,x['exit_year']-x['online_year'])
        for x in r['infrastructure']:
            terminal+=x['cost']-x['remaining'] if x['online']>end else x['cost']*max(0,min(1,(x['exit']-end)/max(1,x['exit']-x['online'])))
        terminal+=sum(x['cost']-x['remaining'] for x in r['projects'] if x['status']=='construction')
        terminal+=sum(x['paid_cost_cny'] for queue in r['devices'].values() for x in queue if x['online']>end)
        terminal+=paths[0]['grid_power_mw']*assumptions['grid_capex_cny_per_mw']*max(0,c['initial_year']+assumptions['grid_lifetime_years']-end)/assumptions['grid_lifetime_years']
        expected=float(metric_rows[case]['terminal_book_value_cny']);delta=abs(terminal-expected)
        max_terminal_residual=max(max_terminal_residual,delta)
        if delta>.1+abs(expected)*c['acceptance']['cash_relative_tolerance']:raise ValueError('terminal stock valuation '+case)
    check('annual_case_count',len(annual)==coverage['annual_cases'],len(annual))
    check('annual_cash_and_physics',max_physical<c['acceptance']['physical_residual_mwh'],dict(max_cash_cny=max_cash,max_physical_mwh=max_physical))
    check('public_budget',max_public<=1+1e-9,max_public)
    check('actual_retirement_decisions',early>0,early)
    check('retirement_metrics_from_asset_exit_years',len(retirement_cases)==coverage['annual_cases'],dict(
        cases=len(retirement_cases),managed_natural_cases=sum(r['managed_natural_retired_mw']>0 for r in retirement_cases),
        early_exit_events=sum(r['early_exit_events'] for r in retirement_cases),natural_exit_events=sum(r['natural_exit_events'] for r in retirement_cases)))
    check('h01_delay_targets_match_interventions',delay_cases==coverage['h01_cases'],delay_cases)
    check('fixed_committed_project_set',fixed_cases==coverage['h01_cases']//2,fixed_cases)
    check('resource_cost_from_accounts',True,dict(max_residual_cny=max_cost_residual,transfers_excluded=True))
    check('terminal_value_from_paid_assets',True,dict(max_residual_cny=max_terminal_residual,cases=len(metric_rows)))
    event={};max_storage=0;max_fuel=0;max_event_residual=0;events=0
    for r in records(folder,'event'):
        events+=1;case=r['case'];event[case]=r
        rows=r['rows'];storage=rows['storage']
        if len(storage)!=c['event']['days']*4:raise ValueError('event time count')
        for a,b in zip(storage,storage[1:]):max_storage=max(max_storage,abs(a['closing_mwh']-b['opening_mwh']))
        for row in rows['fuel']:
            if min(row['closing_mwh'],row['domestic_mwh'],row['import_mwh'])<-.001:raise ValueError('negative physical resource')
            if row['fuel']=='gas':
                if abs(row['channel_a_import_mwh']+row['other_import_mwh']-row['import_mwh'])>.001:raise ValueError('source gas double-count')
                source=rows['sources'][row['period']]
                if row['import_mwh']>(source['available_mw']+source['other_import_mw'])*6+.002:raise ValueError('import source envelope')
                if row['domestic_mwh']>source['domestic_mw']*6+.002:raise ValueError('domestic envelope')
        for fuel in sorted({x['fuel'] for x in rows['fuel']}):
            sequence=[x for x in rows['fuel'] if x['fuel']==fuel]
            for a,b in zip(sequence,sequence[1:]):max_fuel=max(max_fuel,abs(a['closing_mwh']+b['fill_mwh']-b['withdrawal_mwh']-b['closing_mwh']))
        # Independent grouping does not call the production metric function.
        grouped={}
        for x in rows['demand']:
            key=(x['sector'],x['period']);q,u=grouped.get(key,(0,0));grouped[key]=(q+x['requested_service_mwh'],u+x['unmet_service_mwh'])
        for metric in r['metrics']:
            seq=[grouped[metric['service'],i] for i in range(c['event']['days']*4)]
            q=sum(a for a,b in seq);u=sum(b for a,b in seq)
            if abs(q-metric['requested'])>max(.001,q*1e-10) or abs(u-metric['unmet'])>max(.001,u*1e-10):raise ValueError('service totals')
            duration=longest=0
            for a,b in seq:
                duration=duration+6 if b>max(c['acceptance']['shortage_absolute_mwh'],a*c['acceptance']['shortage_relative']) else 0
                longest=max(longest,duration)
            if longest!=metric['longest_interruption_hours']:raise ValueError('weighted false duration')
        max_event_residual=max(max_event_residual,r['max_residual'])
    check('event_continuity',max_storage<.002 and max_fuel<.002,dict(events=events,soc_mwh=max_storage,gas_mwh=max_fuel))
    check('event_solver_residual',max_event_residual<c['acceptance']['physical_residual_mwh'],max_event_residual)
    jrows=read_csv(folder/'h02_results.csv')
    for row in jrows:
        o=int(row['offset_days']);service=row['service'];values={}
        for mode in ('pair','frozen'):
            arms=[event[f'{mode}_{o}_{s}'] for s in ('S0','SG','SW','SGW')]
            if len({a['snapshot_hash'] for a in arms})!=1:raise ValueError('unpaired snapshot')
            nums=[next(x['unmet'] for x in a['metrics'] if x['service']==service) for a in arms]
            values[mode]=nums[3]-nums[1]-nums[2]+nums[0]
        for field,v in [('J_normal',values['pair']),('J_frozen',values['frozen']),('response_contribution',values['pair']-values['frozen'])]:
            if abs(float(row[field])-v)>max(.001,abs(v)*1e-10):raise ValueError('J recomputation')
    check('h02_independent_difference',True,len(jrows))
    check('h01_all_grid_points',len(read_csv(folder/'h01_results.csv'))==coverage['h01_cases'],coverage['h01_cases'])
    check('six_scenarios',set(x['scenario'] for x in read_csv(folder/'scenario_comparison.csv'))=={'S0','SP','SG','ST','SW','SGW'},'annual and event scopes separate')
    selection=load(folder/'policy_selection.json');tradeoffs=read_csv(folder/'policy_tradeoffs.csv')
    feasible=[r for r in tradeoffs if r['split']=='selection' and r['feasible']=='True']
    best=min(feasible,key=lambda r:rank_key(float(r['worst_loss']),float(r['resource_cost_cny']),r['policy']))['policy'] if feasible else None
    check('selection_uses_no_test_outcome',selection['selected']==best,selection)
    check('selection_test_disjoint',not(set(c['search']['selection_gas_offsets'])&set(c['search']['test_gas_offsets'])),'frozen before held-out events')
    return dict(passed=True,status='local_scientific_ledger_checks_passed',checks=checks,retirement_cases=retirement_cases,run_id=m['run_id'],
        manifest_sha256=sha(folder/'run_manifest.json'),reviewer_sha256=sha(Path(__file__)),C9='pending_human_review')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',default='outputs/q3/p3_yx');args=p.parse_args()
    out=ROOT/'outputs/q3_review';out.mkdir(exist_ok=True)
    result=dict(passed=False,status='running')
    dump(out/'ledger_checks.json',result)
    try:result=audit(ROOT/args.output_dir)
    except Exception as exc:result=dict(passed=False,status='failed',error=str(exc))
    dump(out/'ledger_checks.json',result);print(json.dumps(result,ensure_ascii=False))
    if result['passed']:csv_write(out/'retirement_metrics_recomputed.csv',result['retirement_cases'])
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
