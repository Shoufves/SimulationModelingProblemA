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
    if (CAT/'q1_sources.json').is_file():
        specs.append(('q1','data/catalog/q1_sources.json','data/catalog/q1_sources.json'))
    specs.extend(('lb/'+('base' if Path(r['path'][len(LIB):]).parent.as_posix()=='.' else Path(r['path'][len(LIB):]).parent.as_posix()),r['path'],r['target']) for r in manifests)
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
            if namespace=='q1':
                candidate=(ROOT/oldfile).resolve()
                if not candidate.is_relative_to(ROOT/'data/raw/q1'):raise ValueError('Q1 original outside dedicated source directory')
                canonical=candidate.relative_to(ROOT).as_posix()
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
    paths += sorted((ROOT/'data/processed/q2').glob('*.json')) if (ROOT/'data/processed/q2').is_dir() else []
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
        if rel.startswith('data/processed/q2/'):
            status='q2_author_reviewed_conditional_research'
            use='Q2全国聚合条件模型；逐用途审查data/catalog/q2_national_input_review.json；不替代原契约或团队批准'
            boundary='原图复核的NBS值、原始API/CSV匹配、BTR CO2分项和IEA技术参照；重建及外推另列假设；PEO代理/CO2/已接触验证边界必须保留。'
        if rel == 'data/processed/q1/cost_method_parameters.csv':
            use='mmj baf1975原参数；Q1风电统一融资条件成本；见docs/solutions/p1-yx-integration.md'
            boundary='2024 USD、25年、3/5/7%实际WACC研究假设；国家新项目均值未配对；CF通常事前估计，O&M为报告假设；非保供系统成本或全国在运成本。'
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
