"""National reporting from explicitly reconciled model metrics and dated anchors.

This module never creates a primary-energy conversion, land-sink forecast, GDP
forecast or policy target. Those must be separately pinned and substantively
reviewed. Policy thresholds are comparisons, never inputs to agent decisions.
"""
from math import isfinite

from .experiments import net_co2, peak_assessment


def numeric(value, label, *, positive=False):
    if type(value) not in (int,float) or not isfinite(value) or value<0 or (positive and value==0):
        raise ValueError('Missing or invalid '+label)
    return float(value)


def national_report(metrics, model, spec, peak_criteria):
    if model['start_year']!=2024 or model['end_year']!=2060:
        raise ValueError('National S0 reporting requires 2024 initial state through 2060')
    for field in ('primary_energy_boundary','co2_boundary','gdp_basis','accounting_review_reference'):
        if not spec.get(field):
            raise ValueError('National accounting metadata missing: '+field)
    # No implicit scaling from MWh or t to national accounting units is allowed.
    expected={
        'primary_energy_mtce':('Mtce',spec['primary_energy_boundary']),
        'nonfossil_primary_mtce':('Mtce',spec['primary_energy_boundary']),
        'gross_energy_co2_mt':('Mt CO2',spec['co2_boundary']),
        'captured_co2_mt':('Mt CO2',spec['co2_boundary'])}
    bindings=spec['metric_bindings']
    if set(bindings)!=set(expected) or len({b['indicator'] for b in bindings.values()})!=len(bindings):
        raise ValueError('Four distinct reviewed energy/carbon metric bindings required')
    lookup={(r['year'],r['indicator']):r for r in metrics}
    if len(lookup)!=len(metrics):
        raise ValueError('Duplicate national model metric')
    external={r['year']:r for r in spec['nonenergy_and_removal_path']}
    if len(external)!=len(spec['nonenergy_and_removal_path']) or set(external)!=set(range(2024,2061)):
        raise ValueError('Complete unique nonenergy/removal assumptions through 2060 required')
    base=spec['gdp_base']
    if base['year']!=2024 or base['basis']!=spec['gdp_basis'] or not base['source_or_assumption']:
        raise ValueError('GDP base must match the declared 2024 real-price/index basis')
    gdp=numeric(base['value'],'real GDP base',positive=True)
    path=[]
    for year in range(2024,2061):
        if year>2024:
            growth=model['gdp_growth'][str(year)]
            if type(growth) not in (int,float) or not isfinite(growth) or growth<=-1:
                raise ValueError('Invalid real GDP growth')
            gdp=numeric(gdp*(1+growth),'real GDP path',positive=True)
        row={'year':year,'gdp_real':gdp,'gdp_basis':spec['gdp_basis'],
             'primary_energy_boundary':spec['primary_energy_boundary'],'co2_boundary':spec['co2_boundary']}
        for field,(unit,boundary) in expected.items():
            observation=lookup.get((year,bindings[field]['indicator']))
            if observation is None or observation['unit']!=unit or observation['boundary']!=boundary:
                raise ValueError('Unreconciled national metric unit/boundary: '+field)
            row[field]=numeric(observation['value'],field,positive=field=='primary_energy_mtce')
        if row['nonfossil_primary_mtce']>row['primary_energy_mtce']:
            raise ValueError('Nonfossil consumption exceeds total on the same accounting boundary')
        ex=external[year]
        if ex['co2_boundary']!=spec['co2_boundary'] or ex['unit']!='Mt CO2' or not ex['source_or_assumption']:
            raise ValueError('Unreconciled nonenergy/removal boundary or evidence')
        carbon=net_co2(row['gross_energy_co2_mt'],row['captured_co2_mt'],
                       numeric(ex['nonenergy_positive_co2_mt'],'nonenergy positive CO2'),
                       numeric(ex['net_removals_co2_mt'],'net removals'),common_boundary=True)
        row.update(positive_co2_mt=carbon['positive_co2'],net_removals_co2_mt=carbon['net_removals'],
                   net_co2_mt=carbon['net_co2'],neutralization_ratio=carbon['neutralization_ratio'],
                   neutralization_ratio_status=carbon['ratio_status'],
                   nonfossil_primary_share=row['nonfossil_primary_mtce']/row['primary_energy_mtce'],
                   nonenergy_positive_co2_mt=ex['nonenergy_positive_co2_mt'],
                   nonenergy_removal_evidence=ex['source_or_assumption'])
        row['energy_intensity']=row['primary_energy_mtce']/gdp
        row['carbon_intensity']=row['positive_co2_mt']/gdp
        path.append(row)
    historical={r['year']:r for r in spec['historical_anchors']}
    if len(historical)!=len(spec['historical_anchors']) or set(historical)!=set(range(2005,2024)):
        raise ValueError('Same-boundary 2005-2023 historical anchors required; no overlapping forecasts')
    for h in historical.values():
        if any(h[k]!=spec[k] for k in ('primary_energy_boundary','co2_boundary','gdp_basis')) or not h['source_or_assumption']:
            raise ValueError('Historical anchor and projected accounting boundaries differ')
        numeric(h['primary_energy_mtce'],'historical primary energy',positive=True)
        numeric(h['gdp_real'],'historical real GDP',positive=True)
        numeric(h['positive_co2_mt'],'historical positive CO2')
    by_year={r['year']:r for r in path}
    for row in path:
        for base_year in (2005,2025):
            anchor=historical[2005] if base_year==2005 else by_year[2025]
            energy_base=anchor['primary_energy_mtce']/anchor['gdp_real']
            carbon_base=anchor['positive_co2_mt']/anchor['gdp_real']
            row['energy_intensity_reduction_vs_'+str(base_year)]=1-row['energy_intensity']/energy_base
            row['carbon_intensity_reduction_vs_'+str(base_year)]=(1-row['carbon_intensity']/carbon_base if carbon_base else None)
    peak=peak_assessment({**{y:h['positive_co2_mt'] for y,h in historical.items()},
                          **{y:r['positive_co2_mt'] for y,r in by_year.items()}},**peak_criteria)
    outputs=[]
    units={'primary_energy_mtce':'Mtce','nonfossil_primary_share':'fraction','positive_co2_mt':'Mt CO2',
           'net_removals_co2_mt':'Mt CO2','net_co2_mt':'Mt CO2','neutralization_ratio':'fraction',
           **{f'{kind}_intensity_reduction_vs_{y}':'fraction' for kind in ('energy','carbon') for y in (2005,2025)}}
    for year in (2030,2060):
        for field,unit in units.items():
            value=by_year[year][field]
            outputs.append({'year':year,'indicator':field,'value':value,'unit':unit,
                            'boundary':spec['primary_energy_boundary'] if field.startswith(('primary','nonfossil','energy_')) else spec['co2_boundary'],
                            'status':'defined' if value is not None else 'undefined_zero_carbon_denominator',
                            'gdp_basis':spec['gdp_basis']})
    outputs.extend([{'year':2030,'indicator':'sustained_peak_year','value':peak['peak_year'],'unit':'year',
                     'boundary':spec['co2_boundary'],'status':peak['status']},
                    {'year':2030,'indicator':'peak_value','value':peak['peak_value'],'unit':'Mt CO2',
                     'boundary':spec['co2_boundary'],'status':peak['status']}])
    values={(r['year'],r['indicator']):r for r in outputs}
    required={(2030,'nonfossil_primary_share'),(2060,'nonfossil_primary_share'),
              (2030,'carbon_intensity_reduction_vs_2005'),(2030,'carbon_intensity_reduction_vs_2025'),
              (2030,'sustained_peak_year'),(2060,'net_co2_mt')}
    declared={(t['year'],t['indicator']) for t in spec['policy_targets']}
    if len(declared)!=len(spec['policy_targets']) or not required<=declared:
        raise ValueError('Unique complete 2030/2060 policy target set required')
    comparisons=[]
    for target in spec['policy_targets']:
        observation=values.get((target['year'],target['indicator']))
        if observation is None or any(target[k]!=observation[k] for k in ('unit','boundary')):
            raise ValueError('Policy target unit/boundary does not match reported metric')
        if not target['source_id'] or not target['source_locator']:
            raise ValueError('Policy target original and locator required')
        threshold=target['threshold'];op=target['comparison'];v=observation['value']
        if type(threshold) not in (int,float) or not isfinite(threshold) or op not in ('ge','gt','le','lt'):
            raise ValueError('Invalid frozen policy comparison')
        met=None if v is None else {'ge':v>=threshold,'gt':v>threshold,'le':v<=threshold,'lt':v<threshold}[op]
        comparison_status='compared' if met is not None else 'not_determined'
        if target['indicator']=='sustained_peak_year' and v is None and op=='le':
            if peak['status']=='zero_emissions_path':
                met=True;comparison_status='zero_emissions_throughout'
            elif threshold<=2060-peak_criteria['minimum_following_years']:
                # The declared pre-2030 persistent-peak criterion did not hold
                # over the full trajectory; this is not missing input.
                met=False;comparison_status='declared_sustained_peak_criterion_not_met'
        comparisons.append({**observation,'threshold':threshold,'comparison':op,'target_met':met,
                            'comparison_status':comparison_status,
                            'source_id':target['source_id'],'source_locator':target['source_locator']})
    # A target not met is a scientific outcome, not a numerical failure.
    # Undefined carbon denominators or unconfirmed peaks remain explicit.
    return {'annual':path,'indicators':outputs,'targets':comparisons,'peak':peak,
            'accounting_complete':True,'all_target_comparisons_determined':all(r['target_met'] is not None for r in comparisons)}
