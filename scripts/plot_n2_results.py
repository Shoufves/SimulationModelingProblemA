"""Standalone scientific figure from the frozen validation receipt only."""
from pathlib import Path
import argparse
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--output',required=True);args=p.parse_args()
    directory=Path(args.directory);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    report=json.loads((directory/'acceptance.json').read_text('utf-8'))
    rows=report['conditions'];labels=[r['condition'].split('_')[0] for r in rows]
    retained=[100*r['comparison']['retention_reduction_fraction'] for r in rows]
    risk=[100*r['comparison']['maximum_service_fraction_regret'] for r in rows]
    money=[];ratio=[]
    for row in rows:
        folder=directory/row['condition'];summaries=json.loads((folder/'summary.json').read_text('utf-8'))
        candidate=next(r for r in summaries if r['name'].endswith('__anchored_guard'))
        baseline=next(r for r in summaries if r['name'].endswith('__rolling_guard'))
        money.append((baseline['discounted_resource_cost_cny']-candidate['discounted_resource_cost_cny'])/1e9)
        ratio.append(candidate['elapsed_seconds']/baseline['elapsed_seconds'])
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,'svg.hashsalt':'n2-validation'})
    fig,axes=plt.subplots(2,2,figsize=(10,6.6),layout='constrained')
    for ax,values,title,ylabel in zip(axes.flat,[retained,risk,money,ratio],
        ['A. Retention reduction','B. Worst service/year regret','C. Discounted resource-cost saving','D. Computation overhead'],
        ['Retained MW-years saved (%)','Deficit fraction change (percentage points)','2024 CNY billion','Wall-time ratio vs original guard']):
        ax.bar(labels,values,color='#246A91',width=.65)
        ax.set_title(title,loc='left',weight='bold');ax.set_ylabel(ylabel)
        ax.axhline(0,color='#444444',linewidth=.7);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
        if max(abs(v) for v in values)<1e-8:ax.set_ylim(-.01,.01)
    fig.suptitle('Anchored feedback screening vs original rolling retirement rule',weight='bold')
    fig.supxlabel('Frozen conditional scenarios, 2025–2060. These comparisons do not certify system adequacy.',fontsize=9)
    metadata={'png':{'Software':'Matplotlib scientific evidence'},'pdf':{'CreationDate':None,'ModDate':None},'svg':{'Date':None}}
    for suffix in ('png','pdf','svg'):fig.savefig(out/('n2_validation.'+suffix),dpi=220,metadata=metadata[suffix])
    svg=out/'n2_validation.svg'
    svg.write_bytes(('\n'.join(line.rstrip() for line in svg.read_text('utf-8').splitlines())+'\n').encode('utf-8'))
    plt.close(fig)


if __name__=='__main__':main()
