"""Reviewed national initial-state references; missing state is not fabricated.

NEA's 2015 release and the later NBS editions remain separate. WRI fuel defaults
normalize matching gross carrier quantities, not additive primary energy or
combustion emissions. This command performs no model fitting or source download.
"""
import csv
import html
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from energy_model.q2.io import csvout,dump,local_path,sha,verify_source_records


# Original units: 10^4 kW, 10^8 kWh, 10^8 nominal CNY, h, g tce/kWh, %.
POWER_FIELDS=[
 ('consumption_total',r'全社会用电量(\d+)亿千瓦时','10^8 kWh','electricity_consumption'),
 ('consumption_primary_industry',r'第一产业用电量(\d+)亿千瓦时','10^8 kWh','electricity_consumption'),
 ('consumption_secondary_industry',r'第二产业(\d+)亿千瓦时','10^8 kWh','electricity_consumption'),
 ('consumption_tertiary_industry',r'第三产业(\d+)亿千瓦时','10^8 kWh','electricity_consumption'),
 ('consumption_household',r'城乡居民生活(\d+)亿千瓦时','10^8 kWh','electricity_consumption'),
 ('consumption_industry',r'工业用电量(\d+)亿千瓦时','10^8 kWh','electricity_consumption'),
 ('generation_total',r'全口径发电量(\d+)亿千瓦时','10^8 kWh','generation'),
 ('generation_hydro',r'水电发电量(\d+)亿千瓦时','10^8 kWh','generation'),
 ('generation_thermal',r'火电发电量(\d+)亿千瓦时','10^8 kWh','generation'),
 ('generation_nuclear',r'核电、并网风电和并网太阳能发电量分别为(\d+)亿千瓦时','10^8 kWh','generation'),
 ('generation_wind',r'核电、并网风电和并网太阳能发电量分别为\d+亿千瓦时、(\d+)亿千瓦时','10^8 kWh','generation'),
 ('generation_solar',r'核电、并网风电和并网太阳能发电量分别为\d+亿千瓦时、\d+亿千瓦时和(\d+)亿千瓦时','10^8 kWh','generation'),
 ('capacity_total',r'全国发电装机容量(\d+)万千瓦','10^4 kW','year_end_capacity'),
 ('capacity_hydro',r'其中，水电(\d+)万千瓦','10^4 kW','year_end_capacity'),
 ('capacity_pumped_hydro',r'含抽水蓄能(\d+)万千瓦','10^4 kW','year_end_capacity'),
 ('capacity_thermal',r'火电(\d+)万千瓦（含煤电','10^4 kW','year_end_capacity'),
 ('capacity_coal',r'含煤电(\d+)万千瓦','10^4 kW','year_end_capacity'),
 ('capacity_gas',r'气电(\d+)万千瓦','10^4 kW','year_end_capacity'),
 ('capacity_nuclear',r'核电(\d+)万千瓦，并网风电','10^4 kW','year_end_capacity'),
 ('capacity_wind',r'并网风电(\d+)万千瓦，并网太阳能','10^4 kW','year_end_capacity'),
 ('capacity_solar',r'并网太阳能发电(\d+)万千瓦。','10^4 kW','year_end_capacity'),
 ('new_capacity_total',r'全国基建新增发电设备容量(\d+)万千瓦','10^4 kW','commissioned_during_year'),
 ('new_capacity_hydro',r'水电新增(\d+)万千瓦','10^4 kW','commissioned_during_year'),
 ('new_capacity_thermal',r'火电新增(\d+)万千瓦','10^4 kW','commissioned_during_year'),
 ('new_capacity_nuclear',r'核电新增(\d+)万千瓦','10^4 kW','commissioned_during_year'),
 ('new_capacity_wind',r'并网风电新增(\d+)万千瓦','10^4 kW','commissioned_during_year'),
 ('new_capacity_solar',r'并网太阳能发电新增(\d+)万千瓦','10^4 kW','commissioned_during_year'),
 ('utilization_all',r'电厂发电设备平均利用小时数(\d+)小时','h','plants_at_least_6000kW'),
 ('utilization_hydro',r'水电设备平均利用小时(\d+)小时','h','plants_at_least_6000kW'),
 ('utilization_thermal',r'火电设备平均利用小时(\d+)小时','h','plants_at_least_6000kW'),
 ('utilization_nuclear',r'核电(\d+)小时','h','plants_at_least_6000kW'),
 ('utilization_wind',r'风电(\d+)小时','h','plants_at_least_6000kW'),
 ('investment_total',r'电力工程建设完成投资(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('investment_generation',r'电源工程建设完成投资(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('investment_hydro',r'水电、火电、核电、风电分别完成投资(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('investment_thermal',r'水电、火电、核电、风电分别完成投资\d+亿元，(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('investment_nuclear',r'水电、火电、核电、风电分别完成投资\d+亿元，\d+亿元，(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('investment_wind',r'水电、火电、核电、风电分别完成投资\d+亿元，\d+亿元，\d+亿元，(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('investment_grid',r'电网工程建设完成投资(\d+)亿元','10^8 CNY_nominal_2014','major_power_enterprises_construction_spending'),
 ('supply_standard_coal_rate',r'供电标准煤耗(\d+)克/千瓦时','g tce/kWh_net_supplied','plants_at_least_6000kW'),
 ('grid_loss_rate',r'输电线路损失率([\d.]+)%','%','national_grid_line_loss_rate')]


def text_content(path):
    raw=path.read_bytes()
    # The new NEA/FAQ pages are UTF-8; the 2016 yearbook uses GB2312/GBK.
    encoding='gb18030' if b'charset=gb2312' in raw.lower() else 'utf-8'
    text=raw.decode(encoding)
    text=re.sub(r'<script\b.*?</script>|<style\b.*?</style>','',text,flags=re.S|re.I)
    return re.sub(r'\s+','',html.unescape(re.sub(r'<[^>]+>',' ',text)))


def prepare(root=ROOT):
    review=json.loads((root/'data/catalog/q2_initialization_reference_review.json').read_text(encoding='utf-8'))
    if review['decision']!='scoped_initialization_references' or not all(c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('Initial-state reference review absent or unresolved')
    for item in review['fingerprints']:
        if sha(local_path(root,item['path']))!=item['sha256']:
            raise ValueError('Initial-state reference fingerprint mismatch: '+item['path'])
    verify_source_records(root,review['source_records'])
    fuel_doc=json.loads((root/'data/catalog/q2_fuel_reference_transcription.json').read_text(encoding='utf-8'))
    fuel_rows=[];checks=[]
    for row in fuel_doc['records']:
        carbon=Decimal(str(row['carbon_g_per_MJ_NCV']))
        ox=Decimal(str(row['oxidation_percent']))/100
        heat=Decimal(str(row['NCV_MJ_per_physical_unit']))
        co2=carbon*ox*Decimal(44)/12/Decimal(1000000)
        calculated=co2*heat;reported=Decimal(str(row['printed_CO2_t_per_physical_unit']))
        residual=calculated-reported
        checks.append({'check':'rounded_mass_CO2_factor:'+row['fuel'],'residual':str(residual),
                       'tolerance':'0.0005','passed':abs(residual)<=Decimal('.0005')})
        fuel_rows.append({**row,'NCV_MWh_per_physical_unit':float(heat/3600),
                          'CO2_t_per_MWh_NCV':float(co2*3600),'calculated_CO2_t_per_physical_unit':float(calculated),
                          'source_id':fuel_doc['source_id'],'source_path':fuel_doc['source_path'],
                          'source_sha256':fuel_doc['source_sha256'],'source_locator':fuel_doc['source_locator'],
                          'status':'literature_default_not_observed_national_fuel',
                          'annual_information_available_from':fuel_doc['annual_information_available_from']})
    registry=json.loads((root/'data/catalog/q2_sources.json').read_text(encoding='utf-8'))
    source=next(s for s in registry if s['id']=='NEA_POWER_2014_REVIEW')
    content=text_content(local_path(root,source['path']))
    if '2015-03-16' not in content or '2014年电力工业运行简况' not in content:
        raise ValueError('Unexpected NEA publication identity/date')
    power=[]
    for variable,pattern,unit,boundary in POWER_FIELDS:
        values=set(re.findall(pattern,content))
        if len(values)!=1:
            raise ValueError('NEA original field absent or ambiguous: '+variable+' '+str(values))
        value=float(values.pop())
        power.append({'year':2014,'variable':variable,'value':value,'unit':unit,'boundary':boundary,
                      'source_id':'q2:'+source['id'],'source_path':source['path'],'source_sha256':source['sha256'],
                      'source_locator':'2014 report; original Chinese expression: '+pattern,
                      'publication_date':source['published_date'],'status':'reported_2015_vintage_reference'})
    p={r['variable']:r['value'] for r in power}
    capacity_map={
        'coal':p['capacity_coal'],'gas':p['capacity_gas'],
        'other_thermal_unclassified':p['capacity_thermal']-p['capacity_coal']-p['capacity_gas'],
        'conventional_hydro':p['capacity_hydro']-p['capacity_pumped_hydro'],
        'pumped_hydro':p['capacity_pumped_hydro'],'nuclear':p['capacity_nuclear'],
        'wind':p['capacity_wind'],'solar':p['capacity_solar'],
        'other_generation_unclassified':p['capacity_total']-sum(p['capacity_'+t] for t in ('hydro','thermal','nuclear','wind','solar'))}
    capacity=[]
    for technology,value in capacity_map.items():
        if value<0:raise ValueError('Negative NEA capacity reconciliation')
        capacity.append({'year':2014,'geography':'China_mainland','technology':technology,'capacity_MW':value*10,
                         'definition':'2014 year-end; NEA 2015 publication vintage',
                         'derivation':'exact disjoint partition of published groups; 10^4 kW * 10 -> MW',
                         'source_id':'q2:NEA_POWER_2014_REVIEW','source_path':source['path'],
                         'classification':'unclassified_residual' if 'unclassified' in technology else 'named_technology',
                         'unresolved_state':'asset ages; permit status; finance; construction queue; within-year availability',
                         'status':'aggregate_capacity_candidate_not_complete_model_state'})
    generation_residual=p['generation_total']-sum(p['generation_'+t] for t in ('hydro','thermal','nuclear','wind','solar'))
    power.append({'year':2014,'variable':'generation_unallocated_difference','value':generation_residual,
                  'unit':'10^8 kWh','boundary':'reported_total_minus_five_named_generation_subtotals',
                  'source_id':'q2:'+source['id'],'source_path':source['path'],'source_sha256':source['sha256'],
                  'source_locator':'电力生产: total - hydro - thermal - nuclear - grid-connected wind - grid-connected solar',
                  'publication_date':source['published_date'],'status':'derived_unallocated_difference_not_identified_technology'})
    checks.extend([
        {'check':'disjoint_capacity_partition_MW','residual':sum(c['capacity_MW'] for c in capacity)-p['capacity_total']*10,'passed':sum(capacity_map.values())==p['capacity_total']},
        {'check':'generation_named_subtotal_does_not_exceed_total','unallocated_difference':generation_residual,
         'passed':generation_residual>=0,'interpretation':'Not a verified exhaustive partition; retain 11 x 10^8 kWh as unallocated, not rounding or a named technology.'},
        {'check':'generation_and_grid_construction_spending','residual':p['investment_total']-p['investment_generation']-p['investment_grid'],'passed':p['investment_total']==p['investment_generation']+p['investment_grid']}])
    # Match only explicitly named fuels. Broad coal/oil/tce columns deliberately
    # stay outside this conversion; no parent/child or transformation summation.
    mapping={'coke':'coke','crude':'crude_oil','gasoline':'gasoline','kerosene':'kerosene',
             'diesel':'diesel','fuel_oil':'fuel_oil','gas':'natural_gas'}
    factors={r['fuel']:r for r in fuel_rows};normalized=[]
    with (root/'data/processed/q2/nbs2014_accounts.csv').open(encoding='utf-8-sig',newline='') as f:
        accounts=list(csv.DictReader(f))
    for a in accounts:
        if a['table']!='0909CH':continue
        sector,carrier=a['account'].split(':')
        if carrier not in mapping:continue
        factor=factors[mapping[carrier]]
        expected_unit='10^8 m3' if factor['physical_unit']=='10^4 m3' else '10^4 t'
        if a['unit']!=expected_unit:raise ValueError('Unmatched fuel quantity unit')
        energy=None if not a['value'] else float(a['value'])*10000*factor['NCV_MWh_per_physical_unit']
        normalized.append({'year':2014,'sector':sector,'fuel':factor['fuel'],'source_quantity':a['value'],
                           'source_unit':a['unit'],'default_NCV_energy_MWh':energy,
                           'quantity_source':a['source_path'],'quantity_locator':a['source_label']+' / '+a['source_column'],
                           'factor_source':factor['source_id'],'factor_locator':factor['source_locator'],
                           'transformation':'quantity * 10000 physical units * reference MJ/physical unit / 3600 MJ/MWh',
                           'status':'missing_source_quantity' if energy is None else 'reference_heat_normalization_only',
                           'additive_primary_energy':False,'combustion_co2_computed':False,
                           'restriction':'Gross carrier use includes transformation/nonenergy use; not a final-service or emissions input without allocation.'})
    if not all(c['passed'] for c in checks):
        raise ValueError('Initial-state source arithmetic failed: '+str([c for c in checks if not c['passed']]))
    out=root/'data/processed/q2';out.mkdir(exist_ok=True)
    csvout(out/'fuel_reference.csv',fuel_rows);csvout(out/'power_2014_reference.csv',power)
    csvout(out/'initialization_2014_capacity.csv',capacity)
    csvout(out/'initialization_2014_fuel_normalization.csv',normalized)
    dump(out/'initialization_2014_reference_checks.json',{'passed':True,'checks':checks,
         'fuel_references':len(fuel_rows),'power_records':len(power),'disjoint_capacity_groups':len(capacity),
         'fuel_normalization_records':len(normalized),'normalized_missing_records':sum(r['default_NCV_energy_MWh'] is None for r in normalized),
         'model_state_complete':False,'no_cross_vintage_scaling':True,
         'source_review_sha256':sha(root/'data/catalog/q2_initialization_reference_review.json')})
    return {'fuels':len(fuel_rows),'power_records':len(power),'capacity_groups':len(capacity),
            'normalized_fuel_records':len(normalized),'checks':len(checks),'complete_model_state':False}


if __name__=='__main__':print(json.dumps(prepare(),ensure_ascii=False,indent=2))
