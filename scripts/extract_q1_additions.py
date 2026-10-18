"""Reviewed Q1 additions. Explicit preprocessing; never runs during q1.

PDF/HTML/image originals remain unchanged. Image transcriptions and publication
windows are explicit below. The fixed DOC extraction is specific to its hash;
it is not a general Word parser. No missing cell is converted to zero.
"""
from pathlib import Path
import csv,hashlib,json,re
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data/processed/q1'
EVID=ROOT/'outputs/q1_review/additions'

def writecsv(name,rows):
    with (DEST/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader();w.writerows(rows)

def record(variable,value,unit,source,locator,region='China',year=2024,status='reviewed_published',boundary='',**kw):
    return dict(year=year,region=region,variable=variable,value=value,unit=unit,source_id=source,
                source_locator=locator,status=status,boundary=boundary,**kw)

def prices():
    """Published vintage bridge, with overlaps retained in audit, never averaged."""
    mapping=[('Coal, Australia','Coal, Australian','USD/metric tonne'),
             ('Crude oil, average','Crude oil, average','USD/bbl'),
             ('Crude oil, Brent','Crude oil, Brent','USD/bbl'),
             ('Natural gas, Europe','Natural gas, Europe','USD/MMBtu'),
             ('Natural gas, U.S.','Natural gas, US','USD/MMBtu'),
             ('Liquefied natural gas, Japan','Liquefied natural gas, Japan','USD/MMBtu')]
    parsed={}; audits=[]
    specs=[('january',2023,[2020,2021,2022],'Q1_WB_PINK_JAN_2023'),
           ('january',2024,[2021,2022,2023],'Q1_WB_PINK_JANUARY_2024'),
           ('january',2025,[2022,2023,2024],'Q1_WB_PINK_JAN_2025'),
           ('february',2025,[2022,2023,2024],'Q1_WB_PINK_FEB_2025')]
    for month,edition,years,sid in specs:
        path=ROOT/f'data/raw/q1/wb_pink_{month}_{edition}.pdf'
        lines=[re.sub(r'\s+',' ',s).strip() for s in PdfReader(path).pages[0].extract_text(extraction_mode='layout').splitlines()]
        for prefix,var,unit in mapping:
            matches=[line for line in lines if line.startswith(prefix)]
            if len(matches)!=1:raise ValueError((path,prefix,matches))
            values=[float(x) for x in re.findall(r'(?<!\w)\d+\.\d+',matches[0])]
            if len(values)!=11:raise ValueError(('price columns',prefix,values))
            # Last annual column and four same-year quarters, columns 5--8.
            inside=min(values[4:8])-.11<=values[2]<=max(values[4:8])+.11
            if not inside and (var!='Natural gas, Europe' or years[-1]!=2024):
                raise ValueError(('Unexpected annual/quarterly inconsistency',sid,var))
            audits.append(dict(source=sid,variable=var,raw_line=matches[0],years=years,annual=values[:3],
                               quarterly=values[4:8],annual_within_quarterly_range=inside))
            for year,value in zip(years,values[:3]):
                parsed[(sid,var,year)]=record(var,value,unit,sid,f'PDF p1; Energy; {prefix}; Jan-Dec {year}',
                    region='International_benchmark',year=year,status='reviewed_release',
                    boundary='Nominal annual benchmark, rounded published PDF; not Chinese delivered price; publication vintage retained')
    with (ROOT/'data/processed/commodity_price_references.csv').open(encoding='utf-8-sig') as f:
        rows=[r for r in csv.DictReader(f) if r['status']=='archived_reference']
    # Confirm variable labels against the original archive before bridging.
    oldvars={r['variable'] for r in rows}
    if oldvars!={v for _,v,_ in mapping}:raise ValueError(('price labels',oldvars))
    overlaps=[]
    for _,var,_ in mapping:
        old=next(r for r in rows if r['variable']==var and r['year']=='2020')
        new=parsed[('Q1_WB_PINK_JAN_2023',var,2020)]
        overlaps.append(dict(variable=var,year=2020,archived=float(old['value']),pdf=new['value'],
                             absolute_difference=abs(float(old['value'])-new['value']),
                             rounding_tolerance=.0051 if old['unit']=='USD/MMBtu' else .051))
        rows.append(parsed[('Q1_WB_PINK_JANUARY_2024',var,2021)])
        for year in [2022,2023,2024]:
            if var=='Natural gas, Europe' and year==2024:continue
            rows.append(parsed[('Q1_WB_PINK_FEB_2025',var,year)])
    if any(x['absolute_difference']>x['rounding_tolerance'] for x in overlaps):raise ValueError('Unexpected 2020 bridge discrepancy')
    writecsv('prices_reviewed.csv',rows)
    proof=dict(annual_checks=audits,archive_2020_overlaps=overlaps,
        selection='Archive through 2020; January 2024 for 2021; February 2025 for 2022--2024. Same labels/units and source definitions; rounded PDF and archive precision differ.',
        rejected='Europe gas 2024 = 2.00 in both 2025 PDFs, outside quarterly range 8.75--13.57; excluded. No repair by averaging. NEA TTF 10.9 is a separate 2024 snapshot, not spliced into WB.',
        revisions='Japan LNG 2022 18.33 in January 2023 vs 18.43 later; 2023 14.23 in January 2024 vs 14.39 later; 2024 12.85 in January 2025 vs 12.84 February. Later values selected explicitly, no averaging.',
        original_quarantined_workbooks='Unchanged and excluded')
    (EVID/'price_release_review.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def renewable_regions():
    p=ROOT/'data/raw/batch2_mechanisms/nea_province_renewable_2024.doc'
    if hashlib.sha256(p.read_bytes()).hexdigest()!='b2c460a50a2bcd379b1a8c18b0b4c992fffff047dc8c5bb775aa7845ccd62449':
        raise ValueError('DOC extraction requires new content review')
    s=p.read_bytes().decode('utf-16le',errors='ignore');start=s.index('2024年度全国可再生能源电力发展监测评价结果')
    body=s[start:s.index('\x00',start)]
    (EVID/'nea_doc_text.txt').write_text(body.replace('\x07',' | ').replace('\r','\n'),encoding='utf-8')
    rows=[];counts={};source='NEA_PROVINCE_RENEWABLE_2024_DOC'
    for number,end,variable in [(1,'（二）','renewable_consumption_share'),(2,'三、','nonhydro_renewable_consumption_share'),
                               (3,'表4','wind_utilization_rate'),(4,'表5','pv_utilization_rate'),(5,'四、','hydro_basin_utilization_rate')]:
        part=body.split(f'表{number}  ',1)[1].split(end,1)[0]
        chunks=part.split('\x07\x07')[1:]
        count=0
        for chunk in chunks:
            cells=[c.strip() for c in chunk.split('\x07')]
            if not cells or len(cells)<3 or not re.fullmatch(r'\d+(\.\d+)?%',cells[1]):continue
            region=cells[0]
            if number<=2:
                rows.append(record(variable,float(cells[1].rstrip('%')),'%',source,f'Table {number}; {region}; actual 2024',region,
                    boundary='Consumption responsibility accounting includes imported electricity; not local generation share or primary energy share'))
                if len(cells)>3 and re.fullmatch(r'\d+(\.\d+)?%',cells[3]):
                    rows.append(record(variable+'_minimum',float(cells[3].rstrip('%')),'%',source,f'Table {number}; {region}; minimum target',region,
                        boundary='Policy obligation; Tibet exempt and Xinjiang monitored, their missing targets not zero'))
            else:
                for year,cell in zip([2023,2024],cells[1:3]):
                    rows.append(record(variable,float(cell.rstrip('%')),'%',source,f'Table {number}; {region}; {year}',region,year,
                        boundary='Energy utilization, not capacity factor. Wind/PV separate West/East Inner Mongolia; no unweighted province merge. Hydro is basin accounting.'))
            count+=1
        expected=32 if number<=2 else (33 if number<=4 else 8)
        if count!=expected:raise ValueError(('DOC table row count',number,count,expected))
        counts[number]=count
    writecsv('renewable_regions.csv',rows)
    (EVID/'nea_doc_extraction_checks.json').write_text(json.dumps(dict(rows_by_table=counts,
        method='Fixed-hash contiguous UTF16 text span; original Word cell/row delimiters; exact table labels and expected row counts; no blank-to-zero'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def province_capacities():
    # Official image, columns: end-2024 total / central / distributed (10^4 kW).
    data='''全国 88568 51089 37478
北京 130.3 8.1 122.2
天津 724.1 351.3 372.9
河北 7202.4 4294.1 2908.3
山西 3476.8 2500.9 975.9
山东 7613.4 2592.9 5020.6
内蒙古 4810.9 4502.7 308.1
辽宁 1213.9 542.1 671.8
吉林 583.0 382.0 201.0
黑龙江 717.1 471.1 245.9
上海 411.4 39.8 371.6
江苏 6164.7 1595.0 4569.7
浙江 4727.5 833.9 3893.6
安徽 4311.3 1441.9 2869.3
福建 1258.3 76.5 1181.8
江西 2563.9 1374.5 1189.4
河南 4349.1 630.0 3719.1
湖北 3510.0 2147.8 1362.1
湖南 1873.4 486.1 1387.3
重庆 309.8 107.2 202.6
四川 1082.3 889.3 193.0
陕西 3433.0 2523.9 909.1
甘肃 3138.8 2954.9 183.9
青海 3642.0 3604.3 37.8
宁夏 2624.0 2449.3 174.7
新疆 5345.6 5318.7 26.8
新疆兵团 329.2 329.2 NA
西藏 403.9 398.4 5.5
广东 4115.5 1373.3 2742.3
广西 2052.3 1088.6 963.7
海南 740.8 472.5 268.4
贵州 1985.6 1876.0 109.6
云南 3723.0 3433.1 289.9'''
    rows=[]
    for line in data.splitlines():
        region,*values=line.split()
        for var,v in zip(['pv_capacity','pv_central_capacity','pv_distributed_capacity'],values):
            if v=='NA':continue
            rows.append(record(var,float(v),'10^4 kW','Q1_NEA_PV_REGION_IMAGE_2024',f'Image table; {region}; end-2024 {var}',region,
                boundary='Year-end grid-connected PV. Xinjiang and XPCC listed separately; blank XPCC distributed cell remains missing; rounded subcomponents may not sum exactly.'))
    nuclear=[('广东',1613.6),('福建',1216),('浙江',916.6),('辽宁',671.274),('江苏',660.8),('广西',454.72),('山东',425.1),('海南',130)]
    for region,value in nuclear:
        rows.append(record('nuclear_grid_connected_capacity',value,'10^4 kW','Q1_NNSA_NUCLEAR_REGION_IMAGE_2024',f'Regional chart; {region}; operating blue bar',region,
            boundary='Grid-connected status includes newly connected units; source total differs from NBS publication by 5.094 (10^4 kW); definition/capacity reconciliation unresolved, do not splice.'))
    rows.append(record('nuclear_grid_connected_capacity',6088.094,'10^4 kW','Q1_NNSA_NUCLEAR_2024','Paragraph 1; 2024-12-31','全国',
        boundary='58 grid-connected units; source total differs from NBS, no unverified assumption about the reason; article generation forecasts not extracted'))
    checks=[]
    for var in ['pv_capacity','pv_central_capacity','pv_distributed_capacity','nuclear_grid_connected_capacity']:
        subset=[r for r in rows if r['variable']==var];total=next(r['value'] for r in subset if r['region']=='全国')
        subtotal=sum(r['value'] for r in subset if r['region']!='全国')
        checks.append(dict(variable=var,published_total=total,selected_region_sum=subtotal,residual=subtotal-total,
                           scope='XPCC distributed missing; sum is known cells only' if var=='pv_distributed_capacity' else 'All displayed regional rows'))
    writecsv('technology_region_capacities.csv',rows)
    (EVID/'region_transcription_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def context():
    rows=[]
    def add(var,value,unit,sid,locator,**kw):rows.append(record(var,value,unit,sid,locator,**kw))
    for var,value in [('hydro_large_capex',2216),('hydro_small_capex',1873)]:
        add(var,value,'2024 USD/kW','IRENA_COST_2024_PDF','PDF p149; Table 6.3; China; 2018-2024',
            status='published_multiyear',boundary='2018-2024 commissioned projects weighted installed cost; not 2024-only observation and not LCOE')
    for var,value in [('bioenergy_LCOE',.064),('bioenergy_LCOE_p05',.048),('bioenergy_LCOE_p95',.130)]:
        add(var,value,'2024 USD/kWh','IRENA_COST_2024_PDF','PDF p173; China paragraph; 2000-2024',
            status='published_multiyear',boundary='2000-2024 China project sample; percentiles across projects, not confidence interval; not 2024-only new-build cost')
    for var,value in [('hydrogen_production_price_december',28.0),('hydrogen_consumption_price_december',48.6),
                      ('hydrogen_demo_production_price_december',27.4),('hydrogen_demo_consumption_price_december',45.7),
                      ('hydrogen_other_production_price_december',28.5),('hydrogen_other_consumption_price_december',56.4)]:
        add(var,value,'CNY/kg','NEA_HYDROGEN_2025','PDF p18; December 2024 price-index paragraphs',
            boundary='December/end-year survey: production samples are high-purity ex-factory electrolysis/byproduct/methanol-reforming hydrogen, exclude coal hydrogen; consumption samples are operating hydrogen refuelling stations. Not industrial delivered hydrogen, annual mean, paired margin or green-only production cost.')
    for var,value in [('renewable_hydrogen_north_capacity_share',45),('renewable_hydrogen_northwest_capacity_share',44),
                      ('hydrogen_methanol_use_share',27),('hydrogen_ammonia_use_share',26)]:
        add(var,value,'%','NEA_HYDROGEN_2025','PDF p17; regional renewable capacity and hydrogen use paragraphs',
            boundary='Rounded report shares; regional shares refer to built renewable electrolyser capacity, not all hydrogen production')
    for var,value in [('gas_TTF_spot_price',10.9),('gas_NEAsia_LNG_spot_price',11.8),('gas_NEAsia_LNG_all_price',11.4),('gas_HH_spot_price',2.19)]:
        add(var,value,'USD/MMBtu','NEA_NATURAL_GAS_2025','PDF p9; 2024 annual price paragraph',region='International_benchmark',
            boundary='NEA 2025 report of 2024 market benchmarks; TTF/HH/NEAsia definitions retained; separate snapshot, no splice into WB series')
    for var,value,unit in [('bio_natural_gas_output',5,'10^8 m3'),('bio_agroforest_capacity',1709,'10^4 kW'),('bio_waste_incineration_capacity',2738,'10^4 kW')]:
        add(var,value,unit,'Q1_BIO_INDUSTRY_INTERVIEW','2025-04-14 interview; 2024 industry report scale paragraphs',
            status='industry_report_public_summary',boundary='Industry-association report quoted in first-hand forum coverage; rounded supplementary estimate, not official national energy balance. Heat figure has suspect unit and is excluded.')
    for var,value in [('UHV_DC_delivery',7053),('UHV_DC_renewable_delivery',4008)]:
        add(var,value,'10^8 kWh','NEA_PROVINCE_RENEWABLE_2024_DOC','Section IV; Table 6 national row',
            boundary='20 reported UHV DC lines annual electricity; not whole-grid flow, transmission capacity or candidate-network admission')
    add('wind_new_capacity_three_north_share',75,'%','NEA_RENEWABLE_2024','Wind subsection; regional new capacity',
        boundary='Share of 2024 newly connected wind capacity; not cumulative installed capacity or generation share')
    # Existing IPCC source values, preserving reference year and combustion scope.
    with (ROOT/'data/processed/technology_accounting_parameters.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['variable'] in ['other_bituminous_coal_CO2_default','natural_gas_CO2_default','crude_oil_CO2_default']:
                r['status']='reviewed_reference_parameter';rows.append(r)
    writecsv('additional_context.csv',rows)

if __name__=='__main__':
    DEST.mkdir(parents=True,exist_ok=True);EVID.mkdir(parents=True,exist_ok=True)
    prices();renewable_regions();province_capacities();context()
    retrievals=json.loads((ROOT/'data/raw/q1/retrievals.json').read_text(encoding='utf-8'))
    registry=[]
    for r in retrievals:
        if 'path' not in r:continue
        registry.append(dict(id=r['source_id'],title=r['title'],publisher=('国家核安全局转载中核智库' if r['source_id'].startswith('Q1_NNSA') else r['publisher']),url=r['url'],path=r['path'],
            status='q1_scoped_content_review',retrieved_at=r['retrieved_at'],sha256=r['sha256'],
            notes='Local Q1 only. See docs/solutions/p1-lb-additional-review.md; individual anomalies excluded, no original model admission changed.'))
    (ROOT/'data/catalog/q1_sources.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Extracted four reviewed Q1 datasets; original files and old admission contracts unchanged')
