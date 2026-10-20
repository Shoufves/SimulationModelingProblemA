"""Create a narrated, explicitly labelled replay of actual model results.

AI assisted: OpenAI Codex/GPT-6, 2026-10-20; public release date unavailable.
Local Windows SAPI synthetic narration; not a recording of a team member.
"""
from pathlib import Path
import argparse
import json
import math
import subprocess
import wave
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/question2_delivery_20261020"
TMP=ROOT/"tmp/question2_video"


def load(p):return json.loads(Path(p).read_text("utf-8"))
def font(size):return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",size)


def setup(run):
    TMP.mkdir(parents=True,exist_ok=True)
    b=load(run/"S0.json");p30=next(p for p in b['paths'] if p['year']==2030);p60=b['paths'][-1]
    slides=[
      dict(title="问题二：多智能体与双碳条件预测",tag="01 / 任务与数据",image="01_现状.png",
        bullets=["四项必做内容","历史证据与当前初态","2030及2060全指标"],
        narration="本视频只介绍问题二：主体设计、历史校准、基准预测和不确定性分析。问题一数据沿用已有成果。研究范围是中国大陆，包含电力和直接燃料消费，以二零二四年共同观测规模作为未来起点。"),
      dict(title="从当年运行反馈到下一年投资",tag="02 / 主体与机制",image=None,
        bullets=["18个聚合主体","先运行与结算，再投资","补贴应收和现金分开"],
        narration="模型包含十八个聚合主体。每年先更新投运退役，计算连续运行，结算收入、补贴与债务，再学习和提出投资。私人项目收益、共同额度、施工与融资共同约束建设，后续按工期投运。储能保持连续荷电状态。"),
      dict(title="历史趋势验证，如实保留误差",tag="03 / 校准与检验",image="02_历史验证.png",
        bullets=["训练：2015—2021","评估：2022—2024","总装机误差24.90%"],
        narration="参数只按二零一五至二零二一年训练选择。后续三年已经接触，不能称为盲测。能源总量和发电量误差较小，总装机误差仍为百分之二十四点九。因此不回填历史数据，未来采用独立观测初态，并报告财务与年龄重建假设。"),
      dict(title="逐年推演结果回放",tag="04 / 基准结果",image="dynamic",
        bullets=["2024观测规模起步","投资、运行与账本反馈","回放2025至2060"],
        narration=f"这里回放实际保存的逐年结果。二零三零年非化石能源份额约百分之{p30['nonfossil_share']*100:.1f}，正排放约{p30['positive_co2_t']/1e9:.2f}吉吨。二零六零年中和率约百分之{p60['neutralisation_ratio']*100:.1f}，净排放仍约{p60['net_co2_t']/1e9:.2f}吉吨。在这些假设下，尚不能实现碳中和。"),
      dict(title="三类关键参数做双侧扰动",tag="05 / 灵敏度",image="05_必选灵敏度.png",
        bullets=["GDP增速 ±1个百分点","年降本率 2%与4%","碳价水平 ×0.5与×1.5"],
        narration="对题目要求的经济增长、技术降本和碳价进行双侧扰动，同时考察年龄、债务、现金和在建队列。问题二共引用二十四组条件推演。部分碳价或技术扰动没有改变物理结果，只说明当前约束下未触发决策变化，不能外推为现实无效。"),
      dict(title="结论与可复核边界",tag="06 / 交付与限制",image="07_分技术误差.png",
        bullets=["基准全部指标已输出","来源、代码和结果可核对","历史偏差与政策代理保留"],
        narration="本稿已覆盖问题二四项要求，提供全部目标指标、代码、数据和复现入口。价格仍包含参考代理，单区域代表日和历史装机偏差限制结论。这是条件预测，不是官方达标认证。画面为真实结果回放，采用合成语音，内容由人工智能辅助，需团队独立核验。")]
    (TMP/"slides.json").write_text(json.dumps(slides,ensure_ascii=False,indent=2),'utf-8')
    (OUT/"问题二视频讲稿.md").write_text('# 仿真视频讲稿\n\n实际结果回放；Windows本地合成语音。无参赛队号，正式命名待团队填入。\n\n'+'\n\n'.join(f"## {s['tag']}：{s['title']}\n\n{s['narration']}" for s in slides),'utf-8')
    print('narration_chars',sum(len(s['narration']) for s in slides))


def wrap(draw,text,x,y,maxwidth,size=27,fill='#203C4A',linegap=10):
    f=font(size);line=''
    for ch in text:
        if draw.textlength(line+ch,font=f)>maxwidth:
            draw.text((x,y),line,font=f,fill=fill);y+=size+linegap;line=ch
        else:line+=ch
    if line:draw.text((x,y),line,font=f,fill=fill);y+=size+linegap
    return y


