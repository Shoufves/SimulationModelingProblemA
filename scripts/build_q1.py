"""Offline, pinned Q1 descriptive assessment. No ABM admission or forecasting."""
from pathlib import Path
from collections import defaultdict
import argparse, csv, hashlib, importlib.metadata, json, math, os, platform, shutil, subprocess, sys, uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q1 import finite, ratio, compound_index, spatial_difference, segmented_price_volatility, concentration

CODE_PATHS=['run.py','scripts/build_q1.py','src/energy_model/q1.py','scripts/prepare_q1_review.py',
            'scripts/plot_q1.py','scripts/q1_additional_analysis.py','scripts/extract_q1_additions.py',
            'scripts/extract_q1_revision.py','scripts/review_q1_delivery.py','requirements-q1.txt']


def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def csvout(path, rows):
    if not rows: raise ValueError(f'Empty required output: {path}')
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def local_path(path):
    p=(ROOT/path).resolve()
    if not p.is_relative_to(ROOT) or 'restricted' in p.relative_to(ROOT).parts:
        raise ValueError(f'Input outside admitted workspace: {path}')
    return p


def preflight(config):
    records=config['inputs']
    if len({r['id'] for r in records})!=len(records): raise ValueError('Duplicate input ID')
    for r in records:
        if sha(local_path(r['path']))!=r['sha256']: raise ValueError(f'Input hash mismatch: {r["id"]}')
        for key in r['source_map'].values():
            if key not in config['sources']: raise ValueError(f'Unpinned source {key}')
    for s in config['sources'].values():
        if not s['artifacts']: raise ValueError('Source lacks original')
        for a in s['artifacts']:
            if sha(local_path(a['path']))!=a['sha256']: raise ValueError(f'Original hash mismatch: {a["path"]}')


def load_history(config):
    data={}; history=[]; seen=set()
    for spec in config['inputs']:
        group=spec['id']; p=local_path(spec['path'])
        if p.suffix=='.json':
            doc=json.loads(p.read_text(encoding='utf-8'))
            raw=[dict(year=doc['year'],region=doc['region'],variable=r['indicator_id'],value=r['value'],unit=r['unit'],
                      source_id='mmj:S13',source_locator=r['locator'],status=doc['status'],boundary=r['scope']) for r in doc['observations']]
        else:
            with p.open(encoding='utf-8-sig',newline='') as stream:raw=list(csv.DictReader(stream))
        data[group]=[]
        for line,r in enumerate(raw,2):
            if group=='costs' and r['source_id']!='IRENA_COST_2024_PDF':continue
            if group=='prices' and r['status'] not in ('archived_reference','reviewed_release'):
                raise ValueError('Unreviewed price row')
            source=r.get('source_key') or r.get('source_id')
            if source not in spec['source_map']: raise ValueError(f'Unreviewed source {source}')
            sk=spec['source_map'][source]
            variable=r.get('variable') or r.get('technology') or r.get('origin')
            value=finite(r.get('value',r.get('capacity_MW')))
            unit=r.get('unit','MW'); year=int(r['year'])
            if year not in spec['years'] or unit not in spec['units']:
                raise ValueError(f'Unreviewed year/unit: {group}/{year}/{unit}')
            region=r.get('region',r.get('country',r.get('destination','China')))
            qualifier=';'.join(f'{k}={r[k]}' for k in ('family','capacity_factor_pct','real_discount_pct','lifetime_years','row_type') if k in r)
            key=(group,sk,year,region,variable,unit,qualifier)
            if key in seen:raise ValueError(f'Duplicate observation: {key}')
            seen.add(key)
            rid=f'{group}:{line}'
            locator=r.get('source_locator') or (f"{r['sheet']}!{r['cell']}" if 'sheet' in r else f"PDF p{r['pdf_page']}; {r['technology']}; {year}")
            entry=dict(record_id=rid,dataset=group,year=year,region=region,energy=energy_label(group,variable,r),variable=variable,value=value,
                       original_value=r.get('original_value',r.get('value',r.get('raw_cell',r.get('capacity_MW')))),unit=unit,
                       source_key=sk,source_locator=locator,input_path=spec['path'],input_record=line,
                       status=r.get('source_status',r.get('status','published_compilation')),
                       qualifier=qualifier,source_flag=r.get('source_flag',''),
                       boundary=r.get('boundary',spec['review']),
                       observation_role='separate_release_or_compilation' if group in ('official2024','research','irena_capacity') else 'selected_source_record',
                       independence='Do not count same-upstream releases/compilations as independent validation')
            for field in ('publication_year','precision_role','definition_segment','annual_definition_status',
                          'definition_switch','definition_locator','definition_note'):
                entry[field]=r.get(field,'')
            r=dict(r,_id=rid,_source=sk,_value=value,year=year)
            data[group].append(r);history.append(entry)
    return data,history


def select(data,group,variable=None,year=None,**filters):
    return [r for r in data[group] if (variable is None or r.get('variable')==variable)
            and (year is None or r['year']==year) and all(r.get(k)==v for k,v in filters.items())]


def energy_label(group,variable,row):
    if group in ('pipeline','lng'):return '天然气'
    if group=='coal_trade':return '煤炭'
    if group=='balance':
        return {'NBS_2025_C09-03':'能源总量','NBS_2025_C09-04':'石油','NBS_2025_C09-05':'煤炭','NBS_2025_C09-06':'电力'}[row['source_id']]
    value=variable.lower()
    for token,name in [('hydrogen','氢能'),('storage','储能'),('pumped','储能'),('coal','煤炭'),('coke','焦炭'),('oil','石油'),
                       ('petro','石油'),('gas','天然气'),('ccgt','天然气'),('hydro','水电'),('nuclear','核电'),('wind','风电'),
                       ('solar','太阳能/光伏'),('biomass','生物质'),('biofuel','生物质'),('thermal','火电')]:
        if token in value:return name
    if group=='carbon':return '碳排放/过程'
    if 'gdp' in value:return '经济活动'
    if any(x in value for x in ('electric','generation','capacity','10kw')):return '电力/多技术'
    return '能源总量/其他'


def one(data,group,variable,year,unit=None,**filters):
    rows=select(data,group,variable,year,**filters)
    if len(rows)!=1: raise ValueError(f'Expected one observation: {group}/{variable}/{year}/{filters}, got {len(rows)}')
    row=rows[0]
    if unit and row['unit']!=unit: raise ValueError(f'Unit mismatch: {row["_id"]}: {row["unit"]} != {unit}')
    return row


