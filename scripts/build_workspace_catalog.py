"""Offline unified catalog and conservative, field-level NBS deduplication.

Original observations, reviews and source registries are never rewritten.
This view does not admit additional observations to a formal model.
"""
from pathlib import Path
from decimal import Decimal
from collections import defaultdict, Counter
import csv, hashlib, json, re

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT/'data/catalog'
LIB = 'A题_lb/A题完整资料包/A题资料库/'

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def save_json(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def save_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def csv_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def scoped_original(namespace, row, registered, root=ROOT):
    """Allow scoped reuse only of an already cataloged identical public original."""
    original=str(row.get('file',row.get('path',''))).replace('\\','/')
    candidate=(root/original).resolve()
    dedicated=(root/'data/raw'/namespace).resolve()
    if candidate.is_relative_to(dedicated):
        return candidate.relative_to(root).as_posix()
    matches=[r for r in registered if r['source_key']==row.get('reuse_source_key')]
    if (not candidate.is_relative_to((root/'data/raw').resolve()) or len(matches)!=1 or
            not matches[0]['file_available'] or not matches[0]['canonical_path'] or
            candidate!=(root/matches[0]['canonical_path']).resolve() or
            row.get('sha256')!=matches[0]['sha256'] or sha(candidate)!=matches[0]['sha256']):
        raise ValueError(namespace.upper()+' original outside dedicated source directory without verified reuse')
    return candidate.relative_to(root).as_posix()


def references(aliases):
    refs={}
    text=(ROOT/'只读工作区/final.md').read_text(encoding='utf-8')
    for key, old in re.findall(r'^\[([^\]]+)\]:\s*<([^>]+)>',text,re.M):
        tail=old.replace('D:/CSF2026/sanzu/','')
        if tail.startswith('A题_yx/'): tail=tail[len('A题_yx/'):]
        elif tail.startswith('A题mmj/'): tail='A题_mmj/'+tail[len('A题mmj/'):]
        elif tail.startswith('A题lb/'): tail='A题_lb/'+tail[len('A题lb/'):]
        special={'RY':'docs/history/comparison/final_yx.md','RM':'docs/history/comparison/final_mmj.md',
                 'RL':'docs/history/comparison/final_lb.pdf'}
        new=special.get(key,aliases.get(tail,tail))
        refs[key]=dict(original=old,path=new,exists=(ROOT/new).is_file())
    save_json(CAT/'final_references.json',refs)
    return refs

def sources(aliases):
    registry=[]
    original=load(ROOT/'archive/organization_20261017/file_disposition.json')
    representations={r['target']:r['representation'] for r in original if r.get('representation')}
    manifests=[r for r in original if r['target'] and r['path'].startswith(LIB)
               and Path(r['path']).name.startswith('sources') and r['path'].endswith('.json')]
    specs=[('yx','data/catalog/sources.json','data/catalog/sources.json'),
           ('mmj','A题_mmj/data/sources.json','data/sources.json')]
    # Legacy public originals must exist in the registry before Q1/Q2 can
    # verify scoped reuse. This includes lb originals, not just yx/mmj.
    specs.extend(('lb/'+('base' if Path(r['path'][len(LIB):]).parent.as_posix()=='.' else Path(r['path'][len(LIB):]).parent.as_posix()),r['path'],r['target']) for r in manifests)
    for namespace in ('q1','q2'):
        manifest=f'data/catalog/{namespace}_sources.json'
        if (ROOT/manifest).is_file():
            specs.append((namespace,manifest,manifest))
    evidence=defaultdict(list)
    for review in load(ROOT/'data/evidence_reviews.json')['reviews']:
        for item in review.get('evidence_files',[]):
            if item not in evidence[item.get('source_id','')]:evidence[item.get('source_id','')].append(item)
    for namespace,old_manifest,manifest in specs:
        obj=load(ROOT/manifest)
        entries=obj if isinstance(obj,list) else obj.get('sources',[])
        for row in entries:
            if not isinstance(row,dict): continue
            sid=row.get('id',row.get('source_id',''))
            oldfile=str(row.get('file',row.get('path',''))).replace('\\','/')
            attempts=[]
            if oldfile:
                if namespace=='yx': attempts=['data/'+oldfile,oldfile]
                elif namespace=='mmj': attempts=['A题_mmj/'+oldfile,oldfile]
                else:
                    attempts=[(Path(old_manifest).parent/oldfile).as_posix(),LIB+oldfile]
            canonical=next((aliases[x] for x in attempts if x in aliases),'')
            if namespace in {'q1','q2'}:
                canonical=scoped_original(namespace,row,registry)
            exists=bool(canonical and (ROOT/canonical).is_file())
            filehash=sha(ROOT/canonical) if exists else ''
            registry.append(dict(source_key=namespace+':'+sid,namespace=namespace,original_source_id=sid,
                title=row.get('title',''),publisher=row.get('agency',row.get('publisher','')),
                url=row.get('url',''),canonical_path=canonical,sha256=filehash,
                content_group=('sha256:'+filehash) if filehash else '',
                original_path=oldfile,registry_path=manifest,status=row.get('status','registered'),
                file_available=exists,notes=row.get('notes',row.get('note','')),
                original_record=row,evidence_files=evidence[sid] if namespace=='mmj' else [],
                evidence_available=bool(evidence[sid]) if namespace=='mmj' else exists))
            if canonical in representations:
                registry[-1]['representation']=representations[canonical]
    # Verification dependency order need not reorder the published catalog.
    # Keep the established namespace order so review diffs show new records.
    namespace_order = {'yx': 0, 'mmj': 1, 'q1': 2, 'q2': 3}
    registry.sort(key=lambda row: namespace_order.get(row['namespace'], 4))
    save_json(CAT/'sources_unified.json',registry)
    save_csv(CAT/'sources_unified.csv',registry,['source_key','namespace','original_source_id','title','publisher',
        'url','canonical_path','sha256','content_group','registry_path','status','file_available','notes'])
    return registry

def datasets(refs):
    reverse=defaultdict(list)
    for key,r in refs.items(): reverse[r['path']].append(key)
    yx={r['dataset']:r for r in csv_rows(CAT/'dataset_inventory.csv')}
    admitted={r['dataset_path']:r for r in load(ROOT/'workflow/model_inputs.json')['inputs']}
    rows=[]
    paths=sorted((ROOT/'data/processed').rglob('*.csv'))+sorted((ROOT/'data/observations').glob('*.json'))
    paths += [ROOT/'data/processed/attachment_assets.json']
    for p in paths:
        rel=p.relative_to(ROOT).as_posix()
        if '/unified/' in rel: continue
        info=yx.get(p.name,{}) if p.parent==ROOT/'data/processed' else {}
        status=info.get('eligibility','candidate_or_scoped_see_source_notes')
        boundary=info.get('limitations','保留原表年/单位/统计边界；目录归档不是正式模型准入。')
        use=info.get('use','补充核对；按final B3及来源说明限定用途')
        if rel in admitted:
            status='reviewed_scoped_existing_contract';use=admitted[rel]['purpose']
        elif '/observations/' in rel:
            obj=load(p);status=obj.get('status','candidate')
            use=obj.get('scope',use)
        if any(x in rel for x in ('worldbank_energy','worldbank_annual_monthly','transmission_lines_candidate')):
            status='quarantined';boundary+=' 价格版本或线路类型尚未核清，不进入正式初始化。'
        if 'household_energy_by_author_group_unweighted' in rel:
            status='diagnostic_only';boundary+=' 主用已发表群体汇总；旧未加权汇总仅供差异诊断。'
        if any(x in rel for x in ('household','employment','ai_trade/compute')):
            use='扩展模块，按final E4数据门槛启用；'+use
        if rel.startswith('data/processed/q1/'):
            status='q1_descriptive_transcription_reviewed'
            use='Q1描述/可比案例；审查见docs/solutions/p1-lb-input-review.md及p1-lb-additional-review.md；非ABM准入'
            boundary='共同base原件转录及另行核验的公开补充；未获三人共同输入更新批准。逐行区分年份、来源及用途：旧成本投影、多年样本、2024实测和12月价格不混用；发用差非潮流。'
        if rel == 'data/processed/q1/cost_method_parameters.csv':
            use='mmj baf1975原参数；Q1风电统一融资条件成本；见docs/solutions/p1-yx-integration.md'
            boundary='2024 USD、25年、3/5/7%实际WACC研究假设；国家新项目均值未配对；CF通常事前估计，O&M为报告假设；非保供系统成本或全国在运成本。'
        if rel.startswith('data/processed/q2/'):
            status='q2_scoped_historical_review_not_complete_model_admission'
            use='Q2历史总量/装机/CO2候选目标、GDP外生驱动或稀疏清单边界核对；见data/catalog/q2_history_review.json'
            boundary='同源不增样本数；GDP非行为拟合目标；一次电力及其他不改名非化石；BTR与GCB清单分存；稀疏碳汇不外推未来；不批准完整主体初态或全国预测。'
        if rel == 'data/processed/q2/technology_reference.csv':
            status='q2_reviewed_technology_reference_not_complete_model_admission'
            use='Q2寿命/工期及中国样本技术经济参照；实质审查见data/catalog/q2_technology_review.json'
            boundary='2020报告、2018美元、2025投运样本；非2024实测全国机组。寿命非许可，年CF非小时序列，O&M未拆分，燃料热值口径待匹配；不用于2021前主体信息。'
        if rel == 'data/processed/q2/sector_balance_2014_30province.csv':
            status='q2_scoped_historical_sector_balance_candidate'
            use='2014年30省部门/燃料账候选；见data/catalog/q2_sector_state_review.json'
            boundary='不含西藏，未与新版全国统计桥接；保留质量/体积/热量原单位与正负号；居民汽油不直接归建筑服务，非能源用途不直接算燃烧。'
        if rel.startswith('data/processed/q2/nbs2014_'):
            status='q2_reviewed_national_2014_accounts_and_boundary_diagnostics'
            use='2016版统计年鉴的2014全国平衡及七大部门原值；23项算术核对；见data/catalog/q2_nbs2014_review.json'
            boundary='同年不同版本不拼接；综合能源按原表等价热值，不是简单物理热当量；工业含转换，留白非零，30省汇总高于全国的差异不分摊；尚非完整主体初态。'
        if Path(rel).name in {'fuel_reference.csv','power_2014_reference.csv','initialization_2014_capacity.csv','initialization_2014_fuel_normalization.csv'} and rel.startswith('data/processed/q2/'):
            status='q2_scoped_initialization_references'
            use='2014年NEA装机分组、2013燃料默认热值/碳因子和具名燃料热量归一；见q2_initialization_reference_review.json'
            boundary='NEA2015发布版本不缩放到NBS修订总量；残差未分配；建设支出非现金存量；总用量含转换/原料，热量不可加作一次能源，未计算实际燃烧排放。'
        if Path(rel).name.startswith('technology_2010_') and rel.startswith('data/processed/q2/'):
            status='q2_scoped_historical_technology_reference'
            use='IEA/NEA2010中国样本及统一假设；见q2_technology_2010_review.json；供历史决策参数候选与原件冲突检查'
            boundary='2008美元、2015投运预测样本，非2014全国实测；正文净容量与附录项目规模分存；煤价热值矛盾保留；O&M未拆分，寿命非许可。'
        if rel=='data/processed/q2/policy_reference.csv':
            status='q2_scoped_historical_policy_terms'
            use='2009陆上风电、2013光伏政策条款与分区费率；见q2_policy_review.json'
            boundary='名义价格、税基、核准/投运资格及排除项分存；全额标杆价非额外补贴，分布式全电量补贴非总电价；不平均成全国价格，不继承未知年限或倒灌历史。'
        if rel.startswith('data/processed/q2/policy_timeline_'):
            status='q2_scoped_policy_vintage_reference'
            use='3008/3044/2729号文件六组历史电价表、23项价格及公布/明确替代事件；见q2_policy_timeline_review.json'
            boundary='保留已宣布后撤销的2018风电计划价及各版地区；公布日不是核准/开工/投运日，未来价格不倒灌历史。标杆上限非实际付款，名义含税价格不直接接入常价美元模型；未建立全国分区/项目权重或财政时序。'
        if rel.startswith('data/processed/q2/currency_bridge_'):
            status='q2_scoped_retrospective_currency_reference'
            use='WDI中国2008—2024年均人民币/美元汇率与美国GDP平减指数的常价2008美元换算因子；见q2_currency_bridge_review.json'
            boundary='复用既有宏观原件；2026-10-08修订版事后会计换算。美国一般平减为明确研究假设，非中国技术物价；年均汇率非项目交易价，税基不变，不把未来实际值用于历史投资预期，不提供2060路径或全国合同准入。'
        if Path(rel).name.startswith('national_balance_2014_') and rel.startswith('data/processed/q2/'):
            status='q2_scoped_national2014_balance_with_unresolved_differences'
            use='CEADs全国2014原表及冻结差异诊断；煤电原煤/煤炭比较已由q2_coal_bridge_review.json补充解释；气体差异仍未解释'
            boundary='旧差异文件保留当时结果；不得自动升级为NBS同版全国初态或CO2燃烧量；保留非能源用途与附列项'
        if Path(rel).name.startswith('coal_bridge_2014') and rel.startswith('data/processed/q2/'):
            status='q2_scoped_coal_aggregate_bridge'
            use='CEADs B/C/D煤种和部分E合并类别到NBS2016煤炭聚合的15项舍入范围核对；见q2_coal_bridge_review.json'
            boundary='修正原煤与煤炭直接比较的类别错误；不唯一拆分型煤/煤矸石，不解决天然气差异或全国初态准入。'
        if Path(rel).name.startswith('apec_balance_2014') and rel.startswith('data/processed/q2/'):
            status='q2_scoped_retrospective_energy_accounting_reference'
            use='APEC中国005的2014详细能源平衡；ktoe/PJ与HTML/TSV同源核对、终端/非能源用途和条件区间；见q2_apec_balance_review.json'
            boundary='5539个破折号未填零；两个产出附列使用独立单位；总量/子项不双计。版本日期未知，净热值与NBS等价值不直接拼接，能源消耗不是有效服务/设备初态；区间以非负和整数四舍五入为显式假设。'
        if rel=='data/processed/q2/nuclear_queue_2014_reference.csv':
            status='q2_scoped_historical_nuclear_queue_reference'
            use='NEA第33问26台2014年末在建机组28450MW与NNSA同期状态逐机组匹配；见q2_nuclear_queue_review.json'
            boundary='源容量和开工月可追溯；剩余工期、余额和实际未来投运日期留空；在运机组排除；NEA/NBS存量20MW版本差异未调平；模型工期与托管现金仍是明确研究假设。'
        if Path(rel).name.startswith('nuclear_capacity_2015_') and rel.startswith('data/processed/q2/'):
            status='q2_scoped_nuclear_2015_capacity_start_reference'
            use='2015年8台获建造许可机组与CNS7额定MW(e)/开工状态核对；田湾原许可与控制点分存；见q2_nuclear_capacity_2015_review.json'
            boundary='8980MWe为逐机组加总；6台有开工日、2台已核准而日期缺失；CN编号冲突保留，按电厂/机组对应。2016年6月回顾报告不倒灌2015信息；不等于运行许可或完整模型日历。'
        if rel.startswith('data/processed/q2/nuclear_state_2024_'):
            status='q2_scoped_2024_nuclear_state_reference'
            use='2024年底58行在运/27行在建额定容量与日期原表；见q2_nuclear_state_2024_review.json'
            boundary='2025-01-07转载汇编；防城港重复编号、石岛湾技术同号、缺日期、漳州跨年商运和NBS容量差异保留。不是已准入全国设备表；不推断未来投运、退出、许可或资金。'
        if rel.startswith('data/processed/q2/transport_activity_'):
            status='q2_scoped_transport_activity_reference'
            use='NBS2025表16-6/16-8的2014—2024年132格周转量与统计范围、指标定义；见q2_transport_activity_review.json'
            boundary='人公里/吨公里分开，海洋不与水路重复加总；公路为营业性范围，民航含国际航线。2019公路货运与2020海洋子项跳变未桥接，禁止自动驱动跨断点模型；不提供能耗强度、私人出行或未来预测。'
        if rel.startswith('data/processed/q2/current_state_2024'):
            status='q2_partial_current_state_not_admitted'
            use='2024年末装机、储能功率/能量、年度用电及燃气用途的45项源定位与v12终点对照；见q2_current_state_review.json'
            boundary='年鉴/公报版本分开；可靠性样本不外推全国煤气容量；抽蓄不重复加总，发电量不除年末装机冒充容量因子。SOC、设备年龄、同版技术拆分、服务、燃料库存、队列与资金仍缺，不构成全国S0初态。'
        if rel=='data/processed/q2/end_use_reference.csv':
            status='q2_scoped_prospective_end_use_performance_reference'
            use='IRENA REmap中国2014报告附录A七项终端技术的性能及单位换算；见q2_end_use_review.json'
            boundary='2030情景技术假设，不是2014全国设备实测。热泵限空间/低温热；MJ/人公里先求逆再换算。成本价年、kW分母及实际存量未准入，成本未用于历史投资。'
        rows.append(dict(path=rel,final_refs=';'.join(reverse[rel]),status=status,use=use,boundary=boundary,sha256=sha(p)))
    save_csv(CAT/'datasets_unified.csv',rows,['path','final_refs','status','use','boundary','sha256'])
    return rows

def nbs_view():
    candidates=[]
    def add(path,year,var,value,unit,family,namespace,source_id,locator,status,rank):
        if value is None or str(value).strip() in ('','nan','None'): return
        candidates.append(dict(year=int(year),region='China_mainland',variable=var,value=str(value),unit=unit,
            edition='NBS_2025',family=family,source_key=namespace+':'+source_id,dataset_path=path,
            source_locator=locator,source_status=status,rank=rank))
    for filename,family in [('nbs_energy_annual.csv','energy'),('nbs_capacity_annual.csv','capacity')]:
        rel='data/processed/'+filename
        for i,r in enumerate(csv_rows(ROOT/rel),2):
            add(rel,r['year'],r['variable'],r['value'],r['unit'],family,'yx',r['source_id'],
                f'CSV row {i}; '+r['source_locator'],'usable_with_scope',2)
    for kind in ('consumption','production','capacity'):
        rel=f'data/processed/lb/base/nbs/{kind}_2005_2024.csv'
        for i,r in enumerate(csv_rows(ROOT/rel),2):
            for col,val in r.items():
                if col in ('year','source_id'): continue
                if kind=='capacity': var=col;unit='10^4 kW';family='capacity'
                else:
                    var=col if col==kind+'_10ktce' else kind+'_'+col.replace('_share_pct','_pct').replace('primary_electricity_and_other','primary_electricity_other')
                    unit='10^4 tce' if col==kind+'_10ktce' else '%';family='energy'
                add(rel,r['year'],var,val,unit,family,'lb/base',r['source_id'],f'CSV row {i}; column {col}','transcribed_scoped',3)
    mappings={
      'energy_consumption_2015_2024.json':{'total_energy_consumption':('consumption_10ktce','10^4 tce'),
          'coal_share':('consumption_coal_pct','%'),'petroleum_share':('consumption_oil_pct','%'),
          'natural_gas_share':('consumption_gas_pct','%'),'primary_electricity_and_other_energy_share':('consumption_primary_electricity_other_pct','%')},
      'power_capacity_2015_2024.json':{k:(k+'_10kW','10^4 kW') for k in ('total','thermal','hydro','nuclear','wind','solar','other')},
      'demand_energy_total_2015_2024.json':{'total_energy_consumption':('consumption_10ktce','10^4 tce')},
      'demand_real_gdp_growth_2015_2024.json':{'real_gdp_growth_pct':('real_gdp_growth_pct','%')},
      'macro_growth_2015_2024.json':{'real_gdp_growth_pct':('real_gdp_growth_pct','%')},
    }
    for name,mapping in mappings.items():
        rel='data/observations/'+name;obj=load(ROOT/rel)
        for i,vals in enumerate(obj['rows']):
            r=dict(zip(obj['columns'],vals))
            for col,(var,unit) in mapping.items():
                family='capacity' if 'capacity' in name else 'gdp_growth' if 'growth' in name else 'energy'
                add(rel,r['year'],var,r[col],unit,family,'mmj',obj['source_id'],f'rows[{i}].{col}; '+obj['locator'],obj['status'],0 if name.startswith('demand_') else 4)
    # Table 3-4 and table 9-8 are different tables. Their growth rates remain
    # separate families; overlapping values are cross-checks, not identical provenance.
    rel='data/processed/lb/base/nbs/real_gdp_growth_2005_2024.csv'
    for i,r in enumerate(csv_rows(ROOT/rel),2):
        add(rel,r['year'],'real_gdp_growth_pct',r['real_GDP_growth_pct'],'%','gdp_growth_table_3_4','lb/base',
            r['source_id'],f'CSV row {i}; real_GDP_growth_pct','transcribed_scoped',3)
    groups=defaultdict(list)
    for c in candidates:
        key=(c['edition'],c['family'],c['year'],c['region'],c['variable'],c['unit'])
        groups[key].append(c)
    selected=[];provenance=[];conflicts=[]
    for key,items in sorted(groups.items()):
        values={Decimal(x['value']) for x in items}
        row_id=hashlib.sha256('|'.join(map(str,key)).encode()).hexdigest()[:20]
        chosen=min(items,key=lambda r:(r['rank'],r['dataset_path']))
        for item in items: provenance.append(dict(record_id=row_id,**item,selected=item is chosen and len(values)==1))
        if len(values)>1:
            conflicts.extend(dict(record_id=row_id,**x) for x in items)
            continue  # Never silently average, overwrite or admit a disagreement.
        selected.append(dict(record_id=row_id,**chosen,original_value=chosen['value'],
            transformation='identity; field-name mapping only; units unchanged',
            evidence_count=len(items),independent_observation_count=1,
            ready_for='conditional_demand_hindcast_only' if chosen['rank']==0 else 'Q1_scoped_reference_pending_formal_admission',
            blocked_for='national_ABM_initialization_and_calibration_without_input_review',
            uncertainty='not supplied; same-source agreement is not independent validation',
            missing_reason=''))
    out=ROOT/'data/processed/unified'
    fields=['record_id','year','region','variable','value','unit','edition','family','source_key','dataset_path',
        'source_locator','source_status','original_value','transformation','evidence_count','independent_observation_count',
        'ready_for','blocked_for','uncertainty','missing_reason']
    save_csv(out/'nbs_history.csv',selected,fields)
    save_csv(CAT/'nbs_record_provenance.csv',provenance,['record_id','year','family','variable','value','unit','source_key','dataset_path','source_locator','source_status','selected'])
    save_csv(CAT/'nbs_record_conflicts.csv',conflicts,['record_id','year','family','variable','value','unit','source_key','dataset_path','source_locator'])
    summary=dict(candidate_cells=len(candidates),unique_records=len(selected),repeated_cells_removed=len(candidates)-len(groups),
        conflicting_keys=len({x['record_id'] for x in conflicts}),years=[2005,2024],
        key=['edition','family','year','region','variable','unit'],
        policy='No zero filling, no averaging, no scope promotion. GDP table 3-4 versus 9-8 retained separately.',
        outputs={'history':sha(out/'nbs_history.csv'),'provenance':sha(CAT/'nbs_record_provenance.csv')})
    save_json(CAT/'nbs_dedup_summary.json',summary)
    return summary

def main():
    aliases=load(CAT/'path_aliases.json')
    refs=references(aliases);src=sources(aliases);ds=datasets(refs);nbs=nbs_view()
    result=dict(final_references=len(refs),missing_references=[k for k,v in refs.items() if not v['exists']],
                source_records=len(src),source_records_with_files=sum(r['file_available'] for r in src),
                dataset_files=len(ds),nbs=nbs)
    save_json(CAT/'workspace_catalog_summary.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['missing_references']: raise SystemExit(1)

if __name__=='__main__':main()
