"""New renewable project yields without retrofitting the inherited fleet.

All cohorts of a technology share the same daily profile and common curtailment
fraction in each period. Output is allocated by available energy, not capacity.
This is an aggregate approximation, not independent plant-level dispatch.
"""
from math import fsum,isfinite


class RenewableVintages:
    def __init__(self, *, new_project_cf, evidence):
        if set(new_project_cf)!={"wind","solar"} or not evidence:
            raise ValueError("Explicit wind and solar project yields and evidence required")
        if any(not isfinite(v) or not 0<v<=1 for v in new_project_cf.values()):
            raise ValueError("Project capacity factors must be in (0,1]")
        self.new_project_cf=dict(new_project_cf)
        self.evidence=evidence

    def profile(self,model,tech,cf):
        factor=model.variant.get("renewable_availability_multiplier",1)
        return [min(1,cf*v*factor) for v in model.a[tech+"_shape"]]

    def weighted_assets(self,model,tech,year,*,physical=False):
        if hasattr(model,"generation_assets"):
            return model.generation_assets(tech,year,physical=physical)
        rows=[c for c in model.cohorts if c["tech"]==tech and c["status"]=="active" and c["exit_year"]>year]
        rows += [p for p in model.projects if p["tech"]==tech and model.year<p["online_year"]<=year<p["exit_year"]]
        return [(c,1.0) for c in rows]

    def assets(self,model,tech,year):
        return [c for c,_ in self.weighted_assets(model,tech,year)]

    def update_plant(self,model,tech,plant,year,*,physical=False):
        assets=self.weighted_assets(model,tech,year,physical=physical)
        cap=fsum(c["capacity_mw"]*w for c,w in assets)
        profiles=[(c["capacity_mw"]*w,self.profile(model,tech,c.get("generation_cf",model.generators[tech].reference_cf))) for c,w in assets]
        plant.update(capacity_mw=cap,ramp_mw_per_hour=.2*cap,window_energy_budget_mwh=24*cap,
            availability=[fsum(k*p[i] for k,p in profiles)/cap if cap else 0 for i in range(4)])

    def add_candidate(self,model,tech,plant,amount):
        profile=self.profile(model,tech,self.new_project_cf[tech])
        old=plant["capacity_mw"];new=old+amount
        plant["availability"]=[(old*a+amount*b)/new if new else 0 for a,b in zip(plant["availability"],profile)]
        plant["capacity_mw"]=new
        plant["ramp_mw_per_hour"]+=amount*.2
        plant["window_energy_budget_mwh"]+=amount*24

    def candidate_hours(self,model,tech,plant,result):
        profile=self.profile(model,tech,self.new_project_cf[tech])
        # output/available MW is the common dispatched-hours multiplier.
        values=[]
        for row in result["generation"]:
            if row["plant"]!=tech:continue
            i=row["period"]
            denom=plant["capacity_mw"]*plant["availability"][i]
            if denom:values.append(row["output_mwh"]*profile[i]/denom*365)
        return fsum(values)

    def prior_project_margin(self,model,tech,margin_per_mwh,fixed_per_mw):
        """Initial belief uses only known candidate yield, shape and prices."""
        profile=self.profile(model,tech,self.new_project_cf[tech])
        return fsum(profile)*6*365*margin_per_mwh-fixed_per_mw

    def observed_project_margin(self,model,tech,op,result,realised_margin):
        """Translate this year's mixed-fleet sample before expectation learning.

        Each period's common dispatch fraction is applied to the clipped
        candidate profile. Under the model's common technology energy price
        and variable cost, gross contribution scales with dispatched energy;
        fixed O&M is removed before scaling and charged once afterwards.
        No pending project or future-year observation enters this sample.
        An absent fleet has no sample; an existing fleet with zero sales
        provides the observable loss of fixed O&M, without dividing by zero.
        """
        plant=op["plants"][tech]
        capacity=plant["capacity_mw"]
        if capacity<=0:
            return None
        fixed=model.fixed_om_per_mw(tech)
        hours=fsum(row["output_mwh"]*365/capacity for row in result["generation"]
                   if row["plant"]==tech)
        if hours<=0:
            return -fixed
        candidate=self.candidate_hours(model,tech,plant,result)
        return (realised_margin+fixed)*candidate/hours-fixed

    def allocate_actual(self,model,op,result):
        allocation={}
        for tech in ("wind","solar"):
            weighted=self.weighted_assets(model,tech,model.year)
            assets=[c for c,_ in weighted]
            profiles={c["id"]:self.profile(model,tech,c.get("generation_cf",model.generators[tech].reference_cf)) for c in assets}
            for c in assets:allocation[c["id"]]=0.0
            for row in result["generation"]:
                if row["plant"]!=tech:continue
                i=row["period"]
                weights={c["id"]:c["capacity_mw"]*w*profiles[c["id"]][i] for c,w in weighted}
                total=fsum(weights.values())
                if row["output_mwh"]>1e-6 and total<=0:
                    raise ValueError("Renewable output without an available cohort")
                if total:
                    for cid,weight in weights.items():allocation[cid]+=row["output_mwh"]*365*weight/total
            actual=fsum(r["output_mwh"]*365 for r in result["generation"] if r["plant"]==tech)
            if abs(fsum(allocation[c["id"]] for c in assets)-actual)>max(1e-5,actual*1e-12):
                raise ValueError("Renewable cohort outputs do not close")
        return allocation
