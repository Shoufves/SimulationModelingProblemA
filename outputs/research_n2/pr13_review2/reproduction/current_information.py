"""Final information boundary: persist observed GDP, fuel and weather.

Announced technology/lifetime schedules remain known. The simulator's future
GDP regime path is not used as if it were already observed by the controller.
"""
from .anchored import AnchoredModel,activate as activate_anchored


class CurrentInformationModel(AnchoredModel):
    def rollout_forecast(self,due,retained,*,horizon):
        original=self.a['gdp_future']
        # drivers adds the scenario delta. Remove it here so the resulting
        # forecast growth equals the CURRENT observed growth exactly once.
        growth=self.current_growth-self.variant.get('gdp_growth_delta',0.)
        self.a['gdp_future']={key:growth for key in original}
        try:
            return super().rollout_forecast(due,retained,horizon=horizon)
        finally:
            self.a['gdp_future']=original


def activate(model,*,rule,**kwargs):
    activate_anchored(model,rule=rule,**kwargs)
    if rule in ('anchored_guard','rollout_guard'):
        model.__class__=CurrentInformationModel
    return model