def calculate(data):
    indicators=[]; balances=[]; regions=[]; origins=[]; gaps=[]
    def add(ident,dimension,year,value,unit,formula,refs,direction='context',status='calculated',boundary=''):
        indicators.append(dict(indicator_id=ident,dimension=dimension,year=year,value=value,unit=unit,direction=direction,
            formula=formula,input_refs=';'.join(r['_id'] for r in refs),effective_years=str(year),status=status,boundary=boundary))
        return value
    def get(group,var,year,unit=None,**kw): return one(data,group,var,year,unit,**kw)
    for r in data['reviewed2024']:
        if r['precision_role']=='crosscheck_only':continue
        ident=r['variable']+('_'+r['region'] if r['region']!='China' else '')
        add(ident,'低碳' if 'nonfossil' in ident else '协调',r['year'],r['_value'],r['unit'],
            'published scoped value; source unit conversion only',[r],status=r['status'],boundary=r['boundary'])
    growth={r['year']:r['_value'] for r in select(data,'national','real_gdp_growth_pct',family='gdp_growth')}
    gdp=compound_index(growth)
    ebase=get('national','consumption_10ktce',2015,'10^4 tce')
    cbase=get('carbon','Total',2015,'Mt CO2')
    for year in range(2015,2025):
        energy=get('national','consumption_10ktce',year,'10^4 tce')
        coal=get('national','consumption_coal_pct',year,'%')
        co2=get('carbon','Total',year,'Mt CO2')
        gdprows=[r for r in select(data,'national','real_gdp_growth_pct',family='gdp_growth') if 2015<r['year']<=year]
        add('energy_total','低碳',year,energy['_value']/10000,'亿吨标准煤','consumption_10ktce / 10000',[energy])
        add('coal_share','低碳',year,coal['_value'],'%','source share',[coal],'lower',boundary='一次能源消费份额')
        add('coal_allocated_tce','低碳',year,energy['_value']*coal['_value']/1e6,'亿吨标准煤','total * coal_share / 100 / 10000',[energy,coal],boundary='按份额推导的标准煤量；非实物吨或燃烧排放')
        add('real_gdp_index','低碳',year,gdp[year],'2015=100','100 * product(1 + real_growth/100)',gdprows)
        add('energy_intensity_index','低碳',year,(energy['_value']/ebase['_value'])/(gdp[year]/100)*100,'2015=100','(energy/E2015)/(GDP_index/100)*100',[energy,ebase]+gdprows,'lower',boundary='全口径能耗强度；不同于官方扣除原料用能和非化石的指标')
        add('co2_intensity_index','低碳',year,(co2['_value']/cbase['_value'])/(gdp[year]/100)*100,'2015=100','(CO2/C2015)/(GDP_index/100)*100',[co2,cbase]+gdprows,'lower',boundary='GCB属地化石与工业CO2；不含土地利用与移除；非净排放')
        comps=[get('carbon',v,year,'Mt CO2') for v in ('Coal','Oil','Gas','Cement','Flaring','Other')]
        balances.append(dict(account='carbon_components',year=year,unit='Mt CO2',reported=co2['_value'],
            calculated=sum(r['_value'] for r in comps),arithmetic_residual=sum(r['_value'] for r in comps)-co2['_value'],
            input_refs=[r['_id'] for r in [co2]+comps],scope='Inventory internal sum only; not independent energy-to-carbon validation'))
    # Carrier-specific balances preserve both arithmetic and published supply-use differences.
    rules={
        'total':('NBS_2025_C09-03','10^4 tce',['primary_production','imports','exports','inventory_opening_minus_closing'],[('final_consumption',1),('conversion_losses',1),('recovered_energy_deducted',-1),('losses',1)]),
        'oil':('NBS_2025_C09-04','10^4 t',['production_crude_oil','imports_oil_products_inclusive','exports_oil_products_inclusive','inventory_opening_minus_closing'],[('final_consumption',1),('transformation_input',1),('losses',1)]),
        'coal':('NBS_2025_C09-05','10^4 t',['production_raw_coal','imports','exports','inventory_opening_minus_closing'],[('final_consumption',1),('transformation_input',1)]),
        'electricity':('NBS_2025_C09-06','10^8 kWh',['production','imports','exports'],[('final_consumption',1),('transmission_distribution_losses',1)])}
    for carrier,(source,unit,supply_vars,use_terms) in rules.items():
        for year in (2015,2020,2022,2023):
            rows=select(data,'balance',year=year,source_id=source)
            if not rows: raise ValueError(f'Missing balance {carrier}/{year}')
            d={r['variable']:r for r in rows}
            if len(d)!=len(rows) or any(r['unit']!=unit for r in rows):raise ValueError('Balance schema mismatch')
            supply=sum(d[v]['_value']*(-1 if v.startswith('exports') else 1) for v in supply_vars)
            use=sum(d[v]['_value']*sign for v,sign in use_terms)
            a,c=d['available_supply']['_value'],d['consumption']['_value']
            b=dict(account=carrier,year=year,unit=unit,calculated_supply=supply,reported_supply=a,supply_arithmetic_residual=supply-a,
                   calculated_consumption=use,reported_consumption=c,use_arithmetic_residual=use-c,
                   published_supply_minus_consumption=a-c,published_balance=d.get('balance_difference',{}).get('_value'),
                   supply_formula=' + '.join(('-' if v.startswith('exports') else '')+v for v in supply_vars),
                   use_formula=' + '.join(f'{sign}*{v}' for v,sign in use_terms),input_refs=[r['_id'] for r in rows],
                   interpretation='Statistical residual preserved; no inferred loss, stock or missing flow assigned')
            balances.append(b)
            im,ex=d[supply_vars[1]],d[supply_vars[2]]
            add(carrier+'_net_import_ratio','保障',year,ratio(im['_value']-ex['_value'],c),'%','(imports - exports)/consumption * 100',[im,ex,d['consumption']],
                'lower_exposure',boundary='同版同表；石油含油品/国际加油；总能源不是燃料平均；电力负值表示净出口')
    # Origin buckets must be explicit. A positive regional bucket precludes exact country HHI.
    groups={'Other S. & Cent. America','Other Europe','Other Middle East','Other Africa','Other Asia Pacific',
            'Other Americas*','Other Europe*','Other Asia Pacific*','Europe','Other CIS','Rest of World'}
    for fuel in ('pipeline','lng','coal_trade'):
        rs=data[fuel]; total=[r for r in rs if r['row_type']=='total']
        if len(total)!=1 or len({(r['year'],r['unit']) for r in rs})!=1:raise ValueError('Trade denominator mismatch')
        parts=[r for r in rs if r['row_type']=='origin']; t=total[0]['_value']
        hh=concentration([r['_value'] for r in parts],t,[r['origin'] in groups for r in parts])
        for bound in ('lower','upper'):
            add(fuel+'_HHI_'+bound,'保障',2024,hh[bound],'0–10000','sum((origin/total)^2)*10000; country '+bound+' bound',rs,
                'lower_concentration',status='exact' if hh['point'] is not None else 'bound',boundary='上下界为一个指标；不得加权两次；集中度不等于中断概率')
        for r in parts:
            origins.append(dict(fuel=fuel,year=2024,origin=r['origin'],value=r['_value'],unit=r['unit'],share_pct=ratio(r['_value'],t),
                origin_type='regional_bucket' if r['origin'] in groups else 'named_country',input_ref=r['_id'],total_ref=total[0]['_id']))
    # Same-year spatial shares; absolute surplus is not a measured transmission flow.
    gr=select(data,'region_generation',year=2024); cr=select(data,'province',year=2024)
    if any(r['unit']!='10^8 kWh' for r in gr+cr):raise ValueError('Regional electricity unit mismatch')
    g={r['region']:r['_value'] for r in gr}; c={r['region']:r['_value'] for r in cr}
    if len(g)!=31 or len(c)!=31 or len(gr)!=31 or len(cr)!=31:raise ValueError('Expected 31 unique mainland provinces')
    mismatch,diffs=spatial_difference(g,c)
    add('spatial_share_difference','协调',2024,mismatch,'0–1','0.5*sum(abs(G_i/sum(G)-C_i/sum(C)))',gr+cr,'context',boundary='空间错配描述；不是实际净输电、损耗或可靠性指数')
    for region in sorted(g):
        regions.append(dict(year=2024,region=region,generation=g[region],consumption=c[region],unit='10^8 kWh',
            generation_share_pct=ratio(g[region],sum(g.values())),consumption_share_pct=ratio(c[region],sum(c.values())),
            share_difference_pp=diffs[region]*100,generation_minus_use=g[region]-c[region],
            input_refs=';'.join(r['_id'] for r in gr+cr if r['region']==region),boundary='发用差额非实测净输电'))
    nat=get('products','generation_100GWh',2024,'10^8 kWh')
    balances.append(dict(account='province_generation_sum',year=2024,unit='10^8 kWh',reported=nat['_value'],calculated=sum(g.values()),
                         arithmetic_residual=sum(g.values())-nat['_value'],input_refs=[nat['_id']]+[r['_id'] for r in gr]))
    for year in (2015,2020,2023,2024):
        rows=select(data,'province',year=year); vals=sorted([r['_value'] for r in rows],reverse=True)
        add('top5_province_consumption_share','协调',year,ratio(sum(vals[:5]),sum(vals)),'%','sum(top5 use)/sum(31 use)*100',rows,
            boundary='各年分别取前五；不插值缺失年度')
    for var in ('raw_coal_100Mt','natural_gas_100Mm3','hydro_generation_100GWh'):
        rs=select(data,'regional_resources',var,2024); total=get('products',var,2024)
        if len(rs)!=3 or len({r['region'] for r in rs})!=3 or any(r['unit']!=total['unit'] for r in rs):
            raise ValueError('Regional resource selection/unit mismatch')
        subtotal=sum(r['_value'] for r in rs)
        if subtotal>total['_value'] or any(r['_value']<0 for r in rs):raise ValueError('Regional subtotal exceeds national production')
        add('top3_production_'+var,'协调',2024,ratio(subtotal,total['_value']),'%','sum(three largest published province outputs) / same-table national output *100',rs+[total],
            boundary='三省排序来自原图全列人工核对；选录表不是31省完整面板；集中度不直接代表不安全')
    for r in data['renewables']:
        if 'utilization_rate' in r['variable'] or 'pumped_hydro_capacity'==r['variable']:
            add(r['variable'],'协调',r['year'],r['_value'],r['unit'],'published value',[r],boundary='利用率不是容量因子；抽蓄装机仅功率')
    for r in data['snapshots']:
        if r['variable'].startswith('new_storage'):
            ident=r['variable']+('_'+r['region'] if r['variable']=='new_storage_power_share' else '')
            add(ident,'协调',r['year'],r['_value'],r['unit'],'published value',[r],boundary=r['boundary'])
    # Gross gas import mix and industrial/power common resource exposure.
    gasim=get('snapshots','gas_imports_total',2024,'10^8 m3')
    for var in ('gas_imports_LNG','gas_imports_pipeline','gas_top5_import_volume'):
        r=get('snapshots',var,2024,'10^8 m3')
        add(var+'_share','保障',2024,ratio(r['_value'],gasim['_value']),'%','volume / total gross imports * 100',[r,gasim],boundary='进口内部结构；不是净进口依赖')
    hp=get('snapshots','hydrogen_output',2024)
    hparts=[]
    for var in ('coal_hydrogen_output','gas_hydrogen_output','byproduct_hydrogen_output','electrolysis_hydrogen_output'):
        r=get('snapshots',var,2024,hp['unit'])
        hparts.append(r)
        add(var+'_share','低碳',2024,ratio(r['_value'],hp['_value']),'%','approximate route output / reported total lower threshold * 100',[r,hp],status='reference_ratio_to_lower_threshold',boundary='总量为超过3650而非精确3650；本比值仅按3650参考基数描述，不是精确路线份额。电解氢不自动等于绿氢')
    balances.append(dict(account='hydrogen_route_sum',year=2024,unit=hp['unit'],reported=hp['_value'],
                         calculated=sum(r['_value'] for r in hparts),arithmetic_residual=sum(r['_value'] for r in hparts)-hp['_value'],
                         input_refs=[hp['_id']]+[r['_id'] for r in hparts],reported_is_lower_bound=True,
                         scope='Difference against reported lower threshold only; actual total exceeds it, rounded categories do not close; never allocate discrepancy'))
    # Comparable plant-level busbar energy service, with explicit finance/lifetime conventions.
    costs=data['cost_comparison']; costgroups=defaultdict(list)
    lifetimes={'CCGT':30,'Coal_USC':40,'Nuclear_LWR':60}
    for r in costs:
        if (r['unit']!='2018 USD/MWh' or int(r['lifetime_years'])!=lifetimes[r['technology']]
                or r['year']!=2025 or r['status']!='published_projection'):raise ValueError('Cost convention mismatch')
        key=(int(r['capacity_factor_pct']),int(r['real_discount_pct']))
        costgroups[key].append(r)
        add(f"LCOE_{r['technology']}_CF{key[0]}_r{key[1]}",'经济',2025,r['_value'],r['unit'],'published discounted lifetime cost / discounted generation',[r],
            'lower',status='published_projection',boundary=f"2020报告2025投产设定；CF={key[0]}%;实际折现率={key[1]}%;寿命={r['lifetime_years']}年；碳价30USD/t；非现状实测/非保供系统成本")
    if set(costgroups)!={(85,3),(85,7),(85,10),(50,7)} or any({r['technology'] for r in rs}!=set(lifetimes) or len(rs)!=3 for rs in costgroups.values()):
        raise ValueError('Incomplete matched cost groups')
    for r in data['costs']:
        if 'LCOE' in r['variable']:
            add(r['variable'],'经济',r['year'],r['_value'],r['unit'],'published weighted LCOE',[r],'lower',status='published_estimate',
                boundary='IRENA 2024美元；经济寿命25年；2024技术/国家特定WACC；不与2018美元旧投影横排；不含相同保供系统成本')
    for var in sorted({r['variable'] for r in data['prices']}):
        rs=select(data,'prices',var); window=[r for r in rs if 2015<=r['year']<=2024]
        if len({r['year'] for r in window})!=len(window) or len({r['unit'] for r in window})!=1: raise ValueError('Price series mismatch')
        for v in segmented_price_volatility(window):
            segment=v['definition_segment'];refs=[r for r in window if r['definition_segment']==segment]
            add('price_log_volatility_'+var+'__'+segment,'经济','2015–2024',v['value'],'log-return SD',
                'sample_SD(log(P_t/P_t-1)); adjacent homogeneous annual pairs within one definition segment',refs,
                'lower_variability',status='insufficient_returns' if v['value'] is None else 'within_definition_segment',boundary=json.dumps(v,ensure_ascii=False))
            indicators[-1]['effective_years']=';'.join(map(str,v['observed_years']))
        if var in ('Coal, Australian','Natural gas, Europe'):
            gaps.append(dict(item=var,years='2015–2024',status='definition_break',
                reason=('2015混合边境/现货与TTF定义；2024年度2.00与季度不相容而排除' if var=='Natural gas, Europe' else '2022年2月现货改期货，2022混合年度；2023–2024仅1个年度变化不足估计样本SD'),
                impact='保留观测，分段报告有效年度对；不报告全十年同口径波动',action='后续仅凭有明确统一回溯定义的原件扩展可比窗口'))
    return indicators,balances,regions,origins,gaps


