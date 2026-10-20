"""Paired service/year retirement screening on the unchanged PR14 mechanics.

Research assumptions, NOT calibrated policy or a guarantee of feasibility.
AI-assisted method/code/experiments; human scientific review remains required.
"""
from copy import deepcopy
from math import fsum, isfinite
from types import MethodType
from energy_model.q2_forward_current import ForwardModel
from energy_model.q2_national import operate_national

RULES = ('schedule', 'cost_order', 'capacity_ready', 'replacement_ready',
         'rolling_guard', 'paired_myopic', 'paired_guard')


def services(result):
    groups = {}
    for row in result['demand']:
        item = groups.setdefault(row['sector'], dict(requested=0., unmet=0.))
        item['requested'] += row['requested_service_mwh']
        item['unmet'] += row['unmet_service_mwh']
    for item in groups.values():
        item['fraction'] = item['unmet']/item['requested'] if item['requested'] else 0.
    return groups


class RetirementModel(ForwardModel):
    def settle(self, op, result):
        row, margins = super().settle(op, result)
        self.research_services.append(dict(year=self.year, services=services(result)))
        return row, margins

    def forecast(self, due, retained, *, horizon):
        saved = [c['exit_year'] for c in due]
        old_cache = self.planning_cache
        try:
            for c in due:
                c['exit_year'] = self.year+1+int(c['id'] in retained)
            self.planning_cache = {}
            cells = {}
            for lead in range(1, horizon+1):
                op = self.planning_operation(lead)
                for t in ('wind', 'solar'):
                    op['plants'][t]['availability'] = [x*self.research['pressure'] for x in op['plants'][t]['availability']]
                result = operate_national(op)
                self.research_solves += 1
                for sector, values in services(result).items():
                    cells[str(self.year+lead)+'/'+sector] = values['fraction']
            if not all(isfinite(v) and -1e-9 <= v <= 1+1e-9 for v in cells.values()):
                raise ValueError('Invalid service forecast: '+repr(cells))
            return cells
        finally:
            for c, exit_year in zip(due, saved):
                c['exit_year'] = exit_year
            self.planning_cache = old_cache

    def retirement_decision(self):
        cfg = self.research
        target = self.year+1
        due = sorted([c for c in self.cohorts if c.get('research_due') is not None
                      and c['status'] == 'active' and c['exit_year'] == target], key=lambda c:c['id'])
        if not due:
            return 0.
        candidates = [c for c in due if target < c['research_deadline']]
        budget = self.gdp_cny*cfg['public_budget_fraction']
        # Same legal, finite, publicly known action set in every arm.
        allowed = []
        for c in candidates:
            fee = c['capacity_mw']*cfg['retention_fee']
            if fsum(x['capacity_mw']*cfg['retention_fee'] for x in allowed)+fee <= budget:
                allowed.append(c)
        retained = {c['id'] for c in allowed}
        rule = cfg['rule']
        reference = chosen = None
        evaluations = []
        if rule == 'schedule':
            retained = set()
        elif rule == 'cost_order':
            retained = {c['id'] for c in allowed
                        if c['book_cost_cny_per_mw']*(c['research_natural']-target)
                        /max(1,c['research_natural']-c['online_year'])
                        > cfg['retention_fee']*(c['research_deadline']-target)}
        elif rule == 'capacity_ready':
            # Conventional engineering comparator: 15% margin over electric
            # input peak, derated by minimum period availability; no free fuel.
            op = self.planning_operation(1)
            peak = max(fsum(d['service_mwh'][i]/d.get('efficiency',1.)/p['hours']
                            for d in op['demands'].values() if d['carrier']=='electricity')
                       for i,p in enumerate(op['periods']))
            firm = fsum(p['capacity_mw']*min(p['availability']) for p in op['plants'].values())
            if firm >= 1.15*peak:
                retained = set()
        elif rule in ('replacement_ready', 'rolling_guard'):
            horizon = 1 if rule == 'replacement_ready' else cfg['horizon']
            chosen = self.forecast(due,set(),horizon=horizon)
            if max(chosen.values()) <= cfg['risk_limit']:
                retained = set()
        else:
            horizon = 1 if rule == 'paired_myopic' else cfg['horizon']
            reference = self.forecast(due,retained,horizon=horizon)
            chosen = reference
            # Release the most costly cohort first, accepting only a complete
            # service/year vector check. No sum across heterogeneous services.
            for c in sorted(allowed,key=lambda c:(-c['capacity_mw'],c['id'])):
                trial = retained-{c['id']}
                outcome = self.forecast(due,trial,horizon=horizon)
                ceilings = {k:max(cfg['risk_limit'],v) for k,v in reference.items()}
                accept = all(outcome[k] <= ceilings[k]+cfg['tolerance'] for k in reference)
                evaluations.append(dict(released=c['id'], accepted=accept,
                                        max_excess=max(outcome[k]-ceilings[k] for k in reference)))
                if accept:
                    retained, chosen = trial, outcome
        fee = fsum(c['capacity_mw']*cfg['retention_fee'] for c in due if c['id'] in retained)
        if fee > budget+1e-5:
            raise ValueError('Retention budget exceeded')
        for c in due:
            if c['id'] in retained:
                c['exit_year'] += 1
            if c['exit_year'] > c['research_deadline']:
                raise ValueError('Lifetime/maximum deferral exceeded')
        self.planning_cache = {}
        self.research_decisions.append(dict(year=self.year,rule=rule,
            due=[c['id'] for c in due],retained=sorted(retained),
            deferred_mw=fsum(c['capacity_mw'] for c in due if c['id'] in retained),
            fee_cny=fee,budget_cny=budget,treasury_transfer_cny=-fee,contractor_receipt_cny=fee,
            reference=reference,chosen=chosen,evaluations=evaluations,
            hard_limit_feasible=(max(chosen.values())<=cfg['risk_limit']+cfg['tolerance'] if chosen else None),
            status='conditional_action_not_system_feasibility_certificate'))
        return fee

    def step(self):
        year = self.year
        super().step()
        self.year = year
        try:
            fee = self.retirement_decision()
            self.paths[-1]['resource_cost_cny'] += fee
        finally:
            self.year = year+1


