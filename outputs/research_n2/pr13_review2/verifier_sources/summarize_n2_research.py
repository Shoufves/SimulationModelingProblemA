"""Paired comparisons; never use mixed-unit totals as a safety score."""
from pathlib import Path
import argparse
import json


def compare(a,b):
    sa,sb=a['summary'],b['summary']
    av={(y['year'],s):v for y in a['services'] for s,v in y['services'].items()}
    bv={(y['year'],s):v for y in b['services'] for s,v in y['services'].items()}
    if av.keys()!=bv.keys():raise ValueError('Different service/year cells')
    delta={k:av[k]['fraction']-bv[k]['fraction'] for k in av}
    worst=max(delta,key=delta.get)
    return dict(candidate=a['name'],baseline=b['name'],
        maximum_service_fraction_regret=delta[worst],worst_cell=list(worst),
        improved_cells=sum(d < -1e-8 for d in delta.values()),
        worsened_cells=sum(d > 1e-8 for d in delta.values()),
        retention_reduction_fraction=(1-sa['retention_mw_year']/sb['retention_mw_year'] if sb['retention_mw_year'] else None),
        cost_change_fraction=sa['discounted_resource_cost_cny']/sb['discounted_resource_cost_cny']-1,
        co2_change_fraction=sa['cumulative_positive_co2_t']/sb['cumulative_positive_co2_t']-1,
        forecast_solves=sa['forecast_solves'],
        terminal_managed_capacity_change_mw=sa['final_initial_coal_mw']-sb['final_initial_coal_mw'])


def main():
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--candidate',default='paired_guard');args=p.parse_args()
    root=Path(args.directory);protocol=json.loads((root/'protocol.json').read_text('utf-8'))
    pairs=[]
    for c in protocol['conditions']:
        name=c['id']+'__'+args.candidate
        if not (root/(name+'.json')).exists():continue
        a=json.loads((root/(name+'.json')).read_text('utf-8'))
        for rule in protocol['rules']:
            if rule==args.candidate:continue
            path=root/(c['id']+'__'+rule+'.json')
            if not path.exists():continue
            row=compare(a,json.loads(path.read_text('utf-8')))
            pairs.append(row);print(json.dumps(row),flush=True)
    (root/'comparisons.json').write_text(json.dumps(pairs,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
