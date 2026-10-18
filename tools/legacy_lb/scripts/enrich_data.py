"""Extract structured public report tables and aggregate source daily data without filling gaps."""
import csv,json,re,logging,calendar
from pathlib import Path
from collections import defaultdict,Counter
import pdfplumber
from pypdf import PdfReader
from collect import ROOT
logging.getLogger('pdfminer').setLevel(logging.ERROR)
OUT=ROOT/'data'; inventory=json.loads((ROOT/'数据文件目录.json').read_text(encoding='utf-8'))
def write(name,rows,source,note):
    rows=list(rows);p=OUT/name;p.parent.mkdir(exist_ok=True,parents=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,list(rows[0]));w.writeheader();w.writerows(rows)
    rel=str(p.relative_to(ROOT)).replace('\\','/');inventory[:]=[r for r in inventory if r['file']!=rel]
    inventory.append(dict(file=rel,rows=len(rows),columns=len(rows[0]),source=source,note=note))

# Exact PDF columns, using year-label positions; keep IRENA provenance flags.
pages={15:'renewable_total',18:'hydro_total',21:'renewable_hydro',24:'pumped_hydro',26:'wind',29:'onshore_wind',32:'offshore_wind',34:'solar_total',38:'solar_pv',41:'solar_csp',42:'bioenergy',44:'renewable_waste',47:'solid_biofuels',51:'biogas',53:'geothermal'}
rows=[];lookup={}
with pdfplumber.open(ROOT/'raw/reports/irena_capacity_2026.pdf') as doc:
    for pno,technology in pages.items():
        p=doc.pages[pno-1];words=p.extract_words();years=sorted([w for w in words if re.fullmatch('20(?:1[6-9]|2[0-5])',w['text']) and w['top']<150],key=lambda w:w['x0'])
        assert len(years)==10,(pno,len(years))
        china=next(w for w in words if w['text']=='China' and w['top']>150)
        line=[c for c in p.chars if abs(c['top']-china['top'])<2]
        for i,yr in enumerate(years):
            low=years[i-1]['x1']+4 if i else 115;high=yr['x1']+4
            text=''.join(c['text'] for c in sorted(line,key=lambda c:c['x0']) if low<=c['x0']<high)
            digits=re.sub(r'[^0-9.]','',text);assert digits,(pno,yr,text)
            value=float(digits);year=int(yr['text']);lookup[(technology,year)]=value
            rows.append(dict(year=year,country='China',technology=technology,capacity_MW=value,source_flag=''.join(re.findall('[a-z]',text)),source_id='IRENA_CAPACITY_2026',pdf_page=pno,raw_cell=text))
write('irena/china_capacity_2016_2025.csv',rows,'IRENA_CAPACITY_2026','PDF-position extraction. IRENA definitions differ from Chinese official biomass/waste accounting; hydro includes pumped storage but renewable_total excludes pure pumped storage. Original flags retained.')
checks=[]
for y in range(2016,2026):
    for total,parts in [('wind',['onshore_wind','offshore_wind']),('solar_total',['solar_pv','solar_csp']),('hydro_total',['renewable_hydro','pumped_hydro'])]:
        delta=lookup[(total,y)]-sum(lookup[(k,y)] for k in parts)
        checks.append(dict(year=y,check=total+'_components',difference_MW=delta,status='PASS_ROUNDING' if abs(delta)<=1 else 'REVIEW'))
write('quality/irena_component_checks.csv',checks,'IRENA_CAPACITY_2026','Identity checks detect column misalignment; original rounding allowed up to 1 MW')

# Chinese official grid factors: preserve factor type, do not use as fuel combustion factors.
rows=[];table=0
for pno,p in enumerate(PdfReader(ROOT/'raw/reports/china_grid_emission_factor_2023.pdf').pages,1):
    for line in (p.extract_text() or '').splitlines():
        m=re.search(r'表\s*([1-5])',line)
        if m:table=int(m[1])
        m=re.fullmatch(r'\s*([\u4e00-\u9fff]+)\s+(0\.\d+)\s*',line)
        if m:rows.append(dict(year=2023,region=m[1],factor_type={1:'national_average',2:'regional_average',3:'provincial_average',4:'national_excluding_market_nonfossil',5:'national_fossil_power'}[table],kgCO2_per_kWh=float(m[2]),source_id='CHINA_GRID_EF_2023',pdf_page=pno,table=table))
write('emissions/china_grid_factors_2023.csv',rows,'CHINA_GRID_EF_2023','Electricity indirect-emission factors. Do not add indirect electricity emissions to producer combustion emissions in a national total. Missing provinces are not zero.')

# Real GDP growth source index, transcribed from NBS 2025 table 3-4.
indices=[111.5,112.7,114.2,109.7,109.4,110.6,109.5,107.9,107.8,107.5,107.0,106.8,106.9,106.8,106.1,102.3,108.6,103.1,105.4,105.0]
gdp=[]
for year,value in zip(range(2005,2025),indices):
    gdp.append(dict(year=year,real_GDP_index_previous_year_100=value,real_GDP_growth_pct=round(value-100,1),source_id='NBS_2025_C03-04',source_column='国内生产总值（不变价，上年=100）'))
write('nbs/real_gdp_growth_2005_2024.csv',gdp,'NBS_2025_C03-04','Visually transcribed latest historical revision in 2025 yearbook. Do not use GNI column. Rates can chain a constant-price GDP index; they are not current-price RMB levels.')

# Provincial daily CO2 to annual sector sums, retaining coverage explicitly.
groups=defaultdict(lambda:{'value':0.0,'dates':set(),'n':0});first=None;last=None;sectors=Counter();provinces=set();duplicate=0;seen=set()
with (ROOT/'raw/carbonmonitor/CM_China_v1.csv').open(encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        date=r['date'];year=int(date[:4]);first=min(first,date) if first else date;last=max(last,date) if last else date
        key=(r['province'],r['sector'],date)
        if key in seen:duplicate+=1;continue
        seen.add(key);provinces.add(r['province']);sectors[r['sector']]+=1
        if not 2019<=year<=2025:continue
        g=groups[(r['province'],r['sector'],year)];g['value']+=float(r['ktCO2']);g['dates'].add(date);g['n']+=1
rows=[]
for (province,sector,year),g in sorted(groups.items()):
    expected=366 if calendar.isleap(year) else 365
    rows.append(dict(province=province,sector=sector,year=year,CO2_kt_sum=round(g['value'],6),days_present=len(g['dates']),expected_days=expected,coverage='complete_year' if len(g['dates'])==expected else 'partial_year',source_id='FIGSHARE_FILE_55875995'))
write('emissions/carbonmonitor_province_sector_annual_2019_2025.csv',rows,'FIGSHARE_FILE_55875995','Sum of original daily estimates. Use only complete_year for annual comparison. Sectors are reported separately; inspect definitions before totaling.')
(OUT/'quality/carbonmonitor_coverage.json').write_text(json.dumps(dict(first_date=first,last_date=last,provinces=sorted(provinces),sectors=dict(sectors),duplicate_keys=duplicate,partial_groups=sum(r['coverage']=='partial_year' for r in rows)),ensure_ascii=False,indent=2),encoding='utf-8')

(ROOT/'数据文件目录.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
with (ROOT/'数据文件目录.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,['file','rows','columns','source','note']);w.writeheader();w.writerows(inventory)
print(json.dumps(dict(irena_rows=150,irena_checks=Counter(r['status'] for r in checks),carbonmonitor_first=first,carbonmonitor_last=last,annual_rows=len(rows),duplicates=duplicate,data_files=len(inventory)),ensure_ascii=False))
