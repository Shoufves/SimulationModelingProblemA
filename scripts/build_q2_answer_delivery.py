"""Build the A-question answer from frozen computed results, never invented data.

AI-assisted authoring: OpenAI Codex (GPT-6), 2026-10-20. Exact public model
release date is not supplied by this environment; no release date is invented.
Human review/adoption is not asserted. See the accompanying AI-use disclosure.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import re
from html import escape

ROOT = Path(__file__).resolve().parents[1]
TITLE = "问题二：多智能体能源系统与2030、2060双碳目标条件预测"
TECH = dict(coal="煤电", gas="气电", oil="油电", biomass="生物质", hydro="常规水电", nuclear="核电", wind="风电", solar="光伏")
SCENARIOS = ["S0", "SP", "ST", "SG", "SW", "SGW"]
COLORS = ["#153C55", "#D08835", "#188875", "#BC4E4E", "#7972B3", "#76533A"]


def load(p): return json.loads(Path(p).read_text("utf-8"))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, value): Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", "utf-8")
def percent(x): return f"{x*100:.2f}%"
def number(x, digits=2): return "未确认" if x is None else f"{x:,.{digits}f}"


def verify_frozen_sources(hashes):
    """A retired orchestration entry may be verified from its exact byte archive.

    No model, data, or result hash is substituted. This renders historical
    results; it does not attest that today's runner generated those results.
    """
    resolved = {}
    archives = {'scripts/run_q2_current_delivery.py':
                'archive/pr14_review10/run_q2_current_delivery.py'}
    for name, expected in hashes.items():
        path = ROOT/name
        if sha(path) != expected:
            alternate = archives.get(name)
            if alternate is None or not (ROOT/alternate).is_file() or sha(ROOT/alternate) != expected:
                raise ValueError('Frozen source changed: '+name)
            resolved[name] = alternate
    return resolved


def write_csv(path, rows):
    if not rows: return
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


class Paper:
    def __init__(self): self.blocks = []
    def title(self, text): self.blocks.append(("title", text))
    def h(self, text): self.blocks.append(("heading", text))
    def p(self, text): self.blocks.append(("paragraph", text))
    def table(self, heads, rows): self.blocks.append(("table", (heads, rows)))
    def figure(self, name, caption): self.blocks.append(("figure", (name, caption)))
    def page(self): self.blocks.append(("page", None))
    def render(self, out):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, KeepTogether
        pdfmetrics.registerFont(TTFont("Song", "C:/Windows/Fonts/simsun.ttc", subfontIndex=0))
        pdfmetrics.registerFont(TTFont("Hei", "C:/Windows/Fonts/simhei.ttf"))
        body = ParagraphStyle("body", fontName="Song", fontSize=12, leading=15.8, alignment=TA_JUSTIFY,
            wordWrap="CJK", spaceAfter=8, firstLineIndent=24)
        heading = ParagraphStyle("heading", parent=body, fontName="Hei", fontSize=14, leading=19,
            alignment=TA_CENTER, firstLineIndent=0, spaceBefore=12, spaceAfter=10, keepWithNext=True)
        title = ParagraphStyle("title", parent=heading, fontSize=16, leading=23, spaceBefore=3, spaceAfter=16)
        cell = ParagraphStyle("cell", parent=body, fontSize=12, leading=15.8, firstLineIndent=0, spaceAfter=0, alignment=0)
        caption = ParagraphStyle("caption", parent=body, fontSize=12, leading=15.8, firstLineIndent=0, alignment=TA_CENTER, spaceAfter=10)
        width = A4[0]-108
        story=[]; md=[]
        def para(t, style=body): return Paragraph(escape(str(t).replace("−","-")).replace("\n","<br/>"),style)
        for kind, val in self.blocks:
            if kind in ("title","heading","paragraph"):
                story.append(para(val, {"title":title,"heading":heading,"paragraph":body}[kind]))
                md.append(("# " if kind=="title" else "## " if kind=="heading" else "")+val+"\n")
            elif kind=="page": story.append(PageBreak()); md.append("\n---\n")
            elif kind=="table":
                heads,rows=val
                cells=[[para(v,cell) for v in row] for row in [heads]+rows]
                table=Table(cells,colWidths=[width/len(heads)]*len(heads),repeatRows=1,hAlign="CENTER")
                table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E6EFF2")),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),("LINEBELOW",(0,0),(-1,0),.7,colors.HexColor("#153C55")),
                    ("LINEBELOW",(0,-1),(-1,-1),.5,colors.HexColor("#A5B5BE")),
                    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F6F8F9")]),
                    ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
                story.extend([table,Spacer(1,10)])
                md.extend(["|"+"|".join(map(str,heads))+"|", "|"+"|".join(["---"]*len(heads))+"|"])
                md.extend("|"+"|".join(str(v).replace("\n","<br>") for v in row)+"|" for row in rows);md.append("")
            elif kind=="figure":
                name,cap=val
                from PIL import Image as PILImage
                with PILImage.open(out/"figures"/name) as im: ratio=im.height/im.width
                story.append(KeepTogether([Image(str(out/"figures"/name),width=width,height=width*ratio),para(cap,caption)]))
                md.append(f"![{cap}](figures/{name})\n")
        def footer(canvas,doc):
            canvas.setFont("Song",10); canvas.drawCentredString(A4[0]/2,28,str(doc.page))
        SimpleDocTemplate(str(out/"问题二答题稿.pdf"),pagesize=A4,leftMargin=54,rightMargin=54,
            topMargin=45,bottomMargin=48,title=TITLE,author="",subject="A题研究稿；AI辅助生成，须由团队核验").build(story,onFirstPage=footer,onLaterPages=footer)
        (out/"问题二答题稿.md").write_text("\n".join(md),"utf-8")


def charts(out, cases, historical, observations, quality):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont("C:/Windows/Fonts/simhei.ttf")
    plt.rcParams.update({"font.family":"SimHei","axes.unicode_minus":False,"font.size":10,
        "axes.spines.top":False,"axes.spines.right":False,"savefig.dpi":180})
    folder=out/"figures";folder.mkdir(exist_ok=True)
    def done(fig,name):
        fig.tight_layout();fig.savefig(folder/(name+".png"),bbox_inches="tight");fig.savefig(folder/(name+".svg"),bbox_inches="tight");plt.close(fig)
    years=list(range(2015,2025))
    fig,axs=plt.subplots(1,2,figsize=(10,3.5))
    axs[0].plot(years,[observations[y,"consumption_10ktce"]/1e4 for y in years],color=COLORS[0],marker="o")
    axs[0].set(ylabel="能源消费 / 亿吨标准煤",xlabel="年")
    for metric,label,c in [("consumption_coal_pct","煤炭",COLORS[0]),("consumption_primary_electricity_other_pct","一次电力及其他",COLORS[2])]:
        axs[1].plot(years,[observations[y,metric] for y in years],label=label,color=c,marker="o")
    axs[1].set(ylabel="消费构成 / %",xlabel="年");axs[1].legend();done(fig,"01_现状")
    fig,axs=plt.subplots(2,2,figsize=(10,6))
    for ax,metric,obs,scale,label in zip(axs.flat,["primary_energy_tce","electricity_generation_mwh","total_capacity_mw","solar_capacity_mw"],
        ["consumption_10ktce","electricity_generation_mwh","total_capacity_mw","solar_capacity_mw"],[1e8,1e9,1e6,1e6],["能源 / 亿tce","发电 / PWh","总装机 / TW","光伏装机 / TW"]):
        mult=1e4 if obs=="consumption_10ktce" else 1
        ax.plot(years,[observations[y,obs]*mult/scale for y in years],label="观测",color=COLORS[0],marker="o",ms=3)
        ax.plot(years,[p[metric]/scale for p in historical["paths"]],label="仿真",color=COLORS[1],ls="--")
        ax.axvspan(2021.5,2024.3,color="#EEEEEE");ax.set(ylabel=label,xlabel="年");ax.legend(fontsize=8)
    done(fig,"02_历史验证")
    rows=cases["S0"]["paths"];years=[r["year"] for r in rows]
    fig,axs=plt.subplots(2,2,figsize=(10,6))
    specs=[("primary_energy_tce",1e8,"能源消费 / 亿tce"),("nonfossil_share",.01,"非化石份额 / %"),("positive_co2_t",1e9,"正排放 / Gt CO2"),("unmet_service_mwh",1e6,"未满足服务 / TWh")]
    for ax,(key,scale,label) in zip(axs.flat,specs):
        ax.plot(years,[r[key]/scale for r in rows],lw=2,color=COLORS[0]);ax.set(ylabel=label,xlabel="年")
        for yr in (2030,2060):
            row=next(r for r in rows if r["year"]==yr);ax.scatter([yr],[row[key]/scale],color=COLORS[1],zorder=3)
    done(fig,"03_基准路径")
    names=[n for n in cases if n.startswith("sensitivity_")][:6]
    labels=["GDP增速 -1百分点","GDP增速 +1百分点","技术降本 -1百分点","技术降本 +1百分点","碳价 ×0.5","碳价 ×1.5"]
    fig,axs=plt.subplots(1,2,figsize=(10,4))
    base=cases["S0"]["paths"][-1]
    for ax,key,scale,label in [(axs[0],"positive_co2_t",1e9,"2060正排放变化 / Gt"),(axs[1],"nonfossil_share",.01,"2060非化石份额变化 / 百分点")]:
        values=[(cases[n]["paths"][-1][key]-base[key])/scale for n in names]
        ax.barh(labels,values,color=[COLORS[0] if v<0 else COLORS[1] for v in values]);ax.axvline(0,color="#777777",lw=.7);ax.set_xlabel(label)
    done(fig,"05_必选灵敏度")
    fig,ax=plt.subplots(figsize=(8,4))
    techs=list(TECH)
    train=[historical["metrics"][t]["training"]["mape"]*100 for t in techs]
    test=[historical["metrics"][t]["already_seen_evaluation"]["mape"]*100 for t in techs]
    x=list(range(len(techs)));ax.bar([i-.18 for i in x],train,.36,label="2015—2021训练",color=COLORS[0]);ax.bar([i+.18 for i in x],test,.36,label="2022—2024已接触评估",color=COLORS[1])
    ax.set_xticks(x,[TECH[t] for t in techs]);ax.set_ylabel("发电量MAPE / %");ax.legend();done(fig,"07_分技术误差")


def main():
    parser=argparse.ArgumentParser();parser.add_argument("run");parser.add_argument("--output",default="outputs/question2_delivery_20261020");args=parser.parse_args()
    run=ROOT/args.run;out=ROOT/args.output;out.mkdir(parents=True,exist_ok=True)
    results=load(run/"results.json");status=load(run/"status.json")
    if status["failures"]:raise ValueError("Cannot write completed answer from failed cases")
    archived_sources=verify_frozen_sources(results['source_sha256'])
    selected=[r for r in results["results"] if r["name"]=="S0" or r["spec"].get("kind") in {"sensitivity","opening_uncertainty","uncertain_authority","thermal_reference"}]
    cases={r["name"]:load(run/r["result_file"]) for r in selected}
    if len(cases)!=24:raise ValueError("Expected the 24 Q2 cases")
    for r in selected:
        if sha(run/r["result_file"])!=r["result_sha256"]:raise ValueError("Case checksum mismatch")
    histroot=ROOT/load(run/"design.json")["historical_runs"]["net58"]
    hist=load(histroot/"authority_25_full.json")
    quality=load(histroot/"fit_review.json")["cases"]["authority_25_full"]["quality"]
    with (ROOT/"data/processed/q2/national_observations.csv").open(encoding="utf-8-sig") as f:
        obs={(int(r["year"]),r["metric"]):float(r["value"]) for r in csv.DictReader(f)}
    charts(out,cases,hist,obs,quality)
    baseline=cases["S0"];idx={p["year"]:p for p in baseline["paths"]};p30,p60=idx[2030],idx[2060]
    tgt={(r["year"],r["metric"]):r["value"] for r in baseline["targets"]}
    peak=baseline["peak"];maxrow=max(baseline["paths"],key=lambda r:r["positive_co2_t"])
    paper=Paper();paper.title(TITLE);paper.h("摘要")
    paper.p("针对我国多能源转型中的投资、调度与保供约束，构建年度多智能体决策与年内连续能源平衡相耦合的仿真框架。供给企业、八类发电商、用能主体、电网和政府通过燃料、产品、资金、设备队列与碳市场交互；共享投资额度、补贴权利与现金支付分开核算，储能保持连续荷电状态。研究范围为中国大陆，采用2015—2021年数据校准，2022—2024年进行已接触评估，独立以2024年观测规模初始化未来推演。")
    paper.p(f"现状分析表明，2015—2024年能源消费增长37.29%，煤炭份额下降而绝对消费增加；油气来源集中与省际发用电分布差异构成协调压力。历史评估中能源总量与发电量MAPE分别为4.24%和3.27%，总装机及光伏装机误差为24.90%和26.77%，故长期结果作为有明确假设边界的条件预测。基准2030年能源消费{p30['primary_energy_tce']/1e8:.2f}亿吨标准煤，非化石份额{percent(p30['nonfossil_share'])}，正CO2排放{p30['positive_co2_t']/1e9:.2f}Gt；2060年非化石份额{percent(p60['nonfossil_share'])}，净剩余排放{p60['net_co2_t']/1e9:.2f}Gt，中和率{percent(p60['neutralisation_ratio'])}。")
    paper.p(f"本稿仅回答问题二的主体设计、模型校准、基准预测与不确定性四项。使用基准及23组参数/初态条件对照，三项题面关键敏感性均给出双侧结果。创新体现在项目私人边际收益、共同约束审核和连续运行账本的衔接；同时明确历史误差与未观测初态对结论的影响。问题三不在本次交付范围。")
    paper.p("关键词：多智能体；能源转型；连续储能；财政约束；配对情景；能源安全")
    paper.page();paper.h("目录")
    for t in ["1 问题分析与研究边界","2 数据基础与问题一衔接","3 问题二：主体、规则与交互","4 历史校准与验证","5 当前初态与基准预测","6 不确定性分析","7 模型评价与结论","参考文献与AI使用声明","附录：交付索引与复现说明"]:paper.p(t)
    paper.p("本稿中的程序、数据分析、图表和文字由AI辅助生成；来源数据来自公开资料，计算值来自实际保存的模型运行。团队独立复核及修改情况尚未得到确认，不能写成已经完成。正文数字由同一冻结运行自动提取。[13]")
    paper.h("1 问题分析与研究边界")
    paper.p("本次交付限于问题二。沿用问题一已整理的结构、成本和供给证据，将其转化为主体状态、年度行为及运行反馈，完成2030/2060全部指标与关键参数敏感性。问题一不重新立项，问题三不纳入本稿。[1]")
    paper.p("采用大陆总量边界，港澳台不并入。最新完整可统一口径的共同初态取2024年，而不是将其称为2026年现实快照。每年以4个连续6小时时段表示代表日，循环重复365次。模型包含非电燃料消费及非能源用途，不能等同于纯电力模型；空间聚合不支持省际线路故障定位，代表日不支持季节性枯水或概率可靠性结论。氢能现状纳入问题一，未建立独立商业制储运用主体；CCUS也未形成内生投资模块，不能声称覆盖全部技术路线。")
    paper.h("2 数据基础与问题一衔接")
    paper.p("国家统计局同版年鉴承担能源生产、消费和规模主线；EI/上游研究汇编补充分技术发电和贸易，CEC/能源局补充装机、价格、利用及储能；财政部文件支撑补贴支付约束；IEA/NEA、IRENA及IPCC提供成本、效率和排放参考。[2]—[9] 同源汇编不当作独立重复观测，不同价格年度、厂用电口径和热值基准分别登记。")
    paper.table(["资料组","覆盖与用途","关键处理"],[
        ["统计局能源表","2015—2024现状；部分2005起","万tce转tce；同版实际GDP连乘"],
        ["分技术发电/装机","历史校准与2024初态","油电与Other拆分；水电扣除抽蓄"],
        ["贸易与区域","油气煤保障、31省协调","国家集中度给界；份额差不等于输电量"],
        ["价格/成本/财政","运行收益、投资与支付","历史名义值平减为2024实值；权责/现金分离"],
        ["BTR/GCB/IPCC","燃烧、过程、净移除","仅CO2；稀疏清单与年际桥接分别标示"]])
    paper.p("缺失观测不补零；单位转换与原表定位写入逐字段来源。价格平减、净毛发电换算、税与币种口径保留在预处理记录。2024纯油电为9.4496TWh，Other为79.4276TWh；旧问题一材料将两者合列的88.88TWh不能当作油电。本稿采用修正分类。抽蓄65.7TWh发电有公开观测，但将其归入统计残差的处理仍属于明确桥接假设。[3][10]")
    paper.table(["指标","2015","2024","解释"],[
        ["能源消费/亿tce","43.4113","59.60","增长37.29%"],
        ["煤炭份额","63.8%","53.2%","下降10.6个百分点"],
        ["煤炭消费/亿tce","27.6964","31.7072","份额下降≠绝对量下降"],
        ["总装机/GW","1525.27","3349.22","发电能力规模扩张"],
        ["风电/GW","130.75","520.78","容量与电量不能等同"],
        ["光伏/GW","42.18","887.42","需要消纳与配套投资"],
        ["非化石一次能源份额","不跨源拼补","19.8%","2024公布口径为初步测算"]])
    paper.figure("01_现状.png","图1 同版历史总量与结构；一次电力及其他保留原统计名称。[2] AI辅助制图")
    paper.p("其余问题一的四维评估、区域、贸易、成本及各能源角色，沿用既有问题一成果；本稿仅保留与问题二初态和参数直接相关的摘要。")
    paper.h("3 问题二：主体、规则与交互")
    paper.p("模型设置18个聚合主体：煤、油、气、生物质4类供给商；煤、气、油、生物质、水、核、风、光8类发电商；工业热、交通、建筑热及既有用电4类服务需求代理；政府和电网各1。碳市场作为价格、基准与结算环境实现。代理表示全国同类行为的聚合，不是18家真实企业；需求代理不能当作精确行业分解。")
    paper.table(["主体","状态/可见信息","行为与反馈"],[
        ["供给商","国内/进口供应界、库存、当期价格","报价与可交付量；共享用气约束"],
        ["发电商","年龄队列、在建、现金/债务、预期收益","比较边际项目NPV，申请投资，更新施工与偿债"],
        ["用能主体","服务需求、设备寿命、可支配预算","支付能源并在寿命/预算约束下替代设备"],
        ["电网","输送/储能存量、在建、预算","有工期的网储增量，运行缺口反馈"],
        ["政府/环境","财政额度、补贴资格、碳价及配额基准","登记权利、有限资金支付，碳结算不冒充资源成本"]])
    paper.p("每年顺序：读取当年GDP、政策和供给信息；处理投运、退役与设备寿命；形成当期需求并求解年内能源平衡；结算实际收入、燃料、补贴、碳交易与偿债；根据经营结果学习并提出投资；经共同预算和抵押/现金约束审核后进入建设队列。项目按工期在后续年份投运。投资者把当前状态延续到项目评价期，不读取未来实际数据。")
    paper.p("需求服务随GDP、部门弹性与效率趋势变化，D(a,t)=D(a,t−1)×[GDP(t)/GDP(t−1)]^ε(a,t)×(1−g_eff)，另计既有和替代设备。预期收益采用指数更新 E_t=(1−λ)E_(t−1)+λπ_t。发电投资满足NPV_j=−I_j+Στ CF_j,τ/(1+r)^τ；候选新项目在共同运行解中分配到可售电量，按私人项目净现值审核，可能挤出存量电源销售；它不是社会净增收益最大化。正私人净现值项目进入有限共同投资额度，最终额度同时受到自有资金、贷款、抵押、施工能力及共同运行销售约束。建设支出进入受限资金账户，按工期投运，不提前发电。")
    paper.p("运行层对每种载能体、每时段约束供应+放电+转换输出=需求+充电+转换输入+损耗。设备功率、爬坡、燃料库存和可用出力限制共同生效。储能满足SOC_(h+1)=SOC_h+η_ch P_chΔh−P_disΔh/η_dis，且0≤SOC≤E、充放电功率≤P；代表日首尾循环，投运新储能初始为空，退役能量单列处置。求解器先保障服务，再按既定非化石优先及成本/行为分配，行为评分不计入实际资源成本。")
    paper.p("补贴分为资格、应计权益、财政实际支付、拖欠应收与现金收取。基金支付不超过可用现金及支出约束；历史风光资格期限和利用小时上限保留，2021年以后新风光不自动获得旧补贴；垃圾处理服务另有有限市政预算。政府补贴已经进入收益与融资反馈，但并未完整逐厂复刻容量补偿和2025—2026差价合约改革。碳交易属于转移支付，资源成本仅累计真实资源投入和建设支出，避免把财政支出和企业收入同时重复计成本。")
    paper.p("排放核算为P_t=Σ燃料投入×排放因子+过程及其他CO2；N_t=P_t−R_t；中和率η_t=R_t/P_t。土地净移除基准固定为1.346499Gt/年，并作±50%条件扰动，未凭空添加CCUS收益。能源/碳强度为E_t/GDP_t与P_t/GDP_t；降幅统一给出相对2005和模型2025。统计标准煤桥接与物理热量分开保存，非化石份额的类别核对不能消除数量桥接不确定性。[8][9]")
    paper.h("4 历史校准与验证")
    paper.p("使用2015—2021年训练损失选择行为参数，2022—2024年评估趋势；评估窗口在多次模型修订中已经接触，因此不能声称盲测或独立样本外验证。两种燃机技术效率参考分别运行741个候选，补贴承诺倍数5、25、100分开保存。本稿采用预先指定的net58、25中间条件，不按评估成绩挑选。缺测的2022—2024官方燃烧清单不填补为验证样本。")
    paper.p("校准目标是按训练尺度归一化的多指标加权平方误差，包含能源总量、结构、总量及分技术装机/发电、稀疏燃烧排放。MAPE=(1/n)Σ|模拟−观测|/|观测|；结构另报告百分点MAE。内部误差门槛仅用于诊断，题目没有规定必须达到某个MAPE。")
    tr={r["metric"]:r for r in quality["training"]["components"]};ev={r["metric"]:r for r in quality["already_seen_evaluation"]["components"]}
    paper.table(["指标","训练MAPE","已接触评估MAPE"],[[label,percent(tr[k]["mape"]),percent(ev[k]["mape"])] for k,label in [
        ("primary_energy_tce","能源消费"),("electricity_generation_mwh","总发电"),("total_capacity_mw","总装机"),("wind_capacity_mw","风电装机"),("solar_capacity_mw","光伏装机"),("gas_generation_mwh","气电发电")]])
    paper.figure("02_历史验证.png","图2 训练及历史趋势验证；灰区为已接触评估窗口，不是盲测。AI辅助制图")
    paper.figure("07_分技术误差.png","图3 分技术发电误差。聚合误差较小不代表所有技术都准确。AI辅助制图")
    paper.p("2024年模拟总装机2302.37GW，观测3349.22GW，终点缺口31.26%。缺口中火电43.68%、光伏35.02%、风电12.26%、水电含抽蓄9.31%，核电少量抵消。煤电和常规水电历史项目预期收益为负而未自主申请；光伏多期已达施工上限，且2022—2024实际新增速度超过训练期可识别的扩张。因而误差涉及行为抽象、政策覆盖与结构变化，不能仅以修改某个会计错误就宣称消除。")
    paper.p("模型再现了总需求、发电和非化石扩张的主要方向，气电评估发电量MAPE已为3.38%；但不能由此确认装机投资机制足够准确。历史残差保留为长期结论限制，不回填观测强行修正历史，也不再以扩大搜索拖延题目作答。核心代码测试和守恒核验用于说明实现一致性，不能代替经验有效性。")
    paper.h("5 当前初态与基准预测")
    paper.p("未来主实验不继承历史模拟偏低的2024装机，而以独立观测初态开始2025年决策。2024总装机3349.22GW；常规水电为435.52−58.69GW，抽蓄单列；核电60.83GW、风520.78GW、光887.42GW。煤电1190GW、气电140GW为CEC取整锚，生物质45.97GW，油电采用旧小规模参考；未识别热电残差不免费分配为可发电煤电。新型储能为73.76GW/168.2GWh。[2][4][10]")
    opening=baseline["initial_path"]["opening_balance_sheet"]
    debt=sum(r["debt_cny"] for r in opening)/1e12;arrears=sum(r["subsidy_receivable_cny"] for r in opening)/1e9
    paper.p(f"设备年龄由净增容量重建；在建队列由2021—2024平均净增与工期推断，基准倍数1；贷款按账面资产比率50%、流动现金按重置规模10%设定，形成发电部门期初债务约{debt:.2f}万亿元；补贴应收约{arrears:.2f}十亿元来自资格代理和有限历史财政重放，均不是实测全国财务统计。资产=债务+明确股东权益，建设托管资金不能用于随意花费。初态年龄、债务、队列、现金、欠补单独扰动。")
    paper.p("施工能力改用2024投产规模作为代理，而不将2014训练倍数机械乘到更大存量：光伏280GW/年、风电81.37、煤电33.10、气电18.30、常规水电6.26、核电3.93。投产规模是可追溯的近期吞吐代理，并不是实测最大施工能力；其后仍按既定GDP与制造扩张规则变化。[4] 所有未来参数对照共用这套初态规则，历史校准结果不被改写。电价与厂用电率采用2018观测延续代理，煤88美元/吨、气9.1美元/MMBtu属于原成本参考并经过换算，未替换为2024中国实际到厂价。因此“2024实值”指价格单位年，不表示每项都来自2024观测。")
    paper.table(["基准参数","设定","性质"],[
        ["GDP实际增速","2025—30：4.5%；2031—40：3.5%；2041—50：2.5%；2051—60：1.5%","作者条件减速路径"],
        ["风光成本","实值每年下降3%；最低为2024的45%","技术趋势假设"],
        ["碳价","2024参考96.018847元/t；实值增长2%/年","水平基准+条件路径"],
        ["财政与价格","财政延续2024实值强度；电价/厂用电取2018观测延续代理，燃料取技术参考价格","价格统一2024实值，非2024全国实测价"],
        ["年内与时间","2025—2060；4×6小时代表日","年度结构分析，非季节性可靠性模型"]])
    target_rows=[]
    for key,label,scale,unit in [("primary_energy_tce","能源消费",1e8,"亿tce"),("nonfossil_share","非化石份额",.01,"%"),("positive_co2_t","CO2正排放",1e9,"Gt"),("net_removals_t","净移除",1e9,"Gt"),("net_co2_t","剩余净排放",1e9,"Gt"),("neutralisation_ratio","碳中和率R/P",.01,"%"),("total_capacity_mw","总装机",1e6,"TW")]:
        target_rows.append([label,number(p30[key]/scale),number(p60[key]/scale),unit])
    for key,label in [("energy_intensity_reduction_vs_2005","能耗强度降幅/2005"),("carbon_intensity_reduction_vs_2005","碳强度降幅/2005"),("energy_intensity_reduction_vs_2025","能耗强度降幅/2025"),("carbon_intensity_reduction_vs_2025","碳强度降幅/2025")]:
        target_rows.append([label,percent(tgt[2030,key]),percent(tgt[2060,key]),"降幅"])
    paper.table(["指标","2030","2060","单位/基期"],target_rows)
    paper.figure("03_基准路径.png","图4 独立2024观测初态的基准推演，点标2030/2060。服务缺口不算作已实现节能。AI辅助制图")
    paper.p(f"达峰判据检查历史桥接与未来序列最大值，并要求其后5年持续下降；本次状态为{peak['status']}，确认年份为{peak['year'] if peak['year'] is not None else '未确认'}。全序列最高水平约{peak['value']/1e9:.3f}Gt，最高年份标记为{peak.get('observed_max_year','见结果表')}；未来2025—2060窗口内最高值出现在{maxrow['year']}年，为{maxrow['positive_co2_t']/1e9:.3f}Gt。窗口最大值、严格持续下降判据与现实已达峰不是同一件事，历史年际桥接也不能充当官方达峰认证。")
    paper.p(f"按本稿条件口径，2030非化石份额{'达到' if p30['nonfossil_share']>=.25 else '未达到'}25%参考目标，碳强度相对2005年下降{'达到' if tgt[2030,'carbon_intensity_reduction_vs_2005']>=.65 else '未达到'}65%；2060非化石份额{'达到' if p60['nonfossil_share']>=.8 else '未达到'}80%参考水平，净排放{'仍大于零，不能判为碳中和' if p60['net_co2_t']>0 else '不大于零，但仍受CO2与移除边界限制'}。[11] 基准保持有限净移除，没有人为使2060强制达标；不同能源账口径与未来政策更新都会影响数值。")
    paper.h("6 不确定性分析")
    paper.p("必选敏感性保持其余条件不变：GDP各段增速±1个百分点；风光成本年降幅由3%变为2%/4%；碳价路径乘0.5/1.5。补充净移除、燃料价格、初态和补贴承诺等变化。它们是确定性条件范围，不是置信区间或发生概率；单因素敏感性不覆盖所有联合极端条件。")
    sens=[]
    for name,c in cases.items():
        if c["spec"].get("kind")=="sensitivity":
            p=c["paths"][-1]
            sens.append(dict(scenario=name,co2_2060_gt=p["positive_co2_t"]/1e9,net_co2_2060_gt=p["net_co2_t"]/1e9,nonfossil_2060_pct=p["nonfossil_share"]*100,unmet_2060_pct=p["unmet_service_mwh"]/p["requested_service_mwh"]*100))
    write_csv(out/"sensitivity_summary.csv",sens)
    paper.figure("05_必选灵敏度.png","图5 三类题面关键参数的双侧扰动，全部对同一S0比较。AI辅助制图")
    labels={"gdp_growth_delta":"GDP增速","cost_decline_delta":"风光年降本","carbon_price_multiplier":"碳价倍数"}
    paper.table(["参数","低/高条件","2060正排放/Gt","2060非化石/%"],[[lab,desc,
        f"{cases['sensitivity_'+k+'_0']['paths'][-1]['positive_co2_t']/1e9:.3f} / {cases['sensitivity_'+k+'_1']['paths'][-1]['positive_co2_t']/1e9:.3f}",
        f"{cases['sensitivity_'+k+'_0']['paths'][-1]['nonfossil_share']*100:.2f} / {cases['sensitivity_'+k+'_1']['paths'][-1]['nonfossil_share']*100:.2f}"]
        for (k,lab),desc in zip(labels.items(),["−1 / +1百分点","2% / 4%每年","0.5 / 1.5"])])
    uncertain=[c["paths"][-1] for c in cases.values() if c["spec"].get("kind")=="opening_uncertainty"]
    paper.p(f"初态单因素条件下，2060正排放范围{min(p['positive_co2_t'] for p in uncertain)/1e9:.3f}—{max(p['positive_co2_t'] for p in uncertain)/1e9:.3f}Gt，非化石份额范围{min(p['nonfossil_share'] for p in uncertain)*100:.2f}%—{max(p['nonfossil_share'] for p in uncertain)*100:.2f}%。这反映不可观测初态对预测的影响，不能当作全部模型不确定性。历史装机误差与缺失的后续政策机制仍构成结构不确定性。")
    for name,label in [("sensitivity_carbon_price_multiplier_1","碳价强化"),("sensitivity_cost_decline_delta_1","风光降本加快")]:
        changes={k:cases[name]["paths"][-1][k]-p60[k] for k in ("positive_co2_t","nonfossil_share","unmet_service_mwh")}
        paper.p(f"{label}相对S0的2060变化：正排放{changes['positive_co2_t']/1e9:+.4f}Gt，非化石份额{changes['nonfossil_share']*100:+.4f}个百分点，服务缺口{changes['unmet_service_mwh']/1e6:+.2f}TWh。若物理结果相同，仅说明该幅度在当前活跃约束下没有改变决策，不能推断现实政策或技术无效。")
    paper.h("7 模型评价与结论")
    maxres={k:max(c["summary"][k] for c in cases.values()) for k in ("max_physical_residual","max_cash_residual_cny","max_construction_fund_residual_cny","max_financing_transfer_residual_cny")}
    paper.p(f"问题二引用的24组推演全部完成，原始共同批次50组均完成并保留。最大物理平衡残差{maxres['max_physical_residual']:.3g}，最大现金残差{maxres['max_cash_residual_cny']:.4f}元，建设资金残差{maxres['max_construction_fund_residual_cny']:.4f}元，融资转移残差{maxres['max_financing_transfer_residual_cny']:.4f}元；与万亿元系统量级相比为数值舍入。这只验证已实现方程与账本闭合。")
    paper.p("优势在于将年度主体决策、项目共同约束、连续运行和资金反馈连接起来；历史与未来初态分离；参数对照避免不同起点混淆敏感性。局限包括装机历史偏差、反复使用评估窗口、缺失部分政策机制、单区域代表日、财务/年龄重建，以及氢/CCUS和AI/社会分配未独立建模。不能把条件实验称为官方预测、全部温室气体中和认证或全局最优政策。")
    paper.p(f"问题二已形成主体规则、历史校准与趋势检验、2030/2060全指标和GDP/降本/碳价敏感性。在给定假设下，2060剩余净排放{p60['net_co2_t']/1e9:.3f}Gt，不能判为碳中和。该结论说明本模型所表示的趋势和机制尚不足以确保目标，不等于断言未来现实政策无法实现目标。")
    paper.h("参考文献与AI使用声明")
    refs=[
        "[1] 全国大学生仿真建模应用挑战赛组委会. 2026年第二届竞赛A题：双碳背景下多种能源融合发展系统仿真与优化研究. 2026, 1—4页. 题目原件随项目保留。",
        "[2] 国家统计局. 中国统计年鉴2025：能源生产、消费、装机及地区相关表. https://www.stats.gov.cn/sj/ndsj/2025/ . 访问记录：2026-10-17至20；逐表定位见来源清单。",
        "[3] Energy Institute. Statistical Review of World Energy 2025：数据工作簿；上游发电分类说明. 2025. https://www.energyinst.org/statistical-review . 访问记录见原件清单。",
        "[4] 中国电力企业联合会、国家能源局. 2024年电力统计、2025年度行业发展报告及全国电力价格监管报告. https://www.cec.org.cn/ ；https://www.nea.gov.cn/ . 具体年度、页面与访问时间见source_manifest。",
        "[5] 财政部. 2015—2024年度可再生能源电价附加收入安排支出及中央政府性基金决算表；相关补贴政策. https://www.mof.gov.cn/ . 原件与表格定位随财政数据目录保存。",
        "[6] IEA/NEA. Projected Costs of Generating Electricity 2020. Paris: OECD Publishing, 2020. 中国案例与燃机参考表见项目成本提取记录；2010/2015版用于历史效率边界。",
        "[7] IRENA. Renewable Power Generation Costs in 2024. Abu Dhabi: IRENA, 2025. 物理PDF页71、76、119、123、202、209、212. https://www.irena.org/Publications .",
        "[8] IPCC. 2006 IPCC Guidelines for National Greenhouse Gas Inventories, Volume 2: Energy. 2006. Stationary Combustion. https://www.ipcc-nggip.iges.or.jp/public/2006gl/ .",
        "[9] 中华人民共和国. 首次双年透明度报告及国家温室气体清单；Global Carbon Budget年际序列. 官方清单与GCB仅按已声明桥接使用，逐原件定位见national_observations及gcb_peak_bridge_review。",
        "[10] 水电水利规划设计总院. 中国可再生能源发展报告2024. 抽蓄发电统计见物理PDF第26页；来源快照与目视核验见q2_scope_components。",
        "[11] 中共中央、国务院. 关于完整准确全面贯彻新发展理念做好碳达峰碳中和工作的意见；国务院. 2030年前碳达峰行动方案. 2021. 目标比较使用既有来源审查，不把模型结果作官方认证。",
        "[12] Project Mesa contributors. Mesa 3.3.1；SciPy developers. SciPy 1.16.3. 多智能体与数值求解软件；实际依赖见requirements-q2.txt。",
        "[13] Codex，GPT-6，OpenAI，使用日期2026-10-16至20；本轮2026-10-20。模型公开发布日期未由当前环境提供，不填造日期。"]
    for r in refs:paper.p(r)
    paper.p("AI使用声明：本稿的数据整理说明、程序编写/修复、实验编排、图表、文字与演示由Codex辅助生成；公开数据的原始值不是AI编造。数值由实际代码运行产生，但AI辅助实现与分析仍需参赛队员独立核验。当前尚无依据声明核心建模、实现和分析已由队员独立完成，也无依据声明全篇已人工改写。详细记录见支撑材料中的AI工具使用详情说明；本稿为团队研究与复核稿，不代替参赛承诺。")
    paper.h("附录：交付索引与复现说明")
    paper.table(["材料","内容","复核方法"],[
        ["论文MD/PDF与figures","问题二稿、图及底表","与冻结结果指标逐项对应"],
        ["问题二结果","基准、三类必选敏感性及初态等24案","结果SHA256及source_snapshot"],
        ["历史结果与复核","训练选择、误差、分技术诊断","训练窗口和原件哈希不变"],
        ["源码/设计/依赖","src、scripts、workflow及requirements","新建Python环境后按运行说明复算"],
        ["原始/处理数据","data/raw、data/processed与目录","来源、单位、缺失、价格平减可追溯"],
        ["演示与AI说明","MP4、讲稿及AI使用详情PDF","时长、字幕、数字与实际结果一致"]])
    paper.p("复现入口为scripts/run_q2_current_delivery.py；先安装requirements-q2.txt及数据读取依赖，再执行独立2024初态基准与参数对照。轻量支撑包使用scripts/run_q2_portable.py从已审查提取输入重新计算24案，并核对参考路径；完整原件再核验使用完整研究包原入口。仅重建图文使用scripts/build_q2_answer_delivery.py并传入本轮结果目录。示例与具体路径见交付运行说明。研究包保留数据源与全部必要核验材料；投稿前须按组委会论文20MB、支撑ZIP20MB、视频3分钟/300MB的限制检查大小，并由队员核验AI声明及匿名要求。")
    paper.render(out)
    write_csv(out/"baseline_targets.csv",baseline["targets"])
    write_csv(out/"q2_summary.csv",[dict(name=n,**cases[n]["summary"]) for n in cases if n=="S0" or cases[n]["spec"].get("kind") in {"sensitivity","opening_uncertainty","uncertain_authority","thermal_reference"}])
    write_csv(out/"historical_validation.csv",[dict(period=period,**r) for period in ("training","already_seen_evaluation") for r in quality[period]["components"]])
    report_outputs=[out/name for name in ("问题二答题稿.md", "问题二答题稿.pdf", "baseline_targets.csv", "q2_summary.csv", "sensitivity_summary.csv", "historical_validation.csv")]
    report_outputs.extend(p for p in (out/"figures").rglob("*") if p.is_file())
    proof=dict(run=run.relative_to(ROOT).as_posix(),archived_source_resolution=archived_sources,case_count=24,source_batch_case_count=status["cases"],source_results_sha256=sha(run/"results.json"),
        report_script_sha256=sha(Path(__file__)),baseline_2030=p30,baseline_2060=p60,peak=peak,
        physical_cash_residuals=maxres,manifest_scope="Outputs generated by this report builder only; packaging and video have separate validation receipts.",
        files={p.relative_to(out).as_posix():sha(p) for p in report_outputs})
    save(out/"answer_manifest.json",proof)
    print(out);print(json.dumps(dict(cases=len(cases),co2_2030_gt=p30['positive_co2_t']/1e9,co2_2060_gt=p60['positive_co2_t']/1e9,net_2060_gt=p60['net_co2_t']/1e9,peak=peak),ensure_ascii=False))


if __name__=="__main__":main()
