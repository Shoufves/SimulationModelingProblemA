"""Q1 per-carrier diagnosis and conditional synergy synthesis from reviewed inputs."""
from energy_model.q1 import ratio

ENERGIES=['煤炭','石油','天然气','水电','核电','风电','光伏','生物质','氢能']

def derive(data):
    out=[]
    def get(group,var,year=2024,**kw):
        rs=[r for r in data[group] if r.get('variable')==var and r['year']==year and all(r.get(k)==v for k,v in kw.items())]
        if len(rs)!=1:raise ValueError(('Additional observation ambiguous/missing',group,var,year,kw))
        return rs[0]
    def add(key,dim,value,unit,refs,formula,boundary,year=2024,status='calculated'):
        out.append(dict(indicator_id=key,dimension=dim,year=year,value=value,unit=unit,direction='context',formula=formula,
            input_refs=';'.join(r['_id'] for r in refs),effective_years=str(year),status=status,boundary=boundary))
    for r in data['context']:
        var=r['variable']
        dim='经济' if any(t in var for t in ('price','LCOE','capex')) else ('低碳' if 'CO2' in var else '协调')
        add(var,dim,r['_value'],r['unit'],[r],'published scoped value',r['boundary'],r['year'],r['status'])
    # Same published imports table: value/quantity, not homogeneous transaction price.
    for fuel in ['coal_lignite','crude_oil','natural_gas']:
        qty=get('official2024',fuel+'_import_quantity');value=get('official2024',fuel+'_import_value')
        if qty['unit']!='万吨' or value['unit']!='亿元':raise ValueError('Import unit-value units mismatch')
        add(fuel+'_import_unit_value','经济',ratio(value['_value'],qty['_value'],10000),'CNY/t',[qty,value],
            'import value (100 million CNY) / import quantity (10 thousand t) * 10000',
            '2024 gross import unit value, mixes grades/origins/contracts; not domestic delivered price or constant-quality spot quotation')
    prod=get('snapshots','gas_production');imp=get('snapshots','gas_imports_total')
    if prod['unit']!=imp['unit']:raise ValueError('Gas supply units mismatch')
    add('gas_gross_supply_import_share','保障',ratio(imp['_value'],prod['_value']+imp['_value']),'%',[prod,imp],
        'gross imports / (domestic production + gross imports) *100','Gross supply composition, excludes exports/inventory changes; not net import dependence')
    industrial=get('snapshots','gas_industrial_fuel_share');power=get('snapshots','gas_power_share')
    add('gas_industry_power_combined_share','协调',industrial['_value']+power['_value'],'%',[industrial,power],
        'published industrial fuel share + power share','Annual use share; not shortage rationing priority or hourly demand')
    gen=get('official2024','generation_total')
    for fuel in ['hydro','nuclear','wind','solar']:
        r=get('official2024','generation_'+fuel)
        if r['unit']!=gen['unit']:raise ValueError('Generation share units mismatch')
        add(fuel+'_official_generation_share','低碳',ratio(r['_value'],gen['_value']),'%',[r,gen],
            'same-release generation / total generation *100','Generation share, not primary consumption share or avoided-emissions estimate; solar includes non-PV')
    for var,n in [('pv_capacity',5),('nuclear_grid_connected_capacity',3)]:
        rs=[r for r in data['technology_regions'] if r['variable']==var]
        total=get('technology_regions',var,region='全国');regions=[r for r in rs if r['region']!='全国']
        if len(regions)!=(32 if var=='pv_capacity' else 8) or any(r['unit']!=total['unit'] for r in regions):
            raise ValueError('Technology region coverage/unit mismatch')
        selected=sorted(regions,key=lambda r:r['_value'],reverse=True)[:n]
        add(f'top{n}_'+var+'_share','协调',ratio(sum(r['_value'] for r in selected),total['_value']),'%',selected+[total],
            f'sum(top {n} reporting-area capacities)/same-source total *100',
            'Selected: '+','.join(r['region'] for r in selected)+'; PV XPCC separately reported; not outage correlation')
    total=get('technology_regions','pv_capacity',region='全国');distributed=get('technology_regions','pv_distributed_capacity',region='全国')
    add('pv_distributed_capacity_share','协调',ratio(distributed['_value'],total['_value']),'%',[distributed,total],
        'distributed PV / total PV *100','Year-end grid-connected capacity, not generation or self-consumption share')
    for var in ['renewable_consumption_share','nonhydro_renewable_consumption_share']:
        nat=get('renewable_regions',var,region='全国')
        add('nea_'+var,'低碳',nat['_value'],'%',[nat],'published national responsibility-accounting share',nat['boundary'])
        actual=[r for r in data['renewable_regions'] if r['variable']==var and r['region']!='全国']
        target=[r for r in data['renewable_regions'] if r['variable']==var+'_minimum']
        if len(actual)!=31 or len(target)!=29:raise ValueError('Responsibility target coverage mismatch')
        pairs=[(a,t) for a in actual for t in target if a['region']==t['region']]
        below=[a['region'] for a,t in pairs if a['_value']<t['_value']-1e-8]
        add(var+'_below_target_count','协调',len(below),'provinces',[r for pair in pairs for r in pair],
            'count(actual < published target); only 29 assessed provinces',
            'Below target: '+','.join(below)+'; Tibet exempt, Xinjiang monitoring only; not 31-province failure rate')
    for var in ['wind_utilization_rate','pv_utilization_rate','hydro_basin_utilization_rate']:
        rs=[r for r in data['renewable_regions'] if r['variable']==var and r['year']==2024 and r['region']!='全国']
        worst=min(rs,key=lambda r:r['_value'])
        add('minimum_'+var,'协调',worst['_value'],'%',rs,'minimum reported regional/basin utilization',
            'Minimum region: '+worst['region']+'; no weighting; small-area minimum is not national average or capacity factor')
    renewable=get('context','UHV_DC_renewable_delivery');delivery=get('context','UHV_DC_delivery')
    add('UHV_DC_renewable_share','协调',ratio(renewable['_value'],delivery['_value']),'%',[renewable,delivery],
        'renewable electricity / all electricity delivered by same 20 UHV DC lines *100','Annual actual delivery mix, not all transmission, topology or capacity')
    gas=get('context','natural_gas_CO2_default',2006);coal=get('context','other_bituminous_coal_CO2_default',2006)
    add('gas_vs_coal_combustion_factor_reduction','低碳',(1-gas['_value']/coal['_value'])*100,'%',[gas,coal],
        '(1 - gas reference combustion factor / other bituminous coal factor)*100',
        'Same NCV fuel heat only; not lifecycle power intensity; upstream methane and conversion efficiency excluded',year=2006,status='reference_parameter_comparison')
    return out

