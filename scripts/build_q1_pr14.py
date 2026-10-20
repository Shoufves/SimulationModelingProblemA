"""Current Q1 interpretation and a reproducible handoff to the PR14 factory.

The frozen descriptive indicators are retained; no model result is substituted
for an observation and the original Q1 output is never overwritten.
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import shutil

from run_q3_pr14 import ROOT, preflight, load, save, sha, decode, build_snapshot, hashes


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def csv_write(path, records):
    fields=list(dict.fromkeys(k for row in records for k in row))
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader();writer.writerows(records)


def build(out):
    preflight()
    old=ROOT/'outputs/q1/p1_yx'
    manifest=load(old/'run_manifest.json')
    for name,digest in manifest['outputs'].items():
        if sha(old/name)!=digest:
            raise ValueError('Changed frozen Q1 output '+name)
    record=decode(load(ROOT/'data/processed/q2_delivery/parsed_inputs.json')['net58/25'])
    model,assumptions,sources=build_snapshot(record,25,{})
    # Copy only verified historical products. Their numerical indicator values
    # are retained exactly; the current report and classification are explicit.
    for name in manifest['outputs']:
        shutil.copyfile(old/name,out/name)
    history=rows(old/'history.csv');changes=[]
    for row in history:
        if row['dataset']=='research' and row['variable']=='oil_electricity':
            changes.append(dict(record_id=row['record_id'],year=row['year'],value=row['value'],unit=row['unit'],
                original_variable=row['variable'],current_variable='oil_other_composite_electricity',
                basis='PR14 EI Oil/Other split; original OWID combined series is not pure oil',
                source_locator=row['source_locator']))
            row['variable']='oil_other_composite_electricity'
            row['boundary']+='; Original oil_electricity label is a composite Oil+Other research series, not pure oil; see classification_changes.csv'
    if not changes:
        raise ValueError('Expected composite series missing')
    csv_write(out/'history.csv',history)
    csv_write(out/'classification_changes.csv',changes)
    coverage=rows(old/'coverage.csv')
    for row in coverage:
        if row.get('variable')=='oil_electricity':
            row['variable']='oil_other_composite_electricity'
    csv_write(out/'coverage.csv',coverage)
    handoff=rows(old/'model_handoff.csv')
    for row in handoff:
        row['current_model_bridge']='q2_observation_bridge.csv; q2_initial_state.csv; handoff.json'
        row['current_use_boundary']='Original descriptive admission retained; current simulation uses independently reviewed PR14 factory inputs, not this candidate table directly'
    csv_write(out/'model_handoff.csv',handoff)
    bridge=[dict(year=year,metric=metric,value=value,
                 role='PR14 factory observation/bridge input; not an independent new source',
                 locator=f'net58/25 -> build_snapshot -> model.data[{year}, {metric}]')
            for (year,metric),value in sorted(model.data.items()) if 2015<=year<=2024]
    csv_write(out/'q2_observation_bridge.csv',bridge)
    initial=[]
    for tech,capacity in model.initial_capacities.items():
        initial.append(dict(technology=tech,capacity_mw=capacity,generation_mwh=model.initial_generation[tech],
            capacity_role='rounded subtype anchor or reconstruction' if tech in ('coal','gas','oil','biomass') else 'observed broad stock; hydro deducts pumped stock',
            generation_role='PR14 corrected technology statistics; not extra independent observation'))
    for name,p in model.operating_boundary.stores.items():
        initial.append(dict(technology=name,capacity_mw=p['operation']['power_mw'],generation_mwh=model.operating_boundary.initial_pumped_generation_mwh,
            capacity_role='separate observed pumped stock',generation_role='observed pumping output with conditional Other bridge'))
    csv_write(out/'q2_initial_state.csv',initial)
    save(out/'handoff.json',dict(upstream_commit='1b8f465783afe7505c8d4e65ec43ada18c311daf',
        parameters=record['parameters'],training=record['config']['training_years'],evaluation=record['config']['evaluation_years'],
        evaluation_identity='already_seen',historical_training_rerun=False,
        raw_originals_reverified=False,upstream_source_locations=sources,
        assumption_subset={k:v for k,v in assumptions.items() if not isinstance(v,(dict,list))},
        immutable_indicators_sha256=sha(old/'indicators.csv'),classification_changes=len(changes)))
    text=(old/'report.md').read_text('utf-8')
    old_intro=text.split('\n\n')[1]
    text=text.replace(old_intro,'当前版在原Q1已验收描述性结果上增加PR14分类修正及接口。原稿与指标留存于 `outputs/q1/p1_yx`，本版不扩充来源准入、不重新拟合历史。')
    text=text.replace('|油电|','|油电与Other合列（旧研究汇编）|')
    oil=model.data[2024,'oil_electricity_mwh']/1e6
    other=model.data[2024,'unallocated_electricity_mwh']/1e6
    note=(f'\n\n## 与问题二、三的共同口径\n\n'
          f'旧表88.88 TWh为研究汇编合列项，不能称为纯油电。PR14修正后的2024纯油电为{ oil:.6f} TWh，'
          f'Other为{other:.6f} TWh；两者与旧汇编只在原展示精度内接近，不强行作精确恒等。'
          '本版history.csv仅更正合列项名称和边界，record_id、数值、单位及来源保持不变；212条原指标逐字保留。\n\n'
          f'2024水电总装机435520 MW中，抽蓄58690 MW单列，常规水电376830 MW进入发电队列；'
          f'抽蓄发电65.7 TWh、抽水82.125 TWh分别入账。Other扣除抽蓄后的{(other-65.7):.6f} TWh为统计桥接项，'
          '不能虚构成可调度油电或新机组。煤/气分项装机为舍入锚点，油电装机沿用2014值，年龄、债务、现金及在建队列为显式重建。\n\n'
          '主线依次为：Q1识别规模增长、结构转型、共享气源、空间差异和融资约束；'
          'Q2用统一后的统计边界、训练参数与2024初态形成2025—2060条件路径；'
          'Q3从同一路径取得2030/2035快照，以相同库存、资金、项目工期和服务需求检验冲击及政策。\n\n'
          '2015—2021为训练，2022—2024为已接触评估。Q1现状观察和Q2重建初态不能混称同一类观测。'
          '历史容量及光伏装机误差未过门槛的披露保留；S0长期已有服务缺口，不能将因此下降的能耗全部归功于效率。\n\n'
          '碳排放区分燃烧（含垃圾化石部分）、工业过程、正排放、移除与净排放；不等同全温室气体中和。'
          'Q1的2018美元LCOE案例及不同年份价格保留原口径，不直接送入Q2/Q3；后两问使用PR14的2024不变价。'
          '年度累计未折现资源费、折现资源费、12天事件费分别列示，公共转移支付不重复计费。\n\n'
          'Q3按每一种服务检验缺供，其中煤/油/气非能源原料分开；Q2汇总展示缺供率与Q3最差服务缺供率使用不同汇总方式，'
          '须连同名称和分母报告，不能互换。5%年度、15%事件政策筛选阈值仍沿用原方案。\n\n'
          '接口文件：`q2_observation_bridge.csv`来自实际PR14工厂模型，`q2_initial_state.csv`列示技术初态，'
          '`handoff.json`保存参数、桥接假设与上游来源位置，`classification_changes.csv`列示逐记录更名。\n')
    text=text.replace('## 1. 主要判断',note+'\n## 1. 主要判断',1)
    (out/'report.md').write_text(text,'utf-8')
    return dict(historical_rows=len(history),unchanged_indicator_rows=len(rows(old/'indicators.csv')),
                classification_changes=len(changes),observation_bridge_rows=len(bridge))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='outputs/q1/pr14_aligned')
    args=parser.parse_args(argv);folder=(ROOT/args.output_dir).resolve()
    if folder.parent!=ROOT/'outputs/q1' or folder.name in ('p1_yx','p1_lb','yx_reproduction'):
        parser.error('Use a new direct child of outputs/q1')
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if folder.exists() and any(folder.iterdir()):
        marker=folder/'alignment_manifest.json'
        if not marker.is_file() or load(marker).get('owner')!='q1_pr14_alignment':
            parser.error('Refusing to replace unowned output; choose a new directory')
        archive=ROOT/'outputs/q1_pr14_archive'/folder.name/run_id
        archive.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(folder),str(archive))
    folder.mkdir(parents=True,exist_ok=True)
    receipt=dict(status='running',team_approved=False,owner='q1_pr14_alignment',run_id=run_id)
    try:
        receipt['coverage']=build(folder)
        receipt.update(status='passed',input_hashes={**hashes(),**{p:sha(ROOT/p) for p in (
            'outputs/q1/p1_yx/run_manifest.json','data/processed/q2_delivery/parsed_inputs.json',
            'workflow/q3_pr14_inputs.json','scripts/build_q1_pr14.py')}})
    except Exception as exc:
        receipt.update(status='failed',error=str(exc));raise
    finally:
        receipt['outputs']={p.name:sha(p) for p in sorted(folder.iterdir()) if p.name!='alignment_manifest.json'}
        save(folder/'alignment_manifest.json',receipt)
    print(receipt['coverage'])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