def coverage(history):
    grouped=defaultdict(list)
    for r in history:grouped[(r['dataset'],r['region'],r['variable'],r['qualifier'],r['unit'])].append(r)
    out=[]
    for key,rows in sorted(grouped.items()):
        years=sorted({r['year'] for r in rows}); missing=sorted(set(range(2015,2025))-set(years))
        out.append(dict(dataset=key[0],region=key[1],variable=key[2],qualifier=key[3],unit=key[4],
                        observed_years=';'.join(map(str,years)),missing_2015_2024=';'.join(map(str,missing)),
                        observed_count_2015_2024=len(set(years)&set(range(2015,2025))),
                        interpretation=('projection, not historical coverage' if key[0]=='cost_comparison' else
                            'Context/reference or multiyear/December snapshot; inspect status and boundary, not an annual panel' if key[0]=='context' else 'Missing is unknown, not zero')))
    return out


ROLES=[
 ('煤炭','规模供给与电热转换的基础','消费份额下降但绝对标准煤量仍增；发电与供热共享燃料','national;balance;products','燃料供给、存量设备、碳核算','实物煤热值/用途/煤电退出时间不可由总量直接确定'),
 ('石油','交通与化工原料供给','净进口暴露高；能源用途与非燃烧原料须分账','balance;official2024;research','进口来源、库存、交通设备更新','缺原油国别表准入与同年可动用库存；不可套煤炭替代效率'),
 ('天然气','工业、城市燃气和气电共用气源','工业与气电存在共同资源约束；LNG与管道来源不同','snapshots;pipeline;lng','共用气源账本、进口压力、库存提取','缺净出口匹配、日内提取/到货上限；不能只按年度总量保供'),
 ('水电','低碳电能与可调电源','全国装机之外还受来水及区域分布限制','national;renewables;research','水能预算、地区连接','常规水电和抽蓄分开；年发电不产生逐小时可靠出力'),
 ('核电','连续低碳电源候选','资本、折现和利用率改变平准成本排序','national;official2024;cost_comparison','建设队列、许可、运行','60年为成本报告经济假设，非所有机组实际获批寿命'),
 ('风电','新增低碳电量来源','年末装机增长与消纳、时序可用性分别约束','national;renewables;costs','可用率序列、建设、输送','年度利用率不当容量因子；年末容量不代平均容量'),
 ('光伏','新增低碳电量来源','项目电量成本低与持续服务能力是不同问题','national;renewables;costs','日内出力、储能、接网','太阳能与光伏口径分开；完整同服务储能配套成本缺失'),
 ('生物质','燃料型可再生电热来源','受原料收集和可持续供给上限约束','renewables;irena_capacity;research','原料预算、转换效率、碳账','不默认燃烧排放为零；OWID生物质与其他可再生不可相加'),
 ('氢能','二次载能体和工业原料','总产量中煤/气路线占比高，电解不等于绿氢','snapshots','制氢—储运—用氢链','制氢产能不等于产量；缺效率和绿电额外性，不重复计入一次能源'),
 ('储能','跨时段转移电能','2024新储能73.76GW/168.2GWh，公布时长2.3h；名牌规模不等于运行能力','renewables;snapshots;reviewed2024','连续SOC、充放功率、建设队列','同源正文168GWh仅精度核对；2025更新不回填2024；SOC、效率与可用率仍缺'),
 ('输送','连接发电地区与负荷地区','31省份额差异提示跨区协调需求','province;region_generation','跨区流量、容量、损耗','候选线路未准入；发用差额不是实测潮流或最大输电能力'),
 ('CCUS','难替代燃烧/过程的减排配套候选','需同时计捕集率、能耗、运输和永久封存','carbon','捕集净减排与资源消耗','本轮无可用全国同年量化初态；不得无限免费捕集或将捕集量当永久净移除')]


