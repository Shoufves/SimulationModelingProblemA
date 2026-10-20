"""R4: refine only decisions blocked by the original rolling guard.

R3's V01 counterexample showed that unanchored rollout could retain more
capacity than the reference. This module changes the decision rule, not the
frozen acceptance thresholds. R3 remains a separate unchanged experiment.
"""
from .retirement import RetirementModel,activate as base_activate,RULES as BASE_RULES

RULES=BASE_RULES+('anchored_guard',)


class AnchoredModel(RetirementModel):
    def retirement_decision(self):
        if self.research['rule']!='anchored_guard':
            return super().retirement_decision()
        due=[c for c in self.cohorts if c.get('research_due') is not None
             and c['status']=='active' and c['exit_year']==self.year+1]
        if not due:return 0.
        original=self.forecast(due,set(),horizon=self.research['horizon'])
        # Do not invent additional retention when the original rule releases.
        selected='schedule' if max(original.values())<=self.research['risk_limit'] else 'rollout_guard'
        self.research['rule']=selected
        try:
            fee=super().retirement_decision()
        finally:
            self.research['rule']='anchored_guard'
        self.research_decisions[-1].update(rule='anchored_guard',anchor_would_retain=selected=='rollout_guard')
        return fee


def activate(model,*,rule,**kwargs):
    base_activate(model,rule='rollout_guard' if rule=='anchored_guard' else rule,**kwargs)
    if rule=='anchored_guard':
        model.__class__=AnchoredModel
        model.research['rule']=rule
    return model
