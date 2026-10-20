"""PR14 annual extension of the frozen Q3 experiment, with the same paid actions."""
from copy import deepcopy
from types import MethodType

from energy_model.q2_forward_current import ForwardModel
from energy_model.q2_national import operate_national
from energy_model.q2_operations import Q2Error
from .services import service_key


def worst_service(operation, result):
    groups={}
    for r in result['demand']:
        q,u=groups.get(service_key(r),(0.0,0.0))
        groups[service_key(r)]=(q+r['requested_service_mwh'],u+r['unmet_service_mwh'])
    return max((u/q for q,u in groups.values() if q),default=0.0)


class TransitionModel(ForwardModel):
    def configure(self,config,*,scenario='S0',h01=None,policy=(),
                 cost_multiplier=1.0,fixed_pipeline=False):
        self.q3=deepcopy(config);self.scenario=scenario;self.h01=h01
        self.policy=tuple(policy);self.policy_cost_multiplier=cost_multiplier
        self.fixed_pipeline=fixed_pipeline
        self.public_ledger=[];self.retirement_log=[];self.approval_log=[]
        self.snapshots={};self.event_diversification=0.0;self.gas_contract=None
        self.request_history={}
        self.retired_early_mw=0.0
        self.managed_natural_retired_mw=0.0
        ordinary_approve=self.government.approve
        self.original_storage_capex=self.a['storage_capex_cny_per_mwh']
        if h01:
            for key in ('grid_lead_years','storage_lead_years'):self.a[key]+=h01['delay']
        def approve(gov,generation,devices):
            if fixed_pipeline:
                # All arms retain exactly the same paid/committed initial
                # generation project set; no extra electricity plants.
                generation=[dict(p,amount=0.0) for p in generation]
            self.request_history.setdefault(str(self.year),{}).update(generation=deepcopy(generation),devices=deepcopy(devices))
            if h01:
                for p in devices:
                    actor=gov.model.consumer_by_name[p['actor']]
                    if actor.fuel!='electricity':p['electric_fraction']=h01['vE']
            return ordinary_approve(generation,devices)
        self.government.approve=MethodType(approve,self.government)
        ordinary_enqueue=self.grid.enqueue
        def enqueue(grid,kind,request,capex,budget_fraction,lead,life):
            if fixed_pipeline:
                request=0.0
            self.request_history.setdefault(str(self.year),{}).setdefault('infrastructure',{})[kind]=request
            return ordinary_enqueue(kind,request,capex,budget_fraction,lead,life)
        self.grid.enqueue=MethodType(enqueue,self.grid)
        if fixed_pipeline:
            for p in self.projects:
                if p['tech'] in ('wind','solar','hydro','nuclear'):
                    delay=h01['delay'] if h01 else 0
                    p['q3_original_online']=p['online_year']
                    p['online_year']+=delay;p['exit_year']+=delay
                    p['instalment']=p['remaining']/max(1,p['online_year']-self.year)

    def synchronize_exits(self):
        # PR14 annual exposure and all investor screens read the actual exit.
        for c in self.cohorts:
            if 'q3_exit' in c:
                c['exit_year']=c['q3_exit']
        self.planning_cache={}

    def planning_operation(self,lead):
        self.synchronize_exits()
        return super().planning_operation(lead)

    def drivers(self):
        super().drivers()
        if self.scenario=='SP' and self.year>=self.q3['scenarios']['SP']['start_year']:
            self.carbon*=self.q3['scenarios']['SP']['carbon_multiplier']
        if self.scenario=='ST' and self.year>=self.q3['scenarios']['ST']['start_year']:
            self.a['storage_capex_cny_per_mwh']=self.original_storage_capex*self.q3['scenarios']['ST']['storage_cost_multiplier']

    def make_operation(self):
        op=super().make_operation()
        if self.gas_contract and self.year>=self.gas_contract['online']:
            self.event_diversification=self.gas_contract['fraction']
            op['fuels']['gas']['import_cost_per_mwh']*=1+self.event_diversification*self.q3['policy']['gas_premium_fraction']
        return op

    def mature(self):
        for c in self.cohorts:
            if c['status']=='active' and c.get('q3_exit',10**9)<=self.year:
                if self.year>c['q3_natural_exit']:
                    raise Q2Error('accounting_failure','Managed exit exceeds natural lifetime')
                c['status']='retired'
                if self.year<c['q3_natural_exit']:
                    action='early_retired';self.retired_early_mw+=c['capacity_mw']
                else:
                    action='natural_retired';self.managed_natural_retired_mw+=c['capacity_mw']
                self.retirement_log.append(dict(year=self.year,action=action,cohort=c['id'],
                    capacity_mw=c['capacity_mw'],natural_exit=c['q3_natural_exit'],
                    decision=c['q3_decision'],deadline=c['q3_deadline']))
        super().mature()

    def annual_public_spend(self,year):
        return sum(r['amount_cny'] for r in self.public_ledger if r['year']==year)

    def public_limit(self):
        return self.gdp_cny*self.q3['policy']['public_budget_gdp_fraction']

    def approve_public(self):
        """Paid requests enter inherited construction escrow; no instant assets."""
        if self.year!=self.q3['policy']['decision_year']:return
        a,p=self.a,self.q3['policy']
        remaining=max(0,self.public_limit()-self.annual_public_spend(self.year))
        requests=[]
        for kind in self.policy:
            if kind=='gas':
                power=self.suppliers['gas'].offer(record=False)['import_mw'][0]*p['gas_diversification_fraction']
                capex=p['gas_contract_capex_cny_per_mw']*self.policy_cost_multiplier
                lead=p['gas_contract_lead_years']
            else:
                power=self.grid.initial_power*p[kind+'_fraction']
                capex=(a['grid_capex_cny_per_mw'] if kind=='grid' else a['storage_duration_hours']*a['storage_capex_cny_per_mwh'])*self.policy_cost_multiplier
                lead=a[kind+'_lead_years']
                committed=sum(x['power'] for x in self.grid.queue if x['decision']==self.year and x['kind']==kind)
                limit=self.grid.initial_power*a[kind+'_build_fraction']*self.gdp/self.gdp0
                power=min(power,max(0,limit-committed))
            requests.append((kind,power,capex,lead))
        total=sum(power*capex for _,power,capex,_ in requests)
        ratio=min(1,remaining/total) if total else 1
        for kind,power,capex,lead in requests:
            power*=ratio;cost=power*capex
            if not power:continue
            # Entire cost irrevocably appropriated and committed this year.
            self.public_ledger.append(dict(year=self.year,action=kind,amount_cny=cost,
                treasury_transfer_cny=-cost,escrow_transfer_cny=cost,budget_cny=self.public_limit(),
                capacity_mw=power,decision=self.year,online=self.year+lead,source='additional conditional public appropriation'))
            if kind=='gas':
                desired=self.suppliers['gas'].offer(record=False)['import_mw'][0]*p['gas_diversification_fraction']
                self.gas_contract=dict(online=self.year+lead,cost=cost,remaining=cost,instalment=cost/lead,
                    decision=self.year,fraction=p['gas_diversification_fraction']*power/desired)
                continue
            self.grid.queue.append(dict(kind=kind,power=power,
                energy=power*a['storage_duration_hours'] if kind=='storage' else 0,
                decision=self.year,online=self.year+lead,exit=self.year+lead+a[kind+'_lifetime_years'],
                cost=cost,remaining=cost,instalment=cost/lead,q3_public=True))
            self.grid.reserved+=cost
            self.approval_log.append(dict(year=self.year,kind=kind,power_mw=power,
                cost_cny=cost,online=self.year+lead,status='approved_paid_commitment'))

    def forecast_risk(self,remove):
        horizon=self.q3['information']['forecast_horizon_years']
        risk=0.0
        for lead in range(1,horizon+1):
            op=deepcopy(self.planning_operation(lead))
            for tech in ('wind','solar'):
                op['plants'][tech]['availability']=[x*self.q3['information']['pressure_renewable_factor'] for x in op['plants'][tech]['availability']]
            # Same known pressure range for every forecast; no event calendar read.
            r=operate_national(op);risk=max(risk,worst_service(op,r))
        return risk

    def decide_retirement(self):
        if not self.h01:return
        h=self.q3['h01'];year=self.year;target=year+1;rule=self.h01['rule']
        if h['start_year']<=target<=h['last_request_year'] and self.h01['vR']:
            request=self.initial_capacities['coal']*self.h01['vR']
            eligible=[c for c in self.cohorts if c['tech']=='coal' and c['status']=='active'
                and not c.get('q3_decision') and target-c['online_year']>=h['eligible_age_years'] and c.get('q3_natural_exit',c['exit_year'])>target]
            eligible.sort(key=lambda c:(c.get('q3_natural_exit',c['exit_year']),c['id']))
            for c in eligible:
                amount=min(request,c['capacity_mw'])
                if amount<=1e-8:break
                if amount<c['capacity_mw']-1e-8:
                    piece=deepcopy(c);piece['id']=c['id']+'/q3/'+str(year);piece['capacity_mw']=amount
                    c['capacity_mw']-=amount;self.cohorts.append(piece);c=piece
                c.update(q3_natural_exit=c['exit_year'],q3_decision=year,q3_due=target,q3_exit=target,
                    q3_deadline=min(c.get('q3_natural_exit',c['exit_year']),target+h['max_deferral_years']))
                request-=amount
        due=[c for c in self.cohorts if c['status']=='active' and c.get('q3_exit')==target]
        if not due:return
        self.synchronize_exits()
        if rule=='cost_order':
            due.sort(key=lambda c:(c['book_cost_cny_per_mw']*(c.get('q3_natural_exit',c['exit_year'])-target)/max(1,c.get('q3_natural_exit',c['exit_year'])-c['online_year']),c['id']),reverse=True)
        # All candidates see the same prospective new retirement requests.
        risk=self.forecast_risk(due) if rule=='rolling_guard' else None
        replacement=False
        if rule=='replacement_ready':
            current=deepcopy(self.last_operation)
            plant=current['plants']['coal'];old=plant['capacity_mw']
            plant['capacity_mw']=max(0,old-sum(c['capacity_mw'] for c in due))
            plant['ramp_mw_per_hour']=plant['capacity_mw']*.2
            plant['window_energy_budget_mwh']*=plant['capacity_mw']/old if old else 0
            # Strong transparent comparator: already available devices/grid
            # and current service, with no unbuilt replacements counted.
            replacement=worst_service(current,operate_national(current))<=h['risk_limit']
        for c in due:
            delay=(rule=='rolling_guard' and risk>h['risk_limit']) or (rule=='replacement_ready' and not replacement)
            # Cost-order is a transparent avoid-stranding rule: preserve high
            # remaining book value only when cheaper than the frozen risk fee.
            if rule=='cost_order':
                book=c['book_cost_cny_per_mw']*(c.get('q3_natural_exit',c['exit_year'])-target)/max(1,c.get('q3_natural_exit',c['exit_year'])-c['online_year'])
                delay=book>h['retention_fee_cny_per_mw_year']*(c['q3_deadline']-target)
            fee=c['capacity_mw']*h['retention_fee_cny_per_mw_year']
            allowed=target<c['q3_deadline'] and self.annual_public_spend(year)+fee<=self.public_limit()
            if delay and allowed:
                c['q3_exit']=target+1
                self.public_ledger.append(dict(year=year,action='retention_maintenance',amount_cny=fee,
                    treasury_transfer_cny=-fee,contractor_transfer_cny=fee,budget_cny=self.public_limit(),
                    capacity_mw=c['capacity_mw'],decision=year,online=target))
            self.retirement_log.append(dict(year=year,action='decision',cohort=c['id'],rule=rule,
                capacity_mw=c['capacity_mw'],request_year=c['q3_due'],exit=c['q3_exit'],
                natural_exit=c.get('q3_natural_exit',c['exit_year']),deadline=c['q3_deadline'],risk_forecast=risk,
                delayed=bool(delay and allowed),delay_refused=bool(delay and not allowed)))

        self.synchronize_exits()

    def step(self):
        year=self.year
        # Inherited annual settlement/proposals/financing are performed first.
        super().step();self.year=year
        row=self.paths[-1]
        if year in {self.q3['snapshot_year'],self.q3['search']['snapshot_test_year']}:
            self.snapshots[year]=dict(operation=deepcopy(self.last_operation),year=year,
                electricity_value=self.a['retail_price_cny_per_mwh'],diversified_fraction=self.event_diversification)
        self.approve_public()
        # New public projects were proposed after the ordinary payment stage;
        # pay just their first instalment, never the old pipeline twice.
        added_cost=0.0
        for p in self.grid.queue:
            if p.get('q3_public') and p['decision']==year:
                payment=min(p['instalment'],p['remaining']);p['remaining']-=payment
                self.grid.reserved-=payment;added_cost+=payment
                self.finance.append(dict(year=year,kind='q3_public_construction',actor=p['kind'],
                    resource_cost_cny=payment,escrow_transfer_cny=-payment,construction_receipt_cny=payment))
        if self.gas_contract:
            c=self.gas_contract
            if c['decision']<=year<c['online']:
                payment=min(c['instalment'],c['remaining']);c['remaining']-=payment;added_cost+=payment
                self.finance.append(dict(year=year,kind='q3_contract_construction',actor='gas_diversification',
                    resource_cost_cny=payment,escrow_transfer_cny=-payment,construction_receipt_cny=payment))
            if year>=c['online']:
                if c['remaining']>.01:raise Q2Error('accounting_failure','Unpaid diversification contract')
                self.event_diversification=c['fraction']
        self.decide_retirement()
        maintenance=sum(p['amount_cny'] for p in self.public_ledger if p['year']==year and p['action']=='retention_maintenance')
        if self.annual_public_spend(year)>self.public_limit()+.1:raise Q2Error('accounting_failure','Q3 public budget exceeded')
        row['resource_cost_cny']+=added_cost+maintenance
        row['construction_cost_cny']+=added_cost
        row.update(q3_public_commitment_cny=self.annual_public_spend(year),q3_public_budget_cny=self.public_limit(),
            q3_extra_resource_cost_cny=added_cost+maintenance,q3_early_retired_mw=self.retired_early_mw,
            q3_managed_natural_retired_mw=self.managed_natural_retired_mw)
        row['infrastructure_reserved_cny']=self.grid.reserved
        row['infrastructure_fund_residual_cny']=self.grid.reserved-sum(p['remaining'] for p in self.grid.queue)
        self.year=year+1


