"""Matched fixed committed-generation/infrastructure ablation, per final.

Demand devices still renew and pay under the original rules. New generation
and infrastructure requests cannot add assets; existing escrows are retained.
"""
from energy_model.q2_national import NationalGovernment,NationalGrid
from .anchored import activate as activate_policy


class FixedGovernment(NationalGovernment):
    def approve(self,generation,devices):
        return super().approve([dict(p,amount=0.) for p in generation],devices)


class FixedGrid(NationalGrid):
    def enqueue(self,kind,request,capex,budget_fraction,lead,life):
        return super().enqueue(kind,0.,capex,budget_fraction,lead,life)


def activate(model,*,rule,committed_clean_delay=0,current_information=False,**kwargs):
    if type(model.government) is not NationalGovernment or type(model.grid) is not NationalGrid:
        raise ValueError('Fixed-pipeline ablation requires the known PR14 actor types')
    if type(committed_clean_delay) is not int or not 0<=committed_clean_delay<=5:
        raise ValueError('Invalid committed clean-project delay')
    if type(current_information) is not bool:
        raise ValueError('Explicit information-mode boolean required')
    if current_information:
        from .current_information import activate as activate_current
        activate_current(model,rule=rule,**kwargs)
    else:
        activate_policy(model,rule=rule,**kwargs)
    model.government.__class__=FixedGovernment
    model.grid.__class__=FixedGrid
    for p in model.projects:
        if p['status']=='construction' and p['tech'] in ('wind','solar','hydro','nuclear'):
            p['online_year']+=committed_clean_delay
            p['exit_year']+=committed_clean_delay
            p['instalment']=p['remaining']/max(1,p['online_year']-model.year)
    model.forward_assumptions['research_ablation']='Only initial paid/committed generation and infrastructure; paid demand-device renewal retained'
    return model