def handoff(history,indicators):
    role_rows=[]; hands=[]
    for name,role,weak,groups,target,limit in ROLES:
        refs=[r['record_id'] for r in history if r['dataset'] in groups.split(';') and r['year']==2024
              and r.get('precision_role')!='crosscheck_only' and (r['dataset']!='reviewed2024' or r['energy']==name)]
        role_rows.append(dict(energy=name,role=role,diagnosis=weak,evidence_datasets=groups,evidence_refs=';'.join(refs),model_location=target,limitation=limit))
        hands.append(dict(record_kind='energy_interface',energy=name,model_location=target,year=2024,candidate_refs=';'.join(refs),
            candidate_status='scoped_descriptive_candidate' if name!='CCUS' else 'blocked_no_capture_input',
            calibration_targets=groups,training_window='2015–2021 where observed',evaluation_window='2022–2024 already seen; not blind',
            constraint_or_gap=limit,formal_initialization='blocked pending same-year assets, stocks, efficiencies and use-specific admission'))
    for r in history:
        primary=(r['dataset']=='national' and 'gdp_growth_table_3_4' not in r['qualifier'] and 2015<=r['year']<=2024)
        snapshot=(r['dataset'] in ('products','renewables','snapshots','regional_resources','reviewed2024') and r['year']==2024
                  and r.get('precision_role')!='crosscheck_only')
        carbon=(r['dataset']=='carbon' and r['variable']=='Total' and 2015<=r['year']<=2024)
        if not (primary or snapshot or carbon):continue
        hands.append(dict(record_kind='numeric_observation_candidate',energy=r['energy'],model_location='state_or_calibration_target',year=r['year'],
            variable=r['variable'],value=r['value'],unit=r['unit'],region=r['region'],candidate_refs=r['record_id'],
            candidate_status='historical_target_candidate' if r['year']<2024 else '2024_state_or_target_candidate',
            training_window='2015–2021' if r['year']<=2021 else '',evaluation_window='2022–2024 already seen' if r['year']>=2022 else '',
            constraint_or_gap=r['boundary'],formal_initialization='requires model variable/boundary and contemporaneous stocks/assets review'))
    for r in indicators:
        hands.append(dict(record_kind='derived_diagnostic',energy='multiple',model_location='historical_diagnostic_or_constraint_reference',year=r['year'],
            variable=r['indicator_id'],value=r['value'],unit=r['unit'],candidate_refs=r['input_refs'],indicator_ref=r['indicator_id'],
            candidate_status=r['status'],constraint_or_gap=r['boundary'],formal_initialization='diagnostic; never a direct hourly limit or imposed target'))
    return role_rows,hands