def annual_metrics(model):
    # Aggregate only within each named service; no cross-service total score.
    by={}
    for r in model.operations:
        if r['kind']!='demand':continue
        key=(r['year'],service_key(r));q,u=by.get(key,(0.,0.))
        by[key]=(q+r['requested_service_mwh']*365,u+r['unmet_service_mwh']*365)
    risk=max((u/q for q,u in by.values() if q),default=0)
    end=model.year-1
    salvage=0.0
    for c in model.cohorts:
        if c['status']=='active':
            salvage+=c['capacity_mw']*c['book_cost_cny_per_mw']*max(0,c['exit_year']-end)/max(1,c['exit_year']-c['online_year'])
    for c in model.grid.queue:
        salvage+=c['cost']*max(0,min(1,(c['exit']-end)/max(1,c['exit']-c['online']))) if c['online']<=end else c['cost']-c['remaining']
    for p in model.projects:
        if p['status']=='construction':salvage+=p['cost']-p['remaining']
    # Include paid terminal devices. Initial cohorts use the disclosed Q2
    # reference unit cost; later cohorts carry their actual paid amount.
    for consumer in model.consumers.values():
        for p in consumer.cohorts:
            if p['status']=='active':
                cost=p.get('paid_cost_cny',p['capacity']*model.a['device_capex_cny_per_service_mw'])
                salvage+=cost*max(0,p['exit']-end)/max(1,p['exit']-p['online'])
        salvage+=sum(p['paid_cost_cny'] for p in consumer.queue if p['online']>end)
    initial_grid=model.grid.initial_power*model.a['grid_capex_cny_per_mw']
    salvage+=initial_grid*max(0,model.initial_year+model.a['grid_lifetime_years']-end)/model.a['grid_lifetime_years']
    return dict(resource_cost_cny=sum(r['resource_cost_cny'] for r in model.paths),
        terminal_book_value_cny=salvage,cost_less_terminal_book_value_cny=sum(r['resource_cost_cny'] for r in model.paths)-salvage,
        cumulative_co2_t=sum(r['positive_co2_t'] for r in model.paths),max_service_loss=risk,
        public_commitment_cny=sum(r['amount_cny'] for r in model.public_ledger),
        max_annual_public_fraction=max((r['q3_public_commitment_cny']/r['q3_public_budget_cny'] for r in model.paths),default=0),
        retired_early_mw=model.retired_early_mw,managed_natural_retired_mw=model.managed_natural_retired_mw,
        terminal_coal_mw=model.generators['coal'].capacity,
        terminal_queue_mw=model.paths[-1]['queue_mw'],max_residual=max(r['max_residual'] for r in model.paths),
        end_year=end,scope='annual conditional aggregate')
