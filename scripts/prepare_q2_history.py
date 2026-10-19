"""Reproduce reviewed Q2 aggregate observations from existing local evidence.

This command verifies fixed review fingerprints; it cannot approve inputs or
refresh hashes. The manually checked image/PDF cells remain explicit in catalog.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    transcription_path = ROOT/'data/catalog/q2_source_transcription.json'
    review = json.loads((ROOT/'data/catalog/q2_history_review.json').read_text(encoding='utf-8'))
    for item in review['fingerprints']:
        if sha(ROOT/item['path']) != item['sha256']:
            raise ValueError('Q2 history evidence changed: '+item['path'])
    doc = json.loads(transcription_path.read_text(encoding='utf-8'))
    unified = list(csv.DictReader((ROOT/'data/processed/unified/nbs_history.csv').open(encoding='utf-8-sig')))
    rows = []
    for key in ('nbs_consumption','nbs_capacity','nbs_gdp'):
        spec = doc[key]
        for year,values in spec['rows'].items():
            for variable,value in zip(spec['columns'],values):
                if value is None:
                    continue
                candidates = [r for r in unified if r['year']==year and r['variable']==variable and
                              (variable!='real_gdp_growth_pct' or r['family']=='gdp_growth')]
                # The old admitted GDP subset begins in 2015. Earlier visually
                # checked cells are new scoped transcriptions, not missing zeros.
                newly_transcribed = key == 'nbs_gdp' and int(year) < 2015 and not candidates
                if not newly_transcribed and (len(candidates)!=1 or float(candidates[0]['value']) != value):
                    raise ValueError(f'Q2 visual/source-view disagreement {year}/{variable}')
                r=candidates[0] if candidates else {'unit':'%','record_id':''}
                family = ('driver' if key=='nbs_gdp' else 'capacity_or_generation' if key=='nbs_capacity'
                          else 'energy_consumption' if variable=='consumption_10ktce' else 'primary_mix')
                rows.append(dict(year=int(year),indicator=variable,value=value,unit=r['unit'],family=family,
                                 source_path=spec['path'],source_locator=f'year={year}; column={variable}',
                                 source_record_id=r['record_id'],boundary=spec['restriction'],
                                 allowed_use=spec['admitted_use'],independent_observations=1))
    carbon_path=ROOT/'data/raw/batch1_national/GCB2025v15_MtCO2_flat.csv'
    carbon=list(csv.DictReader(carbon_path.open(encoding='utf-8-sig')))
    stored=list(csv.DictReader((ROOT/'data/processed/china_co2_gcb_annual.csv').open(encoding='utf-8-sig')))
    for row in stored:
        matches=[r for r in carbon if r['ISO 3166-1 alpha-3']=='CHN' and r['Year']==row['year']]
        if len(matches)!=1 or float(matches[0][row['variable']])!=float(row['value']):
            raise ValueError('GCB source-cell mismatch')
        rows.append(dict(year=int(row['year']),indicator='gcb_'+row['variable'],value=float(row['value']),
                         unit=row['unit'],family='co2',source_path=carbon_path.relative_to(ROOT).as_posix(),
                         source_locator=row['source_locator'],source_record_id='',boundary=row['boundary'],
                         allowed_use='Q2 fossil/industry historical CO2 target only; not net national GHG',independent_observations=1))
    btr=[]
    spec=doc['btr_co2']
    for variable,values in spec['rows'].items():
        for year,value in zip(spec['years'],values):
            btr.append(dict(year=year,indicator=variable,value=value,unit=spec['unit'],
                            source_path=spec['path'],source_locator=spec['locator'],boundary=spec['restriction']))
    checks=[]
    for i,year in enumerate(spec['years']):
        v={k:values[i] for k,values in spec['rows'].items()}
        residual=v['total_excluding_lulucf']+v['lulucf_net_co2']-v['total_including_lulucf']
        components=v['energy_combustion']+v['industrial_process_product_use']+v['waste_co2']-v['total_excluding_lulucf']
        if max(abs(residual),abs(components))>.21:
            raise ValueError('BTR transcription fails published rounding check')
        gcb=next(r['value'] for r in rows if r['indicator']=='gcb_Total' and r['year']==year)
        checks.append(dict(year=year,net_sum_residual_10kt=residual,positive_sum_residual_10kt=components,
                           btr_positive_mt=v['total_excluding_lulucf']/100,gcb_positive_mt=gcb,
                           difference_mt=gcb-v['total_excluding_lulucf']/100,
                           decision='Separate inventories retained; no automatic bridge or averaging'))
    output.mkdir(parents=True,exist_ok=True)
    for name,data in [('history_observations.csv',rows),('btr_co2_anchors.csv',btr),('inventory_boundary_checks.csv',checks)]:
        with (output/name).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    print(json.dumps({'history_rows':len(rows),'btr_rows':len(btr),'boundary_checks':checks},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',default='data/processed/q2')
    args=p.parse_args()
    build(ROOT/args.output_dir)
