"""Offline Q2 execution; engineering fixtures never satisfy national acceptance."""
import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.quality import historical_quality
from energy_model.q2.targets import national_report
from energy_model.q2.experiments import calibration, metric_rows, parameterize, sensitivity
from energy_model.q2.io import AdmissionError, csvout, dump, load_bundle, local_path, sha


def plot_results(stage,run,fit,scope='synthetic_engineering_only'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.hashsalt']='q2-reproducible-figure'
    fig,axes=plt.subplots(1,2,figsize=(10,4),constrained_layout=True)
    years=[r['year'] for r in run['annual']]
    axes[0].plot(years,[r['primary_mwh'] for r in run['annual']],label='Primary energy (model accounting)')
    axes[0].set_ylabel('MWh');axes[0].set_xlabel('Year');axes[0].legend(fontsize=8)
    axes[1].plot(years,[r['positive_energy_co2_t'] for r in run['annual']],label='Energy CO2 after capture')
    axes[1].set_ylabel('t CO2');axes[1].set_xlabel('Year');axes[1].legend(fontsize=8)
    fig.suptitle('Synthetic engineering fixture — not a national forecast' if scope=='synthetic_engineering_only'
                 else 'S0: model source/energy-carbon accounts; national reconciliation reported separately')
    fig.savefig(stage/'baseline_path.svg',metadata={'Date':None});plt.close(fig)
    indicators=sorted({r['indicator'] for r in fit})
    fig,axes=plt.subplots(len(indicators),1,figsize=(8,2.3*len(indicators)),squeeze=False,constrained_layout=True)
    for indicator,axis in zip(indicators,axes[:,0]):
        data=sorted([r for r in fit if r['indicator']==indicator and r['status']=='compared'],key=lambda r:r['year'])
        axis.plot([r['year'] for r in data],[r['value'] for r in data],
                  label='Synthetic target' if scope=='synthetic_engineering_only' else 'Reviewed observation')
        axis.plot([r['year'] for r in data],[r['simulated'] for r in data],label='Model')
        axis.axvline(2021.5,color='gray',linestyle='--');axis.set_title(indicator);axis.legend(fontsize=8)
    fig.suptitle('Synthetic target recovery — not historical evidence' if scope=='synthetic_engineering_only'
                 else 'Historical comparison; 2022–2024 already-seen holdout')
    fig.savefig(stage/'history_fit.svg',metadata={'Date':None});plt.close(fig)


def execute(config_path,output_dir):
    config_file=local_path(ROOT,config_path)
    out=local_path(ROOT,output_dir)
    allowed=(ROOT/'outputs/q2').resolve()
    if not out.is_relative_to(allowed) or out==allowed:
        raise ValueError('Output must be a child of outputs/q2')
    if out.exists() and any(out.iterdir()):
        existing=out/'run_manifest.json'
        if not existing.is_file() or json.loads(existing.read_text(encoding='utf-8')).get('owner')!='p2/yx':
            raise ValueError('Refusing to overwrite an unowned result directory')
    run_id=uuid.uuid4().hex; started=time.perf_counter()
    latest=out.parent/(out.name+'.latest-attempt.json')
    stage=ROOT/'tmp/q2'/('run-'+run_id)
    stage.mkdir(parents=True)
    dump(latest,{'run_id':run_id,'status':'running','output_valid_for_this_attempt':False})
    try:
        config=json.loads(config_file.read_text(encoding='utf-8'))
        data=load_bundle(ROOT,config)
        experiment=data['experiment']; definitions=data['metric_definitions']
        fit=calibration(data['model_bundle']['historical'],definitions,data['observations'],experiment)
        model=parameterize(data['model_bundle']['baseline'],experiment['parameters'],fit['best_parameters'])
        baseline=EnergyModel(model).run()
        stress=sensitivity(model,definitions,experiment['sensitivity'])
        csvout(stage/'history_fit.csv',fit['history_fit'])
        csvout(stage/'history_baselines.csv',fit['baselines'])
        csvout(stage/'baseline_path.csv',baseline['annual'])
        csvout(stage/'baseline_metrics.csv',metric_rows(baseline,definitions))
        csvout(stage/'sensitivity.csv',stress)
        for name,key in [('asset_ledger','assets'),('action_ledger','actions'),('cash_ledger','cash'),
                         ('information_ledger','information')]:
            csvout(stage/(name+'.csv'),baseline[key])
        dump(stage/'project_ledger.json',baseline['projects'])
        dump(stage/'operation_ledger.json',baseline['operations'])
        dump(stage/'calibration.json',{k:v for k,v in fit.items() if k not in ('history_fit','simulation','baselines')})
        dump(stage/'historical_operation_ledger.json',fit['simulation']['operations'])
        if 'acceptance' not in data:
            raise AdmissionError('Frozen acceptance criteria missing from pinned input bundle')
        quality=historical_quality(fit,experiment['targets'],data['acceptance']['historical_quality'],experiment['windows'])
        dump(stage/'historical_quality.json',quality)
        dump(stage/'lifecycle_queue.json',baseline['lifecycle_queue'])
        scope=config['scope']
        if scope=='national_q2':
            if 'national_reporting' not in data:
                raise AdmissionError('Pinned national accounting bridge and policy comparison inputs missing')
            national=national_report(metric_rows(baseline,definitions),model,data['national_reporting'],data['acceptance']['peak'])
            csvout(stage/'national_accounting_path.csv',national['annual'])
            targets={(r['year'],r['indicator']):r for r in national['targets']}
            csvout(stage/'targets_2030_2060.csv',[
                targets.get((r['year'],r['indicator']),r) for r in national['indicators']])
            dump(stage/'peak_assessment.json',national['peak'])
            if not quality['passed']:
                raise AdmissionError('National historical quality gates failed',quality['targets'])
            gaps=[{'gate':'B4/B6/B8','status':'additional_acceptance_evidence_required',
                   'reason':'A successful model execution alone does not certify rule alternatives, convergence, final SHA reproduction or scientific completeness'},
                  {'gate':'B9','status':'external_review_pending','reason':'Independent reviewers must assess final SHA'}]
            gaps.extend({'gate':'B5','status':r['comparison_status'],'reason':r['indicator']} for r in national['targets'] if r['target_met'] is None)
        else:
            gaps=[{'gate':'B4/B5','status':'not_national_evidence','reason':'Synthetic fixture verifies execution only'},
                  {'gate':'B9','status':'external_review_pending','reason':'Independent reviewers must assess final SHA'}]
        csvout(stage/'gaps_and_conflicts.csv',gaps)
        plot_results(stage,baseline,fit['history_fit'],scope)
        (stage/'report.md').write_text(
            '# Q2 工程复现记录\n\n本次运行仅使用合成工程夹具；不构成全国历史校准、S0 预测或问题二验收通过。\n\n'
            f"实际运行 {len(fit['trials'])} 组训练参数、固定参数的已接触留出评估，以及三因素组合实验。"
            '训练指标四类齐备只验证计算接口，数值来自合成模型，不是观测中国。\n\n'
            '年度主体申请经资金、接入和许可审核后入未来队列；运行采用服务优先的分层求解。'
            '含储能互斥时为 MILP，其余为 LP。资源费、碳履约转移和建设承诺分别记账。\n\n'
            '![运行路径](baseline_path.svg)\n\n![历史接口检查](history_fit.svg)\n\n'
            '全国输入缺口以 workflow/q2_inputs.json 为准；该正式入口当前应拒绝产生全国结论。\n',encoding='utf-8')
        if scope=='national_q2':
            (stage/'report.md').write_text(
                '# Q2 全国条件模型运行记录\n\n本次运行通过输入指纹和历史质量检查；仍需逐项核对 B1—B9，运行成功不等于完整验收。\n\n'
                '逐年统计桥接、非能源排放和净移除依据见 national_accounting_path.csv；目标比较见 targets_2030_2060.csv。'
                '捕集仅从正排放扣一次，不计入净移除。GDP 由同一模型增长路径和固定可比价基数生成；2005、2025 强度基准分别核对。\n\n'
                f"实际运行 {len(fit['trials'])} 组训练候选及已接触留出；阈值/假设在输入清单中固定。"
                '目标未达到属于模型结果；未确定、缺项与求解失败另列。\n\n'
                '![源端能量与能源排放](baseline_path.svg)\n\n![历史拟合](history_fit.svg)\n',encoding='utf-8')
        code_paths=[ROOT/'run.py',Path(__file__),ROOT/'requirements-q2.txt',*sorted((ROOT/'src/energy_model/q2').glob('*.py'))]
        record={'owner':'p2/yx','run_id':run_id,'status':'engineering_success' if scope=='synthetic_engineering_only' else 'national_model_run_success','national_acceptance':False,
                'scope':scope,'command':['python','-B','-X','utf8','run.py','q2','--config',config_path,'--output-dir',output_dir],
                'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'git_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)),
                'python':sys.version,'platform':platform.platform(),
                'dependencies':{n:importlib.metadata.version(n) for n in ('mesa','numpy','scipy','pandas','matplotlib')},
                'solver':'SciPy HiGHS LP/MILP','seconds':time.perf_counter()-started,
                'config_path':config_path,'config_sha256':sha(config_file),'inputs':config['inputs'],
                'code_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in code_paths},
                'outputs':{p.name:sha(p) for p in sorted(stage.iterdir())}}
        dump(stage/'run_manifest.json',record)
        backup=None
        if out.exists():
            backup=out.parent/'archive'/out.name/run_id
            backup.parent.mkdir(parents=True,exist_ok=True)
            out.rename(backup)
        try:
            stage.rename(out)
        except Exception:
            if backup is not None:backup.rename(out)
            raise
        dump(latest,{'run_id':run_id,'status':record['status'],'output_valid_for_this_attempt':True,
                     'manifest_sha256':sha(out/'run_manifest.json'),'national_acceptance':False})
        print(json.dumps({'status':record['status'],'output':output_dir,'national_acceptance':False}))
        return 0
    except Exception as exc:
        failure={'run_id':run_id,'status':'failed','output_valid_for_this_attempt':False,
                 'national_acceptance':False,'error':str(exc),'exception':type(exc).__name__,
                 'config_path':config_path,'config_sha256':sha(config_file) if config_file.is_file() else None,
                 'seconds':time.perf_counter()-started,'gaps':getattr(exc,'gaps',[])}
        if stage.exists() and any(stage.iterdir()):
            diagnostics=out.parent/'failed'/out.name/run_id
            diagnostics.parent.mkdir(parents=True,exist_ok=True)
            stage.rename(diagnostics)
            failure['diagnostic_directory']=diagnostics.relative_to(ROOT).as_posix()
            failure['diagnostic_hashes']={p.name:sha(p) for p in diagnostics.iterdir() if p.is_file()}
        dump(latest,failure)
        dump(out.parent/(out.name+'.failed-attempt.json'),failure)
        print('Q2 FAILED: '+str(exc),file=sys.stderr)
        return 1
    finally:
        # Delete only the staging directory created by this invocation.
        if stage.exists() and stage.parent.resolve()==(ROOT/'tmp/q2').resolve() and stage.name=='run-'+run_id:
            shutil.rmtree(stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    raise SystemExit(execute(args.config,args.output_dir))