def activate(model, *, rule, acceleration=5, horizon=3, pressure=.85,
             risk_limit=.02, retention_fee=20000., public_budget_fraction=.0005):
    if rule not in RULES or model.year != 2025 or model.paths:
        raise ValueError('Research extension requires fresh PR14 forward state and known rule')
    if type(acceleration) is not int or not 0<=acceleration<=10 or type(horizon) is not int or not 1<=horizon<=5:
        raise ValueError('Invalid research horizon/acceleration')
    if not 0<pressure<=1 or not 0<=risk_limit<1 or retention_fee<=0 or not 0<=public_budget_fraction<=.01:
        raise ValueError('Invalid research bound')
    model.__class__ = RetirementModel
    # Mesa stores the bound user step during construction. Rebind the hook,
    # retaining Mesa's wrapper and its step counter; class replacement alone
    # silently leaves the research decision stage inactive.
    model._user_step = MethodType(RetirementModel.step, model)
    model.research = dict(rule=rule,horizon=horizon,pressure=pressure,risk_limit=risk_limit,
                          retention_fee=retention_fee,public_budget_fraction=public_budget_fraction,tolerance=1e-8)
    model.research_services=[]; model.research_decisions=[]; model.research_solves=0
    for c in model.cohorts:
        if c['tech']=='coal' and c['status']=='active':
            natural=c['exit_year']; due=max(2028,natural-acceleration)
            if due<natural:
                c.update(research_natural=natural,research_due=due,
                         research_deadline=min(natural,due+3),exit_year=due)
    return model