def synthesize(data,history,indicators):
    """Each claim carries its actual observation IDs, never a simulated benefit."""
    index={(r['indicator_id'],str(r['year'])):r for r in indicators}
    def I(key,year=2024):return index[(key,str(year))]
    def v(key,year=2024):return I(key,year)['value']
    def H(group,var,year=2024):
        rs=[r for r in history if r['dataset']==group and r['variable']==var and r['year']==year]
        if not rs:raise ValueError(('Missing synthesis evidence',group,var,year))
        return rs
    assessment=[]
    def A(energy,dimension,claim,interpretation,limits,keys=(),observations=()):
        refs=[]
        for k in keys:
            key,year=(k,2024) if isinstance(k,str) else k
            refs.extend(I(key,year)['input_refs'].split(';'))
        for group,var,year in observations:refs.extend(r['record_id'] for r in H(group,var,year))
        assessment.append(dict(energy=energy,dimension=dimension,evidence=claim,diagnosis=interpretation,
            boundary=limits,input_refs=';'.join(dict.fromkeys(refs)),status='descriptive_evidence_with_scope'))
    A('煤炭','保障',f"2023净进口/消费{v('coal_net_import_ratio',2023):.2f}%",'国内供给基础较强，仍受资源集中及运输制约','不能以低进口比推出无保供风险',keys=[('coal_net_import_ratio',2023)])
    A('煤炭','低碳',f"2024消费份额{v('coal_share'):.1f}%，推导消费{v('coal_allocated_tce'):.4f}亿吨标准煤",'份额下降而绝对消费仍高，是转型减排重点','标准煤量不是实物量或直接排放',keys=['coal_share','coal_allocated_tce'])
    A('煤炭','经济',f"2024进口单位价值{v('coal_lignite_import_unit_value'):.1f}元/吨；有同服务煤气核LCOE敏感性",'燃料采购与利用率同时影响经济性，保留调节服务成本','进口混合单位价值非国内煤价；LCOE是旧报告投影',keys=['coal_lignite_import_unit_value',('LCOE_Coal_USC_CF85_r7',2025)])
    A('煤炭','协调',f"原煤前三省占产量{v('top3_production_raw_coal_100Mt'):.2f}%",'资源集中与电热负荷分布需要运输和灵活性配套','集中度不等于失供概率',keys=['top3_production_raw_coal_100Mt'])
    A('石油','保障',f"2023含油品净进口/消费{v('oil_net_import_ratio',2023):.2f}%",'对外依赖突出，应区分原油、油品、原料用途及运输通道','未核验2024国别表，不能给原油国家HHI',keys=[('oil_net_import_ratio',2023)])
    A('石油','低碳','2024一次能源消费份额18.2%；IPCC原油燃烧参考因子73300 kgCO₂/TJ', '交通与化工用途须分开，原料不能全部按即时燃烧计排放','因子为2006 NCV默认值，不是中国生命周期实测',keys=[('crude_oil_CO2_default',2006)],observations=[('national','consumption_oil_pct',2024)])
    A('石油','经济',f"2024原油进口单位价值{v('crude_oil_import_unit_value'):.1f}元/吨",'国际价格变化可通过进口成本传导，电动替代须按同运输服务比较','不将原油吨价与电力kWh成本排名',keys=['crude_oil_import_unit_value'],observations=[('prices','Crude oil, Brent',2024)])
    A('石油','协调','2023石油平衡表分列最终消费和加工转换投入','交通替代、炼化原料和生物液体燃料应分别接入','未提取完整省级炼化/消费面板；不把油电当全部石油用途',observations=[('balance','final_consumption',2023),('research','oil_consumption',2024)])
    A('天然气','保障',f"毛进口占生产加毛进口{v('gas_gross_supply_import_share'):.2f}%",'管道和LNG来源各异，可用作进口暴露的分组依据','不含出口库存调整，不称净进口依存度',keys=['gas_gross_supply_import_share','gas_imports_LNG_share'])
    A('天然气','低碳',f"同热值直接燃烧默认因子比烟煤低{v('gas_vs_coal_combustion_factor_reduction',2006):.2f}%",'可在适用终端替煤，但天然气仍是化石能源','未包括甲烷泄漏、效率和全生命周期排放',keys=[('gas_vs_coal_combustion_factor_reduction',2006)])
    A('天然气','经济',f"2024进口单位价值{v('natural_gas_import_unit_value'):.1f}元/吨；TTF现货10.9美元/MMBtu",'燃料及区域价格差影响调峰和工业替代的经济边界','混合单位价值与现货定义不同，不能无依据相加或换体积',keys=['natural_gas_import_unit_value','gas_TTF_spot_price'])
    A('天然气','协调',f"工业燃料与发电合计占用途{v('gas_industry_power_combined_share'):.0f}%",'二者必须共享气源，不能分别假设有无限供应','年度比例不是短缺分配优先级',keys=['gas_industry_power_combined_share'])
    for name,fuel,genvar in [('水电','hydro','hydro_generation'),('核电','nuclear','generation_nuclear'),('风电','wind','wind_generation'),('光伏','solar','solar_PV_generation')]:
        group='official2024' if name=='核电' else 'renewables'
        r=H(group,genvar)[0]
        A(name,'保障',f"2024公布发电量{r['value']:g} {r['unit']}",
          {'水电':'提供大规模电能与有条件的调节能力，受来水制约','核电':'提供连续发电的资产基础，需计检修、建设与许可约束','风电':'本土资源扩大电量供给，随天气变化','光伏':'本土资源与分布式建设扩大供给，日内出力不均'}[name],
          '年电量不等于任意时段可靠容量；不同发布口径分列',observations=[(group,genvar,2024)])
        A(name,'低碳',f"同一统计公报中{('太阳能' if name=='光伏' else name)}发电占比{v(fuel+'_official_generation_share'):.2f}%",'体现非燃烧电源对电力结构的贡献','不是一次能源消费份额、生命周期零排放或已实现替代减排量；太阳能含非光伏',keys=[fuel+'_official_generation_share'])
    A('水电','经济','中国2018—2024投产样本大/小水电装机成本2216/1873（2024美元/kW）','站址和工程条件差异大，需项目级资本及来水条件','不能以大小水电单位造价直接推导LCOE排名；非2024单年',keys=['hydro_large_capex','hydro_small_capex'])
    A('水电','协调',f"发电前三省占{v('top3_production_hydro_generation_100GWh'):.2f}%，8流域最低水能利用率{v('minimum_hydro_basin_utilization_rate'):.2f}%",'西南水电与受端负荷、风光需联合考虑水能预算及输送','高利用率不证明枯水期充足；有调节库容与径流式电站区别',keys=['top3_production_hydro_generation_100GWh','minimum_hydro_basin_utilization_rate'])
    A('核电','经济','同CF85%下折现3/7/10%的LCOE案例及CF50%敏感性已复算','长寿命重资本使融资和利用率成为关键','2020报告设定2025投产、2018美元；不称2024实际成本',keys=[('LCOE_Nuclear_LWR_CF85_r7',2025),('LCOE_Nuclear_LWR_CF50_r7',2025)])
    A('核电','协调',f"并网容量分布8个沿海省份，前三省占{v('top3_nuclear_grid_connected_capacity_share'):.2f}%",'与沿海负荷相邻的布局有利于本地供给，但要计接网与检修','5.094万kW的区域图总量与年鉴差异保留，不强行统一发布口径',keys=['top3_nuclear_grid_connected_capacity_share'])
    A('风电','经济','2024中国陆上/海上LCOE为0.029/0.056美元/kWh','项目电量成本具有吸引力；调节及网络成本另计','项目WACC和容量因子不同，不是同可靠服务成本',observations=[('costs','onshore_wind_LCOE',2024),('costs','offshore_wind_LCOE',2024)])
    A('风电','协调',f"新增装机75%在三北；全国利用率95.9%，分地区最低{v('minimum_wind_utilization_rate'):.1f}%",'新增供给集中地区需消纳与外送配套','75%仅新增装机；最低地区为西藏，不能代表全国或装机加权情况',keys=['wind_new_capacity_three_north_share','minimum_wind_utilization_rate'],observations=[('renewables','wind_energy_utilization_rate',2024)])
    A('光伏','经济','2024中国地面光伏LCOE为0.033美元/kWh','电量经济性良好；午间集中出力使时段价值和配储影响收益','不含同等保供系统成本，不代表户用电价',observations=[('costs','utility_solar_PV_LCOE',2024)])
    A('光伏','协调',f"分布式占年末装机{v('pv_distributed_capacity_share'):.2f}%；分地区最低利用率{v('minimum_pv_utilization_rate'):.1f}%",'集中式需要跨区消纳，分布式需要配网与本地负荷协调','装机比例不是自用电比例；最低地区西藏不代表全国',keys=['pv_distributed_capacity_share','minimum_pv_utilization_rate'])
    A('生物质','保障','2024发电208.3TWh；公开行业报告摘要估计生物天然气约5亿m³','可提供可储燃料型电热与气体，非电用途已单列','原料收集半径、竞争用途、季节性未形成全国上限；行业数为补充',observations=[('renewables','biomass_generation',2024)],keys=['bio_natural_gas_output'])
    A('生物质','低碳','2024生物质装机45.99GW，发电208.3TWh','有替代化石电热的潜力，但须跟踪原料及碳循环','不默认燃烧或全生命周期排放为零，不把垃圾全视为生物碳',observations=[('renewables','biomass_capacity',2024),('renewables','biomass_generation',2024)])
    A('生物质','经济','中国2000—2024样本LCOE加权0.064，5/95分位0.048/0.130美元/kWh','项目差异显著；原料、环保与供热收益影响经济性','2024不变美元、多年样本；非2024项目总体、分位非置信区间',keys=['bioenergy_LCOE','bioenergy_LCOE_p05','bioenergy_LCOE_p95'])
    A('生物质','协调','行业摘要农林/垃圾焚烧装机约1709/2738万kW，沿海与资源分布关联','优先考察就地热电联产；生物燃料、独立电厂与煤电掺烧竞争原料','地区判断来自行业公开解读，完整分省量表未获；不能推出全国统一掺烧比例',keys=['bio_agroforest_capacity','bio_waste_incineration_capacity'])
    A('氢能','保障','2024总产量超过3650万吨，建成可再生制氢产能约12.5万吨/年','现有工业规模与新可再生路线规模相差大，应分账','总量含原料；能力不等于产量，不加到一次能源总量',observations=[('snapshots','hydrogen_output',2024),('snapshots','renewable_hydrogen_capacity',2024)])
    A('氢能','低碳','煤/气路线约2070/760万吨，电解约32万吨','化石路线主导，氢不是天然低碳载能体','总产量为下限、分项为近似数；电解不等于绿氢',observations=[('snapshots','coal_hydrogen_output',2024),('snapshots','gas_hydrogen_output',2024),('snapshots','electrolysis_hydrogen_output',2024)])
    A('氢能','经济','2024年12月生产/消费侧价格指数28.0/48.6元/kg','高纯氢出厂与加氢站燃料价格表明用氢环节和样本边界影响经济性','生产样本不含煤制氢；消费样本为加氢站，非化工到厂价；两侧未配对，差额非运输费或利润',keys=['hydrogen_production_price_december','hydrogen_consumption_price_december'])
    A('氢能','协调','建成可再生制氢能力华北/西北占45%/44%；甲醇/氨耗氢占27%/26%','先研究有工业用氢负荷的风光制氢与原料替代','不能从地区份额证明绿电额外性或把规划项目计为运行能力',keys=['renewable_hydrogen_north_capacity_share','renewable_hydrogen_northwest_capacity_share','hydrogen_methanol_use_share','hydrogen_ammonia_use_share'])
    if len(assessment)!=36 or {(r['energy'],r['dimension']) for r in assessment}!={(e,d) for e in ENERGIES for d in ['保障','低碳','经济','协调']}:
        raise ValueError('Incomplete per-energy assessment')
    synergies=[]
    def S(key,energies,evidence,mechanism,conditions,risks,metrics,keys):
        refs=[]
        for k in keys:
            indicator_key,year=(k,2024) if isinstance(k,str) else k
            refs.extend(I(indicator_key,year)['input_refs'].split(';'))
        synergies.append(dict(synergy_id=key,energies=energies,evidence=evidence,mechanism=mechanism,
            applicable_conditions=conditions,tradeoff_or_failure=risks,next_model_test=metrics,
            input_refs=';'.join(dict.fromkeys(refs)),status='conditional_direction_not_simulated_benefit'))
    S('SYN01','风电;光伏;储能;输送','三北占新增风电75%；风光地区利用率存在差异；20条直流可再生电量占比可复算',
      '储能转移时段、输送连接地区、需求响应匹配可用电量','有接网/输送余量、适用储能时长及可转移负荷，项目按工期投运',
      '多日低风低光时短时储能无补能；配储不是自动提高可靠容量','弃电、未供能、峰时缺额、总费用；同预算比较单独与联合配套',
        ['wind_new_capacity_three_north_share','minimum_wind_utilization_rate','minimum_pv_utilization_rate','UHV_DC_renewable_share','new_storage_power','new_storage_energy'])
    S('SYN02','水电;风电;光伏;输送','水电生产集中于川滇鄂；流域利用率有差异','水库在水能预算内调节，与风光共同供给受端',
      '需有可调库容、生态下泄约束及同一时期来水与风光资料','枯水与天气相关性可能削弱互补；不能把水能利用率当容量因子',
      '丰枯水敏感性、联合缺额、弃水弃风光与输送瓶颈',['top3_production_hydro_generation_100GWh','minimum_hydro_basin_utilization_rate'])
    S('SYN03','煤炭;风电;光伏;储能','煤炭份额53.2%且绝对消费仍高','灵活煤电与低碳电量配合，储能减少频繁启停和尖峰需求',
      '满足最小出力、爬坡、供热、燃料和碳预算，不把退役资产当备用','降利用率会抬高固定成本；只保装机可能锁定排放',
      '燃煤、排放、启停、未供能与全成本联合比较',['coal_share','coal_allocated_tce','pv_distributed_capacity_share'])
    S('SYN04','天然气;工业用能;电力','工业燃料加发电占用气59%；进口来源分LNG/管道','共享气源约束下协调气电调峰、工业替代和应急需求',
      '气源/接收/管网/储气能力分别受限，保民生规则明确','工业与电力同时受冲击；年度供气充足不保证小时送达',
      '共享燃料的联合缺供与部门分布，避免双重计入气源',['gas_industry_power_combined_share','gas_gross_supply_import_share'])
    S('SYN05','核电;风电;光伏;需求响应','核电集中沿海8省；光伏分布式比例较高','连续低碳供给与时段可转移需求相配合',
      '保留核电运行许可/检修及技术调节范围，负荷转移上限有证据','并非所有核电机组都可深调；低利用率削弱重资本经济性',
      '相同终端服务下的弃电、核电利用小时及系统费用',['top3_nuclear_grid_connected_capacity_share','pv_distributed_capacity_share'])
    S('SYN06','生物质;煤炭;工业热;生物燃料','农林/垃圾焚烧容量和生物天然气规模已分列','就地热电联产或替代气体/液体燃料，按服务而非电量分配原料',
      '可持续原料预算、运输半径、稳定热负荷和环保边界','掺烧、电厂和燃料路线竞争同一原料；燃烧碳不自动归零',
      '同原料上限下供电供热/燃料服务、净排放与成本',['bio_agroforest_capacity','bio_waste_incineration_capacity','bio_natural_gas_output'])
    S('SYN07','风电;光伏;氢能;化工','华北/西北可再生制氢能力集中；甲醇/氨为主要耗氢用途','用低碳电力替代部分化石制氢，优先衔接稳定工业原料需求',
      '电解效率、绿电额外性、储运、工业纯度及连续供氢要求有据','低电价不保证低到厂氢价；加氢站价格不能代替工业到厂价；制氢不能无成本吸收无限弃电',
      '单位终端氢成本/排放、供氢缺口及电力侧机会成本',['renewable_hydrogen_north_capacity_share','renewable_hydrogen_northwest_capacity_share','hydrogen_methanol_use_share','hydrogen_ammonia_use_share','hydrogen_consumption_price_december'])
    S('SYN08','石油;低碳电力;生物燃料;氢能','2023含油品净进口/消费78.85%；2024原油进口单位价值和加氢站燃料价格为有限经济证据','可电气化交通采用电力，难替代运输评估生物液体燃料或氢衍生燃料',
      '按客公里/吨公里等同服务比较，计设备更新、基础设施及燃料工艺','不以电价与油价直接排名；生物天然气数据不代表可持续航煤产量',
      '同交通服务下进口暴露、全生命周期排放与总成本',[('oil_net_import_ratio',2023),'crude_oil_import_unit_value','hydrogen_consumption_price_december'])
    return assessment,synergies

