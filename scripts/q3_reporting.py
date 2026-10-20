"""Tables, figures and bounded interpretations derived only from Q3 outputs."""
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path

from run_q2_national import csv_write,dump


def read(path):
    with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def unpack(path):return json.loads(gzip.decompress(path.read_bytes()))


def bottlenecks(out):
    """Report co-binding constraints for unmet services; no unique cause claim."""
    result=[]
    for path in sorted((out/"cases").glob("policy_*.json.gz")):
        detail=unpack(path)
        if detail["outcome"]["status"]!="completed":continue
        by_year=defaultdict(list)
        for r in detail["operations"]:by_year[r["year"]].append(r)
        for year,records in by_year.items():
            op=detail.get("operation_specs",{}).get(str(year))
            if op is None:continue
            spent=defaultdict(float)
            for r in records:
                if r["kind"]=="demand":
                    d=op["demands"][r["device"]]
                    if "budget_group" in d:spent[d["budget_group"]]+=r["input_mwh"]*d["purchase_price_per_mwh"]
            for r in records:
                if r["kind"]!="demand" or r["unmet_service_mwh"]<=max(.001,1e-8*r["requested_service_mwh"]):continue
                i=r["period"];h=op["periods"][i]["hours"]
                d=op["demands"][r["device"]]
                cap=d["input_capacity_mw"]*h
                device=abs(r["input_mwh"]-cap)<=max(.001,cap*1e-7)
                group=d.get("budget_group")
                budget=(group is not None and spent[group]>=op["spending_limits"][group]["budget_cny"]*(1-1e-7))
                gridflow=sum(z["input_mwh"] for z in records if z["kind"]=="demand" and z["carrier"]=="electricity" and z["period"]==i)/op["grid"]["efficiency"]
                grid=r["carrier"]=="electricity" and gridflow>=op["grid"]["power_mw"]*h*(1-1e-7)
                generation=sum(z["output_mwh"] for z in records if z["kind"]=="generation" and z["period"]==i)
                power=sum(p["capacity_mw"]*p["availability"][i]*h for p in op["plants"].values())
                generation_bound=r["carrier"]=="electricity" and generation>=power*(1-1e-7)
                result.append(dict(policy_id=detail["label"]["policy_id"],year=year,period=i,sector=r["sector"],carrier=r["carrier"],
                    requested_service_mwh=r["requested_service_mwh"],unmet_service_mwh=r["unmet_service_mwh"],
                    device_capacity_binding=device,service_budget_binding=budget,grid_capacity_binding=grid,
                    generation_available_power_binding=generation_bound,
                    interpretation="co_binding_flags_not_unique_causal_proof; inspect full resource/stock budgets too"))
    csv_write(out/"policy_bottleneck_flags.csv",result)
    return result


