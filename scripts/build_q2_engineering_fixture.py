"""Rebuild only explicitly synthetic Q2 fixtures and their engineering fingerprints.

This command never reads or updates national input reviews. Its observations are
model-generated targets, not empirical data. Do not use it for national fitting.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src')); sys.path.insert(0, str(ROOT/'tests'))
from q2_cases import annual_case
from test_q2_experiments import historical_case, definitions, experiment
from energy_model.q2.annual import EnergyModel
from energy_model.q2.experiments import metric_rows
from energy_model.q2.io import dump, sha


def main():
    historical = historical_case()
    baseline = annual_case(); baseline['end_year'] = 2060
    baseline['gdp_growth'] = {str(y):.02 for y in range(2025,2061)}
    spec = experiment()
    spec['sensitivity'] = [
        {'id':'gdp_growth','values':[0.,.02,.04],
         'paths':[['gdp_growth',str(y)] for y in range(2025,2061)],
         'rationale':'Engineering response levels, not a national GDP forecast range'},
        {'id':'technology_cost_decline','values':[0.,.05,.1],
         'paths':[['cost_decline',k] for k in ('solar_build','heat_upgrade')],
         'rationale':'Engineering cost-path perturbation, not an empirical learning distribution'},
        {'id':'carbon_price','values':[0.,10.,20.],'paths':[['policies',0,'carbon_price_per_t']],
         'rationale':'Engineering liability-price perturbation, not Chinese ETS scope or price forecast'}]
    for factor in spec['sensitivity']:
        factor['source_or_assumption'] = 'synthetic fixture'
    objects = {'model_bundle':{'historical':historical,'baseline':baseline}, 'experiment':spec,
               'metric_definitions':definitions(),
               'acceptance':json.loads((ROOT/'workflow/q2_acceptance.json').read_text(encoding='utf-8')),
               'observations':metric_rows(EnergyModel(historical).run(),definitions())}
    bindings = []
    for name,obj in objects.items():
        path = ROOT/f'examples/q2/{name}.json'
        dump(path,obj)
        bindings.append({'id':name,'path':path.relative_to(ROOT).as_posix(),'sha256':sha(path),
                         'purpose':'synthetic engineering verification only','boundary':'synthetic_engineering_only'})
    dump(ROOT/'examples/q2_engineering.json',{
        'version':3,'scope':'synthetic_engineering_only','unresolved_required_inputs':[],
        'inputs':bindings,'sources':[], 'assumptions':[
            'All model quantities and observation targets are synthetic fixtures. No Chinese forecast or historical validity follows.',
            'Version 2 corrects replacement service capacity: 2 units added replace 2 units, not 200. Earlier outputs remain historical failed-physics evidence.',
            'Version 3 values timed construction, operating cash and terminal value; construction is paid at offsets 0..L-1. Fully funded non-remunerated escrow opportunity cost is explicit and excluded from resource accounts.']})
    print('Synthetic fixture v3 regenerated; national reviews untouched')


if __name__ == '__main__': main()
