"""Offline historical technology references, retaining main/annex disagreements.

This is a source extraction, not a national calibration or parameter admission.
No price-year update, O&M split, national averaging or construction rounding is
performed. Those choices belong in the separately reviewed model assumptions.
"""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from energy_model.q2.io import csvout,dump,local_path,sha,verify_source_records


def prepare(root=ROOT):
    review=json.loads((root/'data/catalog/q2_technology_2010_review.json').read_text(encoding='utf-8'))
    if review['decision']!='scoped_historical_technology_reference' or not review['checks'] or not all(c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('Historical technology reference review absent or unresolved')
    for item in review['fingerprints']:
        if sha(local_path(root,item['path']))!=item['sha256']:
            raise ValueError('Historical technology reference fingerprint mismatch: '+item['path'])
    verify_source_records(root,review['source_records'])
    source=json.loads((root/'data/catalog/q2_technology_2010_transcription.json').read_text(encoding='utf-8'))
    if sha(local_path(root,source['source_path']))!=source['source_sha256']:
        raise ValueError('Historical technology original changed')
    metadata={k:source[k] for k in ('source_key','source_path','source_sha256','publication_year','price_year','projection_commission_date','annual_decision_available_from')}
    metadata['admission']='scoped_literature_reference_not_national_model'
    groups=('main_samples','annex_samples','parameters')
    for group in groups:
        rows=source[group]
        if not rows or len({r['id'] for r in rows})!=len(rows):
            raise ValueError('Duplicate or empty historical technology group: '+group)
    parameters={r['id']:r['value'] for r in source['parameters']}
    exchange=parameters['exchange_CNY_USD_2008']
    samples=[]
    for r in source['main_samples']:
        if r['net_capacity_MWe']<=0 or not 0<r['load_factor_percent']<=100:
            raise ValueError('Invalid sample capacity or load factor')
        if r['net_efficiency_percent'] is not None and not 0<r['net_efficiency_percent']<=100:
            raise ValueError('Invalid thermal efficiency')
        samples.append({**r,**metadata,
            'overnight_CNY_2008_per_MWe':r['overnight_USD_2008_per_kWe']*exchange*1000,
            'levelized_om_CNY_2008_per_MWh':r['levelized_om_USD_2008_per_MWh']*exchange,
            'transformation':'2008 USD * published 6.95 exchange; kWe cost *1000; no inflation update',
            'restriction':'Net sample capacity; aggregate levelized O&M does not identify fixed/variable split; CF is study assumption, not measured hourly availability.'})
    diagnostics=[]
    def discrepancy(identity,left,right,unit,interpretation):
        diagnostics.append({'id':identity,'left':left,'right':right,'difference':left-right,
                            'unit':unit,'interpretation':interpretation,'resolved':False})
    discrepancy('coal_heat_price_main_vs_annex',parameters['coal_price_main'],
                parameters['coal_price_mass']/parameters['coal_NCV_annex'],'USD_2008/GJ',
                'Main p43 heat price versus annex p206 mass price/NCV; do not mix the pairs or declare rounding.')
    discrepancy('gas_price_main_vs_shanghai',parameters['gas_price_main_MMBtu'],
                parameters['gas_price_Shanghai_annex'],'USD_2008/reported_million_Btu',
                'Main study assumption versus Shanghai power-sector quote; different scope, not interchangeable observations.')
    main={r['id']:r for r in source['main_samples']}
    annex={r['id']:r for r in source['annex_samples']}
    discrepancy('wind_yumen_main_vs_annex_cost',main['chn-W1']['overnight_USD_2008_per_kWe'],
                annex['chn-W1']['overnight_USD_2008_per_kWe_project'],'USD_2008/kWe',
                'Main p63 cost1223 versus annex A.2 cost1200; annex1700MCNY /6.95 /200MW implies1223.02, but original1200 is retained.')
    # Published aggregate fuel components provide a consistency diagnostic, not
    # an independent observation. Rounding of efficiency and prices is explicit.
    for r in source['main_samples']:
        if r['technology'] in {'coal','gas'}:
            reconstructed=parameters[r['technology']+'_price_main']*3.6/(r['net_efficiency_percent']/100)
            diagnostics.append({'id':'fuel_component:'+r['id'],'left':r['levelized_fuel_USD_2008_per_MWh'],
                'right':reconstructed,'difference':r['levelized_fuel_USD_2008_per_MWh']-reconstructed,
                'unit':'USD_2008/MWh_electricity','interpretation':'Main heat price and rounded net efficiency; agreement within published rounding is a diagnostic, not a new data point.',
                'resolved':abs(r['levelized_fuel_USD_2008_per_MWh']-reconstructed)<=.05})
    out=root/'data/processed/q2';out.mkdir(exist_ok=True)
    csvout(out/'technology_2010_samples.csv',samples)
    csvout(out/'technology_2010_annex.csv',[{**r,**metadata,'capacity_basis':'project_capacity_as_printed_not_main_table_net_unit'} for r in source['annex_samples']])
    csvout(out/'technology_2010_parameters.csv',[{**r,**metadata} for r in source['parameters']])
    csvout(out/'technology_2010_diagnostics.csv',diagnostics)
    result={'main_samples':len(samples),'annex_samples':len(annex),'parameters':len(parameters),
            'diagnostics':len(diagnostics),'unresolved_source_comparisons':sum(not d['resolved'] for d in diagnostics),
            'model_parameters_admitted':False,'review_sha256':sha(root/'data/catalog/q2_technology_2010_review.json')}
    dump(out/'technology_2010_checks.json',result)
    return result


if __name__=='__main__':print(json.dumps(prepare(),ensure_ascii=False,indent=2))