def generate_report(out,config,completion):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    h01=read(out/"h01_results.csv")
    policies=read(out/"policy_results.csv")
    base=next(r for r in policies if r["policy_id"]=="none")
    lock=json.loads((out/"selection_lock.json").read_text(encoding="utf-8"))
    checks={r["policy_id"]:r for r in lock["policy"]["records"]}
    diagnostic=bottlenecks(out)
    candidates=[]
    for candidate in config["policy"]["candidates"]:
        detail=unpack(out/"cases"/("policy_"+candidate["id"]+".json.gz"))
        row=next(r for r in policies if r["policy_id"]==candidate["id"])
        projects=detail["policy_projects"]
        candidates.append(dict(id=candidate["id"],rule=candidate["rule"],actions=";".join(candidate["actions"]),
            payer="additional_public_appropriation",executors="generation_maintenance_or_grid_storage_gas_operators",
            appropriation_fraction_gdp=config["transition"]["public_budget_fraction_gdp"],
            permit_identity="conditional_research_authorisation_not_observed_permit",
            capital_projects=len(projects),actual_capital_commitment_cny=sum(p["cost"] for p in projects),
            first_commissioning_year=min((p["online"] for p in projects),default=None),
            retained_capacity_years_mw=sum(d["capacity_mw"] for d in detail["decisions"] if d["decision"].startswith("retain_")),
            **checks.get(candidate["id"],{})))
    csv_write(out/"policy_candidates.csv",candidates)
    tradeoffs=json.loads((out/"policy_tradeoffs.json").read_text(encoding="utf-8"))
    csv_write(out/"policy_tradeoffs.csv",[dict(carbon_ratio=t["carbon_ratio"],cost_ratio=t["cost_ratio"],
        designated=t["carbon_ratio"]==config["policy"]["carbon_limit_ratio"] and t["cost_ratio"]==config["policy"]["gross_cost_limit_ratio"],
        selected=t["selected"],status=t["reason"],feasible=";".join(t["feasible"]),pareto=";".join(t["pareto"])) for t in tradeoffs["alternative_bounds"]])
    # Each H01 cell is checked against its own fixed-schedule comparator.
    feasibility=[]
    for row in h01:
        ref=next(r for r in h01 if r["mode"]==row["mode"] and r["vR"]==row["vR"] and r["vE"]==row["vE"] and r["delay"]==row["delay"] and r["rule"]=="fixed_schedule")
        reasons=[]
        if row["status"]!="completed" or ref["status"]!="completed":reasons.append("simulation_or_fixed_plan_failed")
        else:
            if float(row["cumulative_combustion_co2_t"])>float(ref["cumulative_combustion_co2_t"])*config["policy"]["carbon_limit_ratio"]+1e-5:reasons.append("carbon")
            if float(row["discounted_resource_cost_cny"])>float(ref["discounted_resource_cost_cny"])*config["policy"]["gross_cost_limit_ratio"]+.01:reasons.append("cost")
            if max(float(row["worst_annual_service_fraction"]),float(row["worst_selection_service_fraction"]))>config["policy"]["service_limit"]+1e-10:reasons.append("service_selection")
        test_pass=row["status"]=="completed" and float(row["worst_test_service_fraction"])<=config["policy"]["service_limit"]+1e-10
        feasibility.append(dict(id=row["id"],feasible_selection=not reasons,violations=";".join(reasons),test_service_passed=test_pass))
    csv_write(out/"h01_feasibility.csv",feasibility)
    sensitivity=read(out/"sensitivity_results.csv")
    csv_write(out/"sensitivity.csv",[dict(**r,scope="single_factor_all_fixed_policy_candidates_no_test_retuning") for r in sensitivity])
    recommendations=[]
    groups=[("能源结构","retain","在原技术寿命内支付保留费用并延后提前退出；2060硬截止", "没有新增延寿许可，也不代表所有煤电退出政策"),
            ("多能调度","grid_storage","申请网侧交付能力与储能项目，按共同预算分配并经历工期", "全国单节点，不能识别跨省线路或区域拥塞；无额外需求响应"),
            ("储备应急","gas_release","付费建设气体注采能力，库存、库容和进口来源总量不变", "注采成本与能力是条件假设；无新增免费燃料或来源分散承诺"),
            ("市场机制","retain","以有公共资金的容量保留合同支付运维服务", "仅检验这一合同；未识别全市场价格、需求响应或税收收入"),
            ("科技应用","storage","在继承成本、效率和寿命下付费部署储能", "ST降本属于外部技术条件，不作为政府免费选择的技术突破；氢和CCUS无准入初态")]
    for category,pid,action,limit in groups:
        row=next(r for r in policies if r["policy_id"]==pid)
        candidate=next(r for r in candidates if r["id"]==pid)
        valid=row["status"]=="completed" and base["status"]=="completed"
        recommendations.append(dict(dimension=category,candidate=pid,action=action,
            evidence="policy_results.csv; cases/policy_"+pid+".json.gz; transition_event_metrics.csv",
            payer="公共额外拨款，全部资本承诺先占预算，保留及维护同受上限约束",executor=candidate["executors"],
            first_online_year=candidate["first_commissioning_year"],capital_commitment_cny=candidate["actual_capital_commitment_cny"],
            baseline_unmet_records=sum(1 for z in diagnostic if z["policy_id"]=="none"),
            baseline_device_bound_records=sum(z["device_capacity_binding"] for z in diagnostic if z["policy_id"]=="none"),
            baseline_budget_bound_records=sum(z["service_budget_binding"] for z in diagnostic if z["policy_id"]=="none"),
            baseline_grid_bound_records=sum(z["grid_capacity_binding"] for z in diagnostic if z["policy_id"]=="none"),
            delta_net_resource_cost_cny=float(row["net_resource_cost_cny"])-float(base["net_resource_cost_cny"]) if valid else None,
            delta_cumulative_co2_t=float(row["cumulative_combustion_co2_t"])-float(base["cumulative_combustion_co2_t"]) if valid else None,
            delta_selection_worst_fraction=float(row["worst_selection_service_fraction"])-float(base["worst_selection_service_fraction"]) if valid else None,
            delta_test_worst_fraction=float(row["worst_test_service_fraction"])-float(base["worst_test_service_fraction"]) if valid else None,
            admissible=checks[pid]["feasible"],failed_constraints=checks[pid]["violations"],limitation=limit,
            conclusion="仅在通过共同约束且对应服务改善时支持此范围内采用；否则保留为无效或不可行证据"))
    csv_write(out/"policy_recommendations.csv",recommendations)
    figures=out/"figures";figures.mkdir(exist_ok=True)
    plt.rcParams.update({"figure.dpi":130,"font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    fig,axes=plt.subplots(1,2,figsize=(13,4.8),constrained_layout=True)
    rules=[("fixed_schedule",.01),("cost_order",.01),("service_ready",.01),("anticipatory",.005),("anticipatory",.01)]
    for ax,mode in zip(axes,("full_response","fixed_projects")):
        rows=[r for r in h01 if r["mode"]==mode]
        cells=list(dict.fromkeys((r["vR"],r["vE"],r["delay"]) for r in rows))
        values=np.full((len(cells),len(rules)),np.nan)
        for i,cell in enumerate(cells):
            for j,(rule,eps) in enumerate(rules):
                item=next(r for r in rows if (r["vR"],r["vE"],r["delay"])==cell and r["rule"]==rule and float(r["epsilon"])==eps)
                if item["status"]=="completed":values[i,j]=100*float(item["worst_test_service_fraction"])
        im=ax.imshow(values,cmap="magma_r",vmin=0,aspect="auto")
        ax.set_title(mode.replace("_"," "))
        ax.set_yticks(range(len(cells)),[f"vR={a}, vE={b}, L={c}" for a,b,c in cells])
        ax.set_xticks(range(5),["schedule","cost","ready","ahead .005","ahead .01"],rotation=25,ha="right")
        for i in range(len(cells)):
            for j in range(5):ax.text(j,i,"failed" if np.isnan(values[i,j]) else f"{values[i,j]:.2f}",ha="center",va="center",color="white" if values[i,j]>max(.01,np.nanmax(values)*.6) else "black",fontsize=8)
        fig.colorbar(im,ax=ax,label="Worst test service shortage (%)")
    fig.suptitle("H01: both grids, unchanged deeper test condition; no probability interpretation")
    fig.savefig(figures/"h01_test_grid.png");plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,5),constrained_layout=True)
    for row in policies:
        if row["status"]!="completed":continue
        pid=row["policy_id"]
        x=float(row["net_resource_cost_cny"])/1e12;y=float(row["cumulative_combustion_co2_t"])/1e9
        marker="o" if checks[pid]["feasible"] else "x"
        ax.scatter(x,y,marker=marker,s=60)
        ax.annotate(pid,(x,y),xytext=(5,4),textcoords="offset points",fontsize=8)
    ax.set(xlabel="Discounted resource cost minus terminal assets (trillion CNY 2024)",ylabel="2025–2060 combustion CO2 (Gt)",title="Finite policy choices: circle=feasible, cross=constraint failure")
    fig.savefig(figures/"policy_cost_emissions.png");plt.close(fig)
    event_data=unpack(out/"events/policy_none-test.json.gz")
    event=next(e for e in event_data if e["year"]==2030 and e["scenario"]=="SGW")
    x=[r["end_hour"] for r in event["calendar"]]
    fig,axes=plt.subplots(2,1,figsize=(9,5),sharex=True,constrained_layout=True)
    gas=[r for r in event["result"]["fuel"] if r["fuel"]=="gas"]
    axes[0].plot(x,[r["closing_mwh"]/1e6 for r in gas],label="Gas stock (TWh thermal)")
    axes[0].set_ylabel("TWh thermal");axes[0].legend()
    axes[1].plot(x,[r["closing_mwh"]/1e3 for r in event["result"]["storage"]],label="Battery SOC (GWh)",color="#ab5a00")
    axes[1].set(xlabel="Elapsed hours (6-hour resolution)",ylabel="GWh");axes[1].legend()
    fig.suptitle("2030 SGW deeper test: continuous stocks, same terminal boundaries")
    fig.savefig(figures/"event_stocks.png");plt.close(fig)
    result=dict(five_dimensions=len(recommendations),h01_feasible=sum(r["feasible_selection"] for r in feasibility),
        h01_test_service_passed=sum(r["test_service_passed"] for r in feasibility),
        selected_policy=completion["selected_policy"],policy_status=completion["designated_policy_status"],
        figures=[p.relative_to(out).as_posix() for p in sorted(figures.glob("*.png"))])
    dump(out/"report_summary.json",result)
    text="# 问题三：转型配套与受约束政策结果\n\n"
    text+=f"已执行 {completion['annual_runs']} 个年度模型案例：H01 为 {completion['h01_cases']} 个，政策单项及组合 {completion['policy_cases']} 个，单因素政策比较 {completion['sensitivity_cases']} 个。工程自查和 C9 团队批准独立记录，不能由运行成功替代。\n\n"
    text+="## 同口径与信息边界\n\n从共同2024初态运行到2060。H01的 vR 只调整初始煤电资产在寿命前5年内的提前退出授权，vE 是满足成本条件的到期更新/扩建设备采用份额，L 只增加网、储及注采设施工期。保留资产支付费用，最迟在原技术寿命或2060退出。单节点模型不输出地区拥塞或全年可靠性概率。\n\n固定项目实验只回放固定日程对照已批准的申请，并在原决策年公开；资金不够即标失败。完整主体实验允许投资不同，不能把总效果都归于时序。费用排序可能因聚合煤电同质而与固定日程相同，不捏造逐厂成本差异。\n\n预测使用当前资产、已承诺队列及预先冻结的压力平台条件；未承诺的未来项目不预支。实际安全评价使用连续事件。选择记录在执行较深检验前锁定；较深条件此前已接触，仍不是盲测。\n\n"
    text+=f"## H01\n\n共同选择约束下可行 {result['h01_feasible']}/{len(h01)}；检验集服务界内 {result['h01_test_service_passed']}/{len(h01)}。后者只表示服务一项通过，不等于成本/排放/工程共同可行。逐点成本、排放、末期资产与各规则差分见 h01_results.csv、h01_comparisons.csv、h01_feasibility.csv。\n\n![H01](figures/h01_test_grid.png)\n\n"
    text+=f"## 政策筛选\n\n主约束：相对同一转型参数下的无额外政策对照，累计燃烧CO₂不增加、折现毛资源成本不高于1.05倍、每个服务的缺供比例不超过1%，额外公共拨款每年不超过GDP的0.0005。预算是相同上限，不强制各方案花完同额资金。结果：**{completion['designated_policy_status']}**；选定策略：**{completion['selected_policy']}**。无可行解时不以替代边界冒充通过。\n\n"
    text+="有限政策集合不等于全局优化。净费用扣除期末残值，同时公开毛成本、保留费用、维护费、资本承诺和实际付款；金融转移不重复算资源成本。policy_tradeoffs.csv 的其他界值只用于取舍敏感性。\n\n![政策取舍](figures/policy_cost_emissions.png)\n\n"
    base_flags=[z for z in diagnostic if z["policy_id"]=="none"]
    text+=f"无额外政策对照共有 {len(base_flags)} 条代表时段服务缺供记录；其中设备能力、服务主体付款预算、电网交付能力分别同时达到边界的记录数为 {sum(z['device_capacity_binding'] for z in base_flags)}、{sum(z['service_budget_binding'] for z in base_flags)}、{sum(z['grid_capacity_binding'] for z in base_flags)}。这些是同时约束的诊断标记，不是互斥归因；不能把设备/资金限制直接称为气源不足。逐条见 policy_bottleneck_flags.csv。\n\n"
    text+="| 五方面 | 已执行的动作 | 相对对照净成本变化（万亿元） | 检验最坏缺供比例变化（百分点） | 主约束 |\n|---|---|---:|---:|---|\n"
    for r in recommendations:
        cost="失败" if r["delta_net_resource_cost_cny"] is None else f"{r['delta_net_resource_cost_cny']/1e12:.4f}"
        safety="失败" if r["delta_test_worst_fraction"] is None else f"{100*r['delta_test_worst_fraction']:.4f}"
        text+=f"| {r['dimension']} | {r['candidate']} | {cost} | {safety} | {'通过' if r['admissible'] else r['failed_constraints']} |\n"
    text+="\n每项建议的执行者、付款者、投入、首年投运、证据与失效限制见 policy_recommendations.csv。气体注采能力只提高已有库存的出入速率，不增加库容、进口来源或初始储量；其费用是假设，已做半倍/双倍敏感性。储能部署使用继承的技术水平，ST外部降本不是可免费选择的政府动作。氢、CCUS、居民和就业缺乏本轮准入输入，不虚构其效果。\n\n"
    text+="## 稳健性和失败\n\n六个单因素变体各自重跑八项政策，保留/维护约束、供给、初态和需求不随排名改变。选择后评价检验集，排序记录见 sensitivity_rankings.csv；全部原始点见 sensitivity.csv。无效政策、无可行解、固定项目融资失败与求解失败分别保留，不能把失败填成零损失。\n\n![连续库存](figures/event_stocks.png)\n\n"
    text+="代码与配置是条件研究实现。Q2的聚合重建、价格/融资/初始队列假设、已接触历史评估、缺同口径CO₂留出及气油生物质残差继续有效；本轮不重标为已解决。完整审查证据在 outputs/validation/p3_mmj，团队批准需另外两人对同一最终SHA给出。\n"
    (out/"transition_report.md").write_text(text,encoding="utf-8")
    return result