def report_sections(data,inds,assessment,synergies):
    text=['','## 11. 补齐后的分能源评价','','本节按九类能源逐一对照保障、低碳、经济、协调。比较对象、时期和适用范围不同，不构造跨服务混合排名。每个判断的具体原值引用见[energy_assessment.csv](energy_assessment.csv)。']
    for energy in ENERGIES:
        text+=['',f'### {energy}','']
        for row in [r for r in assessment if r['energy']==energy]:
            text.append(f"- **{row['dimension']}：**{row['evidence']}。{row['diagnosis']}。边界：{row['boundary']}。")
    text+=['','## 12. 多能源协同潜力与适用条件','','以下是现状证据支持的待检验方向，不是已经测得的协同收益；问题一不以尚未实施的仿真给这些方向排序。完整证据引用见[synergy_assessment.csv](synergy_assessment.csv)。']
    for r in synergies:
        text+=['',f"### {r['synergy_id']}：{r['energies'].replace(';','—')}",'',
               f"依据：{r['evidence']}。机制：{r['mechanism']}。",'',
               f"适用条件：{r['applicable_conditions']}。主要限制：{r['tradeoff_or_failure']}。",'',
               f"后续检验：{r['next_model_test']}。"]
    text+=['','## 13. 数据补充与仍需保留的空缺','',
           '![国际能源年均基准价格](price_trends.svg)','',
           '图4：三条基准各用原单位独立坐标。混合年度单独标点、不参与连线；澳煤现货与期货断开，欧洲气价2015混合点与TTF断开，2024异常值不绘入。不可跨价格定义断点解释涨幅或因果。','',
           '分省光伏装机及8省核电并网容量见[technology_region_capacities.csv](technology_region_capacities.csv)；可再生消纳责任权重、风光电网分区利用率及流域水能利用率见[renewable_regions.csv](renewable_regions.csv)。全国已评估的29个地区中，总量责任权重未达标3个、非水电1个；西藏免考核和新疆只监测，不计为不达标。', '',
           '价格观测与有效收益率覆盖分开报告：澳煤2022、欧洲气价2015为混合年度；澳煤期货2023—2024只有1个变化，不计算SD。欧洲2024异常年度值排除；另有NEA TTF截面，不拼入WB。原件定义页、切换时间、有效相邻对及统计不足均显式保存。', '',
           '生物质非电利用已补生物天然气行业估计；完整省级原料与液体燃料表、可核实的供热统计仍不齐。协会完整年度报告需订阅；公开采访的供热单位疑似错误，已排除。未将未取得的数据填零或解释为不存在。', '',
           '水电和生物质新增成本属于多年样本；氢气价格为12月指数；煤、油、气新增进口单位价值为2024同表金额/数量，随品类与来源结构变化。它们补足现状经济性分析，但不能拼成无条件的九能源成本排行榜。', '',
           '原油2024国别、核燃料/生物质原料价格和贸易细项仍需更细资料；水风光电量经电网混合后没有天然的分品种海关贸易或终端归属，不能硬填为零。完整历史地区面板与运行时序影响后续区域校准和仿真精度，不将已完成描述评价扩张为全国模型校准。', '',
           '新增来源、实际提取位置、版本选择和排除项见[补充用途审查](../../../docs/solutions/p1-lb-additional-review.md)。']
    return text
