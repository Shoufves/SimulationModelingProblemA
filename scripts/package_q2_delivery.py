"""Package the Q2-only handoff without altering the frozen experiment.

AI assisted: OpenAI Codex/GPT-6, 2026-10-20; release date unavailable.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/question2_delivery_20261020"
RUN=ROOT/"outputs/q2_current_delivery/20261020T004752442611Z"


def load(p):return json.loads(Path(p).read_text('utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n','utf-8')


def source_closure(initial):
    """Follow explicit local evidence references, including nested reviews."""
    result=set(initial);pending=list(initial);checked=set()
    def strings(value):
        if isinstance(value,str):yield value
        elif isinstance(value,dict):
            for k,v in value.items():yield from strings(k);yield from strings(v)
        elif isinstance(value,list):
            for v in value:yield from strings(v)
    while pending:
        rel=pending.pop();path=ROOT/rel
        if path.suffix.lower()!='.json':continue
        try:parsed=load(path)
        except (ValueError,UnicodeError):continue
        for text in strings(parsed):
            if len(text)>350 or '\n' in text or '://' in text:continue
            root_style=text.startswith(('data/','docs/','src/','scripts/','workflow/','outputs/')) or text=='run.py' or text.startswith('requirements-')
            local_file=('/' not in text and '\\' not in text and text.lower().endswith(('.pdf','.csv','.json','.xlsx','.jpg','.png','.html','.txt','.py')))
            if not root_style and not local_file:continue
            cache_key=(str(path.parent),text)
            if cache_key in checked:continue
            checked.add(cache_key)
            candidates=[ROOT/text,path.parent/text]
            for candidate in candidates:
                try:resolved=candidate.resolve()
                except (ValueError,OSError):continue
                if not resolved.is_relative_to(ROOT):continue
                name=resolved.relative_to(ROOT).as_posix()
                if name.startswith(('tmp/','.git/','data/restricted/')) or resolved.suffix.lower()=='.zip':continue
                if name not in result and resolved.is_file():result.add(name);pending.append(name)
    return result


def ai_disclosure():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from html import escape
    pdfmetrics.registerFont(TTFont('Q2Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('Q2Hei','C:/Windows/Fonts/simhei.ttf'))
    texts=[
      ('AI工具使用详情说明','本说明用于问题二研究稿的真实交接，不替参赛队作独立完成或人工复核承诺。'),
      ('1 工具与日期','OpenAI Codex，当前主模型GPT-6；本轮2026-10-20。用户此前允许使用一个子智能体协助，本轮用于当前初态工厂与只读结果/文字核对。公开版本发布日期未由环境提供，不填造具体日期。语音使用本地Windows SAPI Huihui合成。'),
      ('2 应用环节','AI参与资料整理、代码实现与修复、历史校准实验编排、当前初态重建、敏感性执行、结果核验、图表和答题稿生成、离线复现入口以及视频制作。参与程度包括核心代码和分析，而非仅文字润色。'),
      ('3 关键交互：任务收缩','用户明确：“题目没有强求的可以先不做，以完成题目为优先，三小时限制是让你完成题目”。据此保留题面历史校准与趋势验证，不再把内部MAPE门槛当比赛硬性要求，不再增加大规模参数搜索。'),
      ('4 关键交互：范围','用户随后明确：“问题三不用做”。本次正式交付目录仅包括问题二；问题一沿用既有成果，原已执行的其他实验保留备查，但不进入当前答题稿或复现默认集合。'),
      ('5 关键交互：复核与修正','只读复核发现年度顺序、变弹性需求公式、私人NPV与价格来源表述需修正，答题稿已按实际代码重写。周期为当期运行与结算后再学习和投资；需求按GDP年增长递推；项目评价允许挤出存量销售；2024实值不等于2024实测价格。'),
      ('6 数值与图表贡献','图表与表格由AI辅助脚本直接读取冻结结果。数据原始观测来自公开材料；初态财务、年龄、在建队列及未来参数中存在作者条件假设，正文分别标注。提取输入快照不包含驱动仿真的未来参考路径，后者仅在重新求解后核对。'),
      ('7 采纳与人工修改','现有会话显示用户批准路线、限定范围并要求修复，但没有证据证明队员已独立重写全部核心建模、实现和分析，也没有完整人工修改记录。因此当前状态为AI辅助研究稿，人工复核及采用情况待队员据实补录。不能将本说明改成“未使用AI”或笼统宣称核心内容已由人独立完成。'),
      ('8 仍需队员核验','重点核验模型适用边界、2024初态选择、历史装机误差、价格与政策代理、参考文献原件及比赛独立完成要求。正文、代码、数据和数字一致并不自动等于科学正确或参赛资格认可。本说明不包含虚构队号、签名、学校或参赛者身份。'),
      ('9 材料索引','问题二答题稿MD/PDF、24案逐年与目标数据、提取输入/原件来源清单、529项测试记录、独立复核、视频及讲稿。具体文件与SHA256列在压缩包的PACKAGE_MANIFEST.json。')]
    body=ParagraphStyle('body',fontName='Q2Song',fontSize=12,leading=17,spaceAfter=10,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=body,fontName='Q2Hei',fontSize=14,leading=20,spaceBefore=10,keepWithNext=True)
    story=[];md=[]
    for title,text in texts:
        story.extend([Paragraph(escape(title),heading),Paragraph(escape(text),body)])
        md.append('## '+title+'\n\n'+text)
    SimpleDocTemplate(str(OUT/'AI工具使用详情说明.pdf'),pagesize=A4,leftMargin=54,rightMargin=54,topMargin=45,bottomMargin=45,author='',title='AI工具使用详情说明').build(story)
    (OUT/'AI工具使用详情说明.md').write_text('# 问题二AI使用说明\n\n'+'\n\n'.join(md)+'\n','utf-8')


def package():
    ai_disclosure()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    stage=ROOT/'tmp'/('q2_delivery_stage_'+stamp);stage.mkdir()
    files=set()
    for folder in ('src','scripts'):
        files.update(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*.py') if '__pycache__' not in p.parts)
    for folder in ('data/processed/q1','data/processed/q2','data/processed/q2_delivery'):
        files.update(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*') if p.is_file())
    sourcehashes=load(RUN/'source_snapshot.json')
    runtime_readers={p.relative_to(ROOT).as_posix() for p in (ROOT/'data/raw').rglob('*.py') if '__pycache__' not in p.parts}
    runtime_manifests={(ROOT/p).parent.joinpath('source_manifest.json').relative_to(ROOT).as_posix() for p in runtime_readers if (ROOT/p).parent.joinpath('source_manifest.json').is_file()}
    compact_sources=source_closure(set(sourcehashes))
    runtime_reviews={p.relative_to(ROOT).as_posix() for p in (ROOT/'data/catalog').glob('q2*.json')}
    fullsources=source_closure(compact_sources|runtime_readers|runtime_manifests|runtime_reviews)
    files.update(p for p in compact_sources if not p.startswith(('data/raw/','outputs/')))
    # Original small tables/pages and actual observations stay in the compact
    # archive. Large reference publications are separately disclosed, not
    # silently changed or claimed to have been reverified by compact execution.
    selected_raw=[];omitted=[]
    for p in sorted(compact_sources):
        if not p.startswith('data/raw/'):continue
        h=sha(ROOT/p)
        if (ROOT/p).stat().st_size<=4_000_000 and not p.endswith(('sanfeng_2020_ipo_summary.pdf','changqing_2021.pdf')):
            files.add(p);selected_raw.append(p)
        else:omitted.append(dict(path=p,sha256=h,bytes=(ROOT/p).stat().st_size,reason='Complete reference publication in full research package; parsed inputs included here'))
    for p in ('requirements-q2.txt','requirements-q1.txt','requirements-data.txt',
              'docs/solutions/QUESTION2_DELIVERY_20261020.md',
              'outputs/validation/current_opening_review_20261020.json',
              'outputs/validation/current_delivery_review_20261020.json',
              'outputs/validation/full_tests_delivery_workspace_temp_20261020.log',
              'outputs/validation/portable_full_20261020.log',
              'outputs/validation/portable_isolated_package_20261020.log',
              'outputs/validation/full_package_isolated_20261020.log',
              'outputs/validation/full_package_report_rebuild_20261020.log',
              'outputs/validation/q2_paper_review_20261020.json'):
        files.add(p)
    # The Q1 report is not re-delivered; only its provenance data supports the
    # short Q1-to-Q2 bridge. The corrected oil scope is in the new Q2 paper.
    for p in ('outputs/q1/p1_yx/history.csv','outputs/q1/p1_yx/indicators.csv','outputs/q1/p1_yx/run_manifest.json'):
        files.add(p)
    for p in OUT.rglob('*'):
        if p.is_file() and p.suffix.lower() in {'.md','.pdf','.csv','.json','.png','.svg'} and p.name not in {'package_validation.json','answer_manifest.json'} and not p.name.startswith('video_slide_'):
            files.add(p.relative_to(ROOT).as_posix())
    for p in sorted(files):
        target=stage/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,target)
    shutil.copyfile(ROOT/'docs/solutions/QUESTION2_DELIVERY_20261020.md',stage/'先读我_问题二运行说明.md')
    save(stage/'OMITTED_LARGE_REFERENCES.json',omitted)
    save(stage/'PACKAGE_MANIFEST.json',dict(scope='Question 2 only; raw-document subset plus verified parsed inputs',
        original_source_run=RUN.relative_to(ROOT).as_posix(),
        portable_original_revalidation=False,files={p.relative_to(stage).as_posix():sha(p) for p in stage.rglob('*') if p.is_file()},
        full_raw_sources='问题二完整研究复现包.zip',omitted_original_count=len(omitted)))
    light=OUT/'问题二轻量支撑包.zip'
    with zipfile.ZipFile(light,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(stage).as_posix())
    # Complete raw verification package: same relative repository layout,
    # complete source closure, historical verification inputs and all Q2 cases.
    fullfiles=set(files)|fullsources
    for p in sourcehashes:
        if p.startswith('outputs/q2_revenue_recalibration/'):
            parent=(ROOT/p).parent
            fullfiles.update(x.relative_to(ROOT).as_posix() for x in parent.glob('*.json'))
    relevant=load(ROOT/'data/processed/q2_delivery/q2_design.json')['scenarios']
    for p in ('source_snapshot.json','design.json','results.json','status.json','targets.csv'):
        fullfiles.add((RUN/p).relative_to(ROOT).as_posix())
    for spec in relevant:
        for suffix in ('.json','_path.csv'):
            fullfiles.add((RUN/(spec['name']+suffix)).relative_to(ROOT).as_posix())
    full=OUT/'问题二完整研究复现包.zip'
    with zipfile.ZipFile(full,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(fullfiles):z.write(ROOT/p,p)
        z.write(stage/'先读我_问题二运行说明.md','先读我_问题二运行说明.md')
        manifest=dict(scope='Complete Q2 source closure; original common batch index contains optional cases not redelivered',files={p:sha(ROOT/p) for p in sorted(fullfiles)})
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    proof=dict(stage=stage.relative_to(ROOT).as_posix(),light_bytes=light.stat().st_size,
        light_under_20_MB=light.stat().st_size<20_000_000,light_sha256=sha(light),full_bytes=full.stat().st_size,full_sha256=sha(full),
        q2_case_count=len(relevant),omitted_large_originals=omitted)
    save(OUT/'package_validation.json',proof)
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    if not proof['light_under_20_MB']:raise ValueError('Compact package exceeds competition limit')


if __name__=='__main__':package()