def render_report(out,data,history,inds,balances,regions,origins,gaps,assessment,synergies):
    def ind(key,year=2024):return next(r['value'] for r in inds if r['indicator_id']==key and r['year']==year)
    def val(group,var,year):return one(data,group,var,year)['_value']
    text=['# 问题一：我国多能源发展现状评估（p1/lb）','',
          '研究日期：2026-10-18。共同起点：`7a65d068d19eea2f7dd8161a618a3ad8d66f98b8`。本报告是问题一三个子问题的修订候选，按独立评审修正C1/C2/L2/L3，等待独立复审与新增用途共同确认；此前完成判断已撤回。见[评审修订记录](../../../docs/solutions/p1-lb-review-response.md)。',
          '', '## 1. 主要判断', '',
          f"2015—2024年能源消费由{ind('energy_total',2015):.4f}增至{ind('energy_total'):.2f}亿吨标准煤（增长{(ind('energy_total')/ind('energy_total',2015)-1)*100:.2f}%）。煤炭份额由{ind('coal_share',2015):.1f}%降至{ind('coal_share'):.1f}%，但同表推导的煤炭标准煤消费量由{ind('coal_allocated_tce',2015):.4f}增至{ind('coal_allocated_tce'):.4f}亿吨。结构转型与绝对需求增长并存，不能只凭份额下降判断煤炭需求已见顶。", '',
          f"2023年同表净进口/消费：石油{ind('oil_net_import_ratio',2023):.2f}%、煤炭{ind('coal_net_import_ratio',2023):.2f}%。石油包括油品等原表边界，不能改称原油依存度。天然气进口中LNG占{ind('gas_imports_LNG_share'):.2f}%；全年分项用途说明工业与气电应共用气源约束，但不足以计算中断损失。", '',
          f"2024年31省发电份额与用电份额差异指标为{ind('spatial_share_difference'):.4f}。它衡量空间分布不同，不能直接变成实际跨省输电量或安全等级。成本对比则表明，折现率和利用率变化能改变煤、气、核电的排序，因此后续模型应保留资金与运行条件。", '',
          '## 2. 边界、来源与历史覆盖', '',
          '地理主线为中国大陆。统计局2025版同版历史为主，2015—2024为比较窗口；2005起部分序列作背景。2023细账、2024现状、2025更新和2020报告对2025的成本投影分别标记。研究数据库的China编制口径保留，未经桥接不混为同一套观测。', '',
          f"[history.csv](history.csv)含{len(history)}条已选来源记录；[coverage.csv](coverage.csv)逐系列列明缺年。[indicators.csv](indicators.csv)含{len(inds)}条指标记录、{len({r['indicator_id'] for r in inds})}个指标标识，含不同年份、参数变体及上下界，不代表独立指标数量。独立公报和研究汇编作为单独版本，不能因文件不同重复算独立样本。所有关键结果可由input_refs回到history中的原件定位，再由[输入锁定清单](../../../workflow/q1_inputs.json)回到原件哈希。", '',
          '## 3. 规模、结构与低碳', '',
          '|指标|2015|2024|口径|','|---|---:|---:|---|']
    for key,label in [('energy_total','消费/亿吨标准煤'),('coal_share','煤炭份额/%'),('energy_intensity_index','能耗强度/2015=100'),('co2_intensity_index','化石工业CO₂强度/2015=100')]:
        text.append(f'|{label}|{ind(key,2015):.3f}|{ind(key):.3f}|同序列指数；具体公式见指标表|')
    text+=['','强度分母为同版实际GDP增速连乘指数。全口径能耗强度不同于官方扣除原料及非化石用能的指标。GCB为属地化石和工业CO₂，包含过程排放且不含土地利用及净移除，不能代表全国净温室气体或证明碳中和。', '',
           '|年末装机/万kW|2015|2024|','|---|---:|---:|']
    for v,n in [('total_10kW','总装机'),('thermal_10kW','火电'),('hydro_10kW','水电'),('nuclear_10kW','核电'),('wind_10kW','风电'),('solar_10kW','太阳能')]:
        text.append(f"|{n}|{val('national',v,2015):,.0f}|{val('national',v,2024):,.0f}|")
    text+=['','|生产/发电规模|2015|2024|单位|','|---|---:|---:|---|']
    for group,v,label,scale,unit in [('national','production_10ktce','一次能源生产',10000,'亿吨标准煤'),
            ('products','raw_coal_100Mt','原煤产品产量',1,'亿吨'),('products','natural_gas_100Mm3','天然气产量',1,'亿立方米'),
            ('products','generation_100GWh','总发电量',10,'TWh')]:
        text.append(f"|{label}|{val(group,v,2015)/scale:.3f}|{val(group,v,2024)/scale:.3f}|{unit}|")
    text+=['','2035年国家自主贡献报告（2025发布，物理p5/印刷p3）直接给出2024年非化石能源占一次能源消费比重19.8%，状态为初步测算。本次独立登记该发布口径；其他年份未取得同版点值。统计局“一次电力及其他”保留原名，即使数值相同也不合并。天然气不算非化石。装机、发电和一次能源消费份额分别报告。火电含生物质、垃圾和余热等，不全部当化石发电。','',
           '|补充技术证据|2015|2024|单位/边界|','|---|---:|---:|---|']
    for v,label in [('coal_electricity','煤电'),('gas_electricity','气电'),('oil_electricity','油电'),('hydro_electricity','水电'),('nuclear_electricity','核电'),('wind_electricity','风电'),('solar_electricity','太阳能发电'),('biofuel_electricity','生物质发电')]:
        text.append(f"|{label}|{val('research',v,2015):.2f}|{val('research',v,2024):.2f}|TWh，OWID上游研究汇编，单独口径|")
    text+=['',f"2024年氢气总产量公布为超过{val('snapshots','hydrogen_output',2024):.0f}万吨；煤制、天然气制、副产、电解的公布近似分项合计3632万吨，比总量下限少18万吨，不能将18万吨当精确残差。电解路线按3650参考基数的比值为{ind('electrolysis_hydrogen_output_share'):.3f}%，不是精确份额，也不能全部改称绿氢。生物质装机/发电与新能源装机统计分别保留，不能重复计入其他可再生。"]
    text+=['','其他可再生与生物质部分重合，不加总。水电等数值与统计局/能源局不同，保留版本差异，不静默拼接。','',
           '## 4. 供给保障与国际暴露','','|净进口占消费/%|2015|2020|2022|2023|','|---|---:|---:|---:|---:|']
    for fuel,label in [('total','能源标准煤总账'),('oil','石油（含油品）'),('coal','煤炭'),('electricity','电力')]:
        text.append('|'+label+'|'+'|'.join(f'{ind(fuel+"_net_import_ratio",y):.2f}' for y in (2015,2020,2022,2023))+'|')
    text+=['','|2024进口来源|国家HHI下界|上界|主要来源份额|','|---|---:|---:|---|']
    for fuel in ('pipeline','lng','coal_trade'):
        top=sorted([r for r in origins if r['fuel']==fuel],key=lambda r:r['share_pct'],reverse=True)[:3]
        text.append(f"|{dict(pipeline='管道天然气',lng='液化天然气',coal_trade='煤炭')[fuel]}|{ind(fuel+'_HHI_lower'):.2f}|{ind(fuel+'_HHI_upper'):.2f}|"+'；'.join(f"{r['origin']} {r['share_pct']:.2f}%" for r in top)+'|')
    text+=['',f"2024年天然气用途：城市燃气{val('snapshots','gas_city_distribution_share',2024):.0f}%、工业燃料{val('snapshots','gas_industrial_fuel_share',2024):.0f}%、发电{val('snapshots','gas_power_share',2024):.0f}%、化工化肥{val('snapshots','gas_chemical_fertilizer_share',2024):.0f}%。这些是全年用途比例，只能说明共享气源的模型结构，不能作为缺气时的既定分配优先级。"]
    text+=['','地区合计桶存在时只报告国家HHI界；不假设桶内国家等份，不把集中度换成事件概率。EI天然气按40MJ/m³统一热值，和国内体积不直接拼接；煤炭EJ也不无依据换算万吨。原油国别结构未纳入本轮，保障分析的燃料覆盖保留此缺口。中东、欧美事件后续通过来源/通道、价格与技术条件进入，本轮不估计尚无依据的冲击幅度。','',
           '## 5. 经济性：可比案例与当前成本分开','','IEA/NEA 2020报告的中国项目案例采用2018美元、同一厂端电量服务、相同折现率/容量因子组和共同生命周期LCOE方法。经济寿命按技术分别为气30、煤40、核60年；不是人为统一寿命。碳价30美元/吨属于报告假设，非国内实际碳价。2025表示报告设定投产年。','','|容量因子|实际折现率|气电|煤电|核电|','|---:|---:|---:|---:|---:|']
    for cf,rate in ((85,3),(85,7),(85,10),(50,7)):
        text.append(f'|{cf}%|{rate}%|'+'|'.join(f"{ind(f'LCOE_{t}_CF{cf}_r{rate}',2025):.2f}" for t in ('CCGT','Coal_USC','Nuclear_LWR'))+'|')
    text+=['','单位：2018 USD/MWh。CF85%、折现7%时核电最低；折现10%时煤电低于核电；同为7%折现、CF降至50%时核电成本高于煤气。这个比较仅支持融资/利用率敏感性，不构成2024实际成本排序，也不保证同等可靠性、调峰或备用服务。','',
           'IRENA 2024中国陆上风电、光伏、海上风电LCOE分别见下表。它们采用2024美元、25年经济寿命和报告技术/国家特定WACC，不能假称三个技术一律5%融资；不与上述2018美元案例作价格高低总排名。','','|技术|LCOE原值|单位|','|---|---:|---|']
    for r in data['costs']:
        if 'LCOE' in r['variable']:
            label={'onshore_wind_LCOE':'陆上风电','utility_solar_PV_LCOE':'地面光伏','offshore_wind_LCOE':'海上风电'}[r['variable']]
            text.append(f"|{label}|{r['_value']}|{r['unit']}|")
    text+=['','|国际年均价格序列|年度对数变化标准差|有效收益率数|','|---|---:|---:|']
    for r in inds:
        if r['indicator_id'].startswith('price_log_volatility_'):
            metadata=json.loads(r['boundary']);value=f"{r['value']:.4f}" if r['value'] is not None else '不足2个变化，不计算'
            text.append(f"|{r['indicator_id'].replace('price_log_volatility_','')} ({r['effective_years']})|{value}|{metadata['n_returns']}|")
    text+=['','观察窗口2015—2024，原始年值覆盖不等于同口径可比覆盖。澳煤2015—2021为Newcastle 6000 kcal/kg现货，6个有效变化；2022年2月更换期货，混合年度2022保留但不参与收益率；2023—2024期货仅1个变化，不计算样本标准差。欧洲气价2015年4月改TTF，混合年度2015不参与收益率；TTF 2016—2023共7个变化；2024年度2.00与季度不相容另行排除。另四条序列各9个变化。各段有效相邻对逐项保存在指标boundary中，禁止跨段合成全窗口SD。原争议工作簿继续隔离，版本和舍入差异保留。国际年均基准不是中国交付价，不识别短期尾部或冲击因果。','',
           '## 6. 区域协调与调节','','|产品|2024年产量前三省|占同表全国产量|','|---|---|---:|']
    for var,label in [('raw_coal_100Mt','原煤'),('natural_gas_100Mm3','天然气'),('hydro_generation_100GWh','水电')]:
        rs=select(data,'regional_resources',var,2024)
        text.append(f"|{label}|"+'、'.join(r['region'] for r in rs)+f"|{ind('top3_production_'+var):.2f}%|")
    text+=['','前三省依据同一原图全列核对后选录；原表空白不补零。这说明生产资源集中与东部大负荷之间存在协调要求，不能仅凭集中度给地区安全评级。核电、光伏及风光消纳地区资料已补，见第11—13节；其他地区细分缺项不由此表外推。', '',
           '|地区|发电量|用电量|发电份额−用电份额/百分点|','|---|---:|---:|---:|']
    ordered=sorted(regions,key=lambda r:r['share_difference_pp'])
    for r in ordered[:5]+list(reversed(ordered[-5:])):
        text.append(f"|{r['region']}|{r['generation']:.2f}|{r['consumption']:.2f}|{r['share_difference_pp']:.3f}|")
    text+=['','发用电量单位为亿kWh。完整31省见[regional_comparison.csv](regional_comparison.csv)。差额涉及统计边界、损耗与跨区交换，不能直接当线路输电能力。', '',
           '|调节证据|年份|值|单位|','|---|---:|---:|---|']
    for r in inds:
        if r['dimension']=='协调' and ('utilization' in r['indicator_id'] or 'storage' in r['indicator_id'] or 'pumped' in r['indicator_id']):
            text.append(f"|{r['indicator_id']}|{r['year']}|{r['value']}|{r['unit']}|")
    text+=['','2025发布的新型储能报告实际描述2024年：全国73.76GW，图1能量168.2GWh，正文约168GWh仅作同源精度核对，不相加或平均；公布时长2.3h。图1的2021—2024历史与图2六大区域功率份额一并保留，地区量属于全国子集。华北22.24GW/49.42GWh，西北18.71GW/52.01GWh。SOC、效率、逐时可用率仍缺，名牌容量和公布时长不保证极端时段服务。2025运行更新仍单独展示。利用率不是容量因子；输电候选数据未解除隔离。', '',
           '## 7. 九类能源与配套的模型位置','','|能源|角色|短板及下一步|','|---|---|---|']
    for name,role,weak,groups,target,limit in ROLES:text.append(f'|{name}|{role}|{weak}；后续接入{target}；{limit}|')
    text+=['','## 8. 静态核对与交接','','|2023账本|单位|供给算术差|用量算术差|公布供给−消费|公布平衡差|','|---|---|---:|---:|---:|---:|']
    for b in balances:
        if b.get('year')==2023 and 'supply_arithmetic_residual' in b:
            text.append(f"|{b['account']}|{b['unit']}|{b['supply_arithmetic_residual']:.0f}|{b['use_arithmetic_residual']:.0f}|{b['published_supply_minus_consumption']:.0f}|{b['published_balance']}|")
    text+=['','算术差是公式计算与原表公布量之差；公布供需差是统计账本本身的残差，二者不能混同。1个末位单位的差保留；大额统计差不擅自分摊为库存或损耗。GCB仅进行同表分项求和，不以此冒充能源到碳的独立闭合。煤炭产品产量与平衡表产量不同，按用途分开。', '',
           '[static_balance.json](static_balance.json)保留所有检查点及原值；[model_handoff.csv](model_handoff.csv)列出初态候选、校准目标、约束与阻断项。后续训练2015—2021、评估2022—2024；评估段已接触，不称盲测。本轮没有建立全国真实完整初态、小时调度或未来预测。', '',
           '## 9. 结果图与缺口边界','','![需求及煤炭消费指数](demand_trends.svg)', '',
           '图1：按2015=100比较需求与实际GDP。份额下降不代表煤炭标准煤消费绝对量下降。', '',
           '![融资条件与可比成本](cost_sensitivity.svg)', '',
           '图2：同容量因子下折现率变化；仅适用于报告给定的价格、寿命和厂端服务。', '',
           '![31省中份额差异最大的十省](regional_shares.svg)', '',
           '图3：发电份额减用电份额最负及最正的各五省；完整31省用于指标计算。', '',
           '四维都有定量证据，未做加权总分或全国安全评级。缺口详见[gaps_and_conflicts.csv](gaps_and_conflicts.csv)：欧洲气价2024异常单元格、原油国别和部分能源细项仍保留；天然气同口径净进口、全技术同等可靠服务成本、连续运行序列、同年库存资产、CCUS与完整净排放等限制后续仿真，不是本轮描述结果。', '',
           '本报告的作用是把已知现状、可比较的证据和模型约束交清。数据缺口不由演示参数补齐；工程检查通过不等于完成全国校准或外部评审。','',
           '## 10. 复现与核验','','```powershell','python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_lb','python -B -X utf8 run.py test','python -B -X utf8 run.py audit','python -B -X utf8 scripts/scan_google_keys.py','```','',
           f'运行离线检查{len(data)}个处理输入及原件指纹；输入被改动时返回非零。每次结果附[run_manifest.json](run_manifest.json)。首次用途审查见[审查记录](../../../docs/solutions/p1-lb-input-review.md)。配置不是自动准入工具；研究状态、输入哈希与原契约分别保留。']
    from q1_additional_analysis import report_sections
    text+=report_sections(data,inds,assessment,synergies)
    (out/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True,encoding='utf-8').strip()


