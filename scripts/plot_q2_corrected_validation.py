"""Export observed/model paths with an explicit already-seen evaluation window."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from q2_corrected_factory import preflight, scope_inputs
from review_q2_revenue_candidate import review


def main():
    folder = (ROOT / sys.argv[1]).resolve()
    review(folder)
    design = json.loads((folder/'design.json').read_text('utf-8'))
    if design.get('model_factory') != 'q2_corrected_factory:build':
        raise ValueError('Expected corrected model research run')
    case = json.loads((folder/'authority_25_full.json').read_text('utf-8'))
    data, national, _ = preflight()
    observed, *_ = scope_inputs(data, national, case['parameters'], recovery_share=.5)
    paths = {r['year']: r for r in case['paths']}
    years = list(range(2015,2025))
    specs = [
        ('气电发电量','gas_generation_mwh','gas_electricity_mwh',1e6,'TWh'),
        ('纯油发电量','oil_generation_mwh','oil_electricity_mwh',1e6,'TWh'),
        ('复合生物能源发电量','biomass_generation_mwh','biofuel_electricity_mwh',1e6,'TWh'),
        ('风电发电量','wind_generation_mwh','wind_electricity_mwh',1e6,'TWh'),
        ('光伏发电量','solar_generation_mwh','solar_electricity_mwh',1e6,'TWh'),
        ('总装机容量','total_capacity_mw','capacity_total_10kmw',1e3,'GW'),
        ('风电装机容量','wind_capacity_mw','capacity_wind_10kmw',1e3,'GW'),
        ('光伏装机容量','solar_capacity_mw','capacity_solar_10kmw',1e3,'GW'),
    ]
    # Capacity observation keys/units come from the same reviewed target mapping.
    targets = {t['metric']:t for t in national['targets']}
    rows=[]
    for title, metric, key, scale, unit in specs:
        multiplier = 1
        if 'capacity' in metric:
            key = targets[metric]['observation']
            multiplier = targets[metric]['multiplier']
        rows.append(dict(title=title, metric=metric, observation=key, unit=unit,
            observation_multiplier=multiplier, display_divisor=scale,
            years=years, observed=[observed[y,key]*multiplier/scale for y in years],
            model=[paths[y][metric]/scale for y in years]))
    font_path=Path('C:/Windows/Fonts/msyh.ttc')
    if font_path.is_file():
        font=FontProperties(fname=str(font_path))
        plt.rcParams['font.family']=font.get_name()
    plt.rcParams['axes.unicode_minus']=False
    plt.rcParams['svg.fonttype']='none'
    fig,axes=plt.subplots(4,2,figsize=(12,13),sharex=True,layout='constrained')
    for ax,row in zip(axes.flat,rows):
        ax.axvspan(2021.5,2024.35,color='#fff0df',zorder=0)
        ax.plot(years,row['observed'],color='#263f57',marker='o',markersize=3,label='观测')
        ax.plot(years,row['model'],color='#b94439',marker='s',markersize=3,label='模型')
        ax.set_title(row['title'],loc='left',fontsize=12,weight='bold')
        ax.set_ylabel(row['unit']);ax.set_xlim(2014.7,2024.35);ax.set_ylim(bottom=0)
        ax.set_xticks([2015,2017,2019,2021,2022,2024])
        ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    axes.flat[0].legend(frameon=False,ncol=2)
    fig.suptitle('历史验证：发电量较接近，装机仍明显不足\n2015—2021训练；橙色区域为2022—2024已接触评估',fontsize=16,weight='bold')
    fig.supxlabel('年份 · 授权倍数25为条件假设；其余两组亦完整报告。本图不是最终验收。',fontsize=10)
    out=folder/'figures';out.mkdir(exist_ok=True)
    fig.savefig(out/'historical_validation.png',dpi=160)
    fig.savefig(out/'historical_validation.svg')
    plt.close(fig)
    sources=json.loads((folder/'results.json').read_text('utf-8'))['source_sha256']
    for path in (Path(__file__),folder/'results.json',folder/'authority_25_full.json'):
        sources[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    payload=dict(created_at=datetime.now(timezone.utc).isoformat(),source_sha256=sources,
        data=rows,evaluation_identity='already_seen_not_blind',scientific_acceptance=False)
    (out/'plot_data.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(out.relative_to(ROOT).as_posix())


if __name__=='__main__':
    main()