def frame(slide,idx,total,year=None,rows=None):
    im=Image.new('RGB',(1280,720),'#F3F6F8');d=ImageDraw.Draw(im)
    d.rectangle((0,0,1280,12),fill='#147D75')
    d.text((45,35),slide['tag'],font=font(22),fill='#147D75')
    d.text((45,77),slide['title'],font=font(40),fill='#153C55')
    y=175
    for text in slide['bullets']:
        d.ellipse((48,y+9,58,y+19),fill='#D08835')
        y=wrap(d,text,73,y,320,size=27)+20
    d.rounded_rectangle((415,155,1240,624),18,fill='white')
    if slide['image']=='dynamic':
        plot=(485,205,1190,545);left,top,right,bottom=plot
        ymax=14; ymin=7
        def xy(r):return (left+(r['year']-2025)/35*(right-left),bottom-(r['positive_co2_t']/1e9-ymin)/(ymax-ymin)*(bottom-top))
        for t in [8,10,12,14]:
            yy=bottom-(t-ymin)/(ymax-ymin)*(bottom-top)
            d.line((left,yy,right,yy),fill='#E4EBEF',width=1);d.text((440,yy-12),str(t),font=font(18),fill='#617785')
        d.text((454,168),'CO2正排放 / Gt',font=font(22),fill='#153C55')
        for yr in [2025,2030,2040,2050,2060]:
            x=left+(yr-2025)/35*(right-left);d.text((x-23,bottom+12),str(yr),font=font(18),fill='#617785')
        shown=[r for r in rows if r['year']<=year]
        pts=[xy(r) for r in shown]
        if len(pts)>1:d.line(pts,fill='#147D75',width=5)
        x,y=pts[-1];d.ellipse((x-6,y-6,x+6,y+6),fill='#D08835')
        r=shown[-1];d.text((740,165),f"{year}年  非化石 {r['nonfossil_share']*100:.1f}%",font=font(23),fill='#153C55')
        d.text((610,590),'保存路径回放 · 非实时求解画面',font=font(20),fill='#617785')
    elif slide['image']:
        img=Image.open(OUT/'figures'/slide['image']).convert('RGB');img.thumbnail((800,440),Image.Resampling.LANCZOS)
        im.paste(img,(415+(825-img.width)//2,155+(469-img.height)//2))
    else:
        boxes=[('年度驱动与投退',510,190),('连续能源运行',910,190),('经营财政结算',910,410),('学习与投资审核',510,410)]
        for txt,x,y in boxes:
            d.rounded_rectangle((x,y,x+235,y+105),14,fill='#E6EFF2',outline='#147D75',width=2)
            d.text((x+15,y+37),txt,font=font(25),fill='#153C55')
        for a,b in [((745,242),(910,242)),((1025,295),(1025,410)),((910,462),(745,462)),((625,410),(625,295))]:
            d.line((*a,*b),fill='#D08835',width=4)
            dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy);ux,uy=dx/length,dy/length
            d.polygon([b,(b[0]-12*ux-6*uy,b[1]-12*uy+6*ux),(b[0]-12*ux+6*uy,b[1]-12*uy-6*ux)],fill='#D08835')
        d.text((548,560),'资金守恒 + 能量守恒 + 年度反馈',font=font(25),fill='#153C55')
    d.text((45,652),'AI辅助研究稿 · 条件预测 · 合成语音',font=font(20),fill='#617785')
    d.text((1100,652),f'{idx+1:02d} / {total:02d}',font=font(20),fill='#617785')
    d.rectangle((45,694,1235,699),fill='#DCE4E8');d.rectangle((45,694,45+1190*(idx+1)/total,699),fill='#147D75')
    return im


def render(run):
    import imageio_ffmpeg
    slides=load(TMP/'slides.json');rows=load(run/'S0.json')['paths']
    fmt=None;segments=[];durations=[]
    for i in range(len(slides)):
        with wave.open(str(TMP/f'voice_{i}.wav'),'rb') as f:
            params=f.getparams();raw=f.readframes(f.getnframes())
        current=(params.nchannels,params.sampwidth,params.framerate)
        if fmt is None:fmt=current
        if fmt!=current:raise ValueError('Inconsistent narration format')
        duration=params.nframes/params.framerate
        # Padding keeps complete sentence endings, total remains under 180 s.
        pad=.45;segments.append(raw+b'\0'*int(pad*params.framerate)*params.nchannels*params.sampwidth);durations.append(duration+pad)
    total=sum(durations)
    if total>178:raise ValueError(f'Narration too long: {total:.3f}; regenerate faster')
    with wave.open(str(TMP/'narration.wav'),'wb') as f:
        f.setnchannels(fmt[0]);f.setsampwidth(fmt[1]);f.setframerate(fmt[2]);f.writeframes(b''.join(segments))
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    writer=imageio_ffmpeg.write_frames(str(TMP/'silent.mp4'),(1280,720),fps=10,codec='libx264',quality=7,
        pix_fmt_in='rgb24',pix_fmt_out='yuv420p',output_params=['-preset','fast','-movflags','+faststart'])
    writer.send(None);actual=0
    try:
        for i,(s,duration) in enumerate(zip(slides,durations)):
            count=round(duration*10);cached={}
            for j in range(count):
                yr=2025+min(35,int(j*36/count)) if s['image']=='dynamic' else None
                if yr not in cached:cached[yr]=frame(s,i,len(slides),year=yr,rows=rows).tobytes()
                writer.send(cached[yr])
            frame(s,i,len(slides),year=2060 if s['image']=='dynamic' else None,rows=rows).save(OUT/f'video_slide_{i+1:02d}.png')
            actual+=count/10
    finally:writer.close()
    dest=OUT/'问题二-演示稿.mp4'
    subprocess.run([ffmpeg,'-y','-i',str(TMP/'silent.mp4'),'-i',str(TMP/'narration.wav'),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',str(dest)],check=True,capture_output=True)
    metadata=imageio_ffmpeg.read_frames(str(dest));info=next(metadata);metadata.close()
    if info['duration']>180 or tuple(info['size'])!=(1280,720):raise ValueError(info)
    result=dict(duration_seconds=info['duration'],size_pixels=info['size'],bytes=dest.stat().st_size,narration='Local Windows SAPI Huihui synthetic voice',content='Replay of actual saved results, explicitly labelled',source_run=run.relative_to(ROOT).as_posix(),segments=[dict(title=s['title'],duration_seconds=d) for s,d in zip(slides,durations)])
    (OUT/'video_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['setup','render']);p.add_argument('run');a=p.parse_args()
    (setup if a.mode=='setup' else render)(ROOT/a.run)