def run(output_dir):
    out=local_path(output_dir)
    allowed=ROOT/'outputs/q1'
    if not out.is_relative_to(allowed) or out==allowed:raise ValueError('Q1 output must be a child of outputs/q1')
    if out.exists() and any(out.iterdir()):
        manifest=out/'run_manifest.json'
        if not manifest.is_file() or json.loads(manifest.read_text(encoding='utf-8')).get('owner')!='p1/lb':
            raise ValueError('Refusing to overwrite unowned result directory')
    config_path=ROOT/'workflow/q1_inputs.json'
    run_id=uuid.uuid4().hex
    attempt=out.parent/(out.name+'.latest-attempt.json')
    stage=out.parent/('.q1-stage-'+run_id); backup=None
    stage.mkdir(parents=True)
    try:
        dump(attempt,dict(run_id=run_id,status='running',output_valid_for_this_attempt=False))
        config=json.loads(config_path.read_text(encoding='utf-8')); preflight(config)
        data,history=load_history(config)
        inds,balances,regions,origins,gaps=calculate(data)
        from q1_additional_analysis import derive,synthesize
        inds+=derive(data)
        assessment,synergies=synthesize(data,history,inds)
        for item,reason,impact in [
            ('net_gas_import_ratio','匹配出口与消费边界未齐','不将毛进口比称净依赖'),
            ('crude_country_origins','本轮未准入原油国别表','原油来源集中度不计算'),
            ('same_reliability_system_cost','厂端LCOE不含统一调峰/备用/网络服务','不做全技术保供成本排名'),
            ('net_zero_carbon','无完整移除/非能源净温室气体路径','不推断碳中和'),
            ('CCUS','无同年全国捕集/封存/能耗初态','不生成捕集量或减排率'),
            ('2024_initialization','库存、资产年龄、设备效率、建设队列未齐','所有Q2状态只为候选'),
            ('hydro_scope','NBS/NEA/研究库水电边界不同','版本分别保存不拼接'),
            ('coal_production_scope','产品产量与平衡表生产量不同','按原表用途不替换'),
            ('regional_time_series','仅2015/2020/2023/2024用电截面','不插值为年面板'),
            ('technology_province_panel','已补光伏32统计地区与核电8省；煤气水电前三省、风电新增区域与分区消纳；生物质完整省级量表仍缺','不据总发电差异分摊每种能源，不声称完整多年地区面板'),
            ('biomass_nonpower','生物天然气有行业估计；完整供热与液体燃料表未取得，公开报道供热单位可疑而排除','不把生物质发电代表所有生物质用途'),
            ('nuclear_publication_scope','核电地区并网容量总6088.094与年鉴6083万kW不同','发布口径/容量取值未完全桥接，各自展示不拼接'),
            ('cost_reference_periods','水电2018—2024样本、生物质2000—2024样本、煤气核旧投影与2024风光成本时期不同','分表比较，不生成跨年份跨服务全能源成本排行榜'),
            ('nonfossil_primary_share_history','已提取NDC独立发布2024初步测算19.8%；同版其他年份仍缺','不把NBS一次电力及其他合并为该序列；不以发电份额替代'),
            ('storage_operating_state','已补2024新型储能功率/能量与公布时长；SOC、效率和逐时可用率未齐','仅作名牌规模候选，不能初始化可调运行能力'),
            ('hourly_reliability','同期时序、输送和提取上限未齐','不输出停电概率'),
            ('hydrogen_history','产量路线主要为2024截面；电解非全绿氢','不编造十年历史')]:
            gaps.append(dict(item=item,years='scope dependent',status='gap_or_boundary_conflict',reason=reason,impact=impact,action='保留空缺，后续用途核验'))
        roles,hands=handoff(history,inds)
        for name,rows in [('history',history),('indicators',inds),('energy_roles',roles),('model_handoff',hands),
                          ('gaps_and_conflicts',gaps),('regional_comparison',regions),('import_origins',origins),('coverage',coverage(history)),
                          ('energy_assessment',assessment),('synergy_assessment',synergies),
                          ('renewable_regions',[r for r in history if r['dataset']=='renewable_regions']),
                          ('technology_region_capacities',[r for r in history if r['dataset']=='technology_regions'])]:csvout(stage/(name+'.csv'),rows)
        dump(stage/'static_balance.json',dict(checks=balances,independent_energy_to_carbon='blocked: matched fuel/use factors and noncombustion split missing'))
        from plot_q1 import build as plot
        plot(stage,inds,regions,data['prices'])
        render_report(stage,data,history,inds,balances,regions,origins,gaps,assessment,synergies)
        record=dict(owner='p1/lb',status='success',run_id=run_id,scientific_scope='Q1 scoped assessment; no national ABM or external acceptance',
                    command=['python','-B','-X','utf8','run.py','q1','--output-dir',Path(output_dir).as_posix()],
                    python=sys.version,platform=platform.platform(),dependencies={'runtime':'Python >=3.11','reportlab':importlib.metadata.version('reportlab')},
                    git_sha=git('rev-parse','HEAD'),git_dirty=bool(git('status','--porcelain')),git_status=git('status','--porcelain'),
                    base_sha=config['base_sha'],config_path='workflow/q1_inputs.json',config_sha256=sha(config_path),
                    code_hashes={p:sha(ROOT/p) for p in CODE_PATHS},inputs=config['inputs'],sources=config['sources'],
                    config=config['decisions'],counts=dict(history=len(history),indicators=len(inds),regions=len(regions)),
                    outputs={p.name:sha(p) for p in sorted(stage.iterdir())})
        dump(stage/'run_manifest.json',record)
        if out.exists():
            backup=out.parent/('.q1-backup-'+uuid.uuid4().hex); out.rename(backup)
        try:stage.rename(out)
        except Exception:
            if backup:backup.rename(out)
            raise
        if backup:shutil.rmtree(backup)
        dump(attempt,dict(run_id=run_id,status='success',output_valid_for_this_attempt=True,
                          manifest_sha256=sha(out/'run_manifest.json')))
        print(json.dumps(dict(status='success',output=str(out),counts=record['counts']),ensure_ascii=False))
        return 0
    except Exception as exc:
        # Failure evidence is separate; a previous successful result is never relabelled as this failed attempt.
        failure=out.parent/(out.name+'.failed-attempt.json')
        failure_record=dict(run_id=run_id,status='failed',output_valid_for_this_attempt=False,error=str(exc),command_output=output_dir)
        dump(failure,failure_record)
        dump(attempt,failure_record)
        print(f'Q1 FAILED: {exc}',file=sys.stderr)
        return 1
    finally:
        if stage.exists():shutil.rmtree(stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    try:raise SystemExit(run(args.output_dir))
    except (ValueError,OSError) as exc:print(f'Q1 FAILED: {exc}',file=sys.stderr);raise SystemExit(1)
