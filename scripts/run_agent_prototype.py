"""Run synthetic mechanism comparisons, isolated from admitted observations."""
import json
import sys
from pathlib import Path

from workflow_status import read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.agents import simulate

CONFIG = "examples/synthetic_agents.json"


def summarize(run):
    rows = run["rows"]
    return {
        "cumulative_unserved_service_su": sum(s["unserved_service"] for row in rows for s in row["services"].values()),
        "cumulative_energy_related_emissions_abstract":
            sum(row["energy_related_synthetic_emissions"] for row in rows),
        "cumulative_equipment_investment_cu": sum(d["investment"] for row in rows
            for d in row["decisions"] if d["kind"] == "equipment_substitution"),
        "cumulative_generation_investment_cu": sum(d["investment"] for row in rows
            for d in row["decisions"] if d["kind"] == "generation_investment"),
        "last_step_capacity_units": rows[-1]["capacity_at_start"],
        "last_step_equipment_share_at_start":
            {name: values["electric_share"] for name, values in rows[-1]["services"].items()},
        "max_abs_balance_residual_eu": max(abs(residual)
            for row in rows for residual in row["balance_residuals"].values()),
        "pending_capacity_at_end_units": sum(
            project["capacity_units"] for projects in run["final_projects"].values()
            for project in projects if project["online_step"] > rows[-1]["step"]),
        "note": "仅合成EU/SU/CU及抽象排放；不对应中国物理量，不含全国过程排放和移除。",
    }


def build(root=ROOT):
    config = read_json(root / CONFIG)
    cases = {
        "full_feedback": simulate(config),
        "frozen_equipment": simulate(config, substitution=False),
        "frozen_generation_investment": simulate(config, investment=False),
    }
    summaries = {name: summarize(run) for name, run in cases.items()}
    output = root / "outputs/prototype"
    output.mkdir(parents=True, exist_ok=True)
    code_paths = ["src/energy_model/agents.py", "src/energy_model/accounting.py",
                  "scripts/run_agent_prototype.py"]
    result = {
        "mode": "synthetic", "warning": config["warning"], "config_path": CONFIG,
        "input_sha256": sha256(root / CONFIG),
        "implementation_sha256": {path: sha256(root / path) for path in code_paths},
        "summaries": summaries, "cases": cases,
        "validation_status": "program_mechanisms_only_not_historical_validation",
    }
    (output / "agent_runs.json").write_text(json.dumps(
        result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    labels = {"full_feedback": "完整反馈", "frozen_equipment": "冻结设备替代",
              "frozen_generation_investment": "冻结发电投资"}
    lines = [
        "# 主体决策原型：合成机制验证", "",
        "**全部数值为合成案例，不是中国观测、历史验证或2030/2060预测。**",
        "第1—8步代表抽象决策步；EU/SU/CU和排放均为抽象单位。参数来自examples/synthetic_agents.json，"
        "实际官方数据未接入此原型。",
        "", "## 已运行的交互", "",
        "工业和交通主体比较已观察到的电力/燃料服务成本，在预算、设备替代速度与回收期内决策；"
        "燃料供应者根据上一期利用率报价；运营者执行含碳成本排序和能力/网络约束调度；"
        "发电企业根据当期售电价和销售比例预期投资，建设滞后后投运。"
        "政府碳价是外生输入，不宣称碳市场内生出清。",
        "", "## 机制对照", "",
        "|机制|累计未满足服务（SU）|能源相关合成排放|设备投资（CU）|发电投资（CU）|最大守恒残差（EU）|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, summary in summaries.items():
        lines.append(f"|{labels[name]}|{summary['cumulative_unserved_service_su']:.4f}|"
                     f"{summary['cumulative_energy_related_emissions_abstract']:.4f}|"
                     f"{summary['cumulative_equipment_investment_cu']:.2f}|"
                     f"{summary['cumulative_generation_investment_cu']:.2f}|"
                     f"{summary['max_abs_balance_residual_eu']:.2e}|")
    lines += ["", "这是程序机制对照，不能计作赛题全国基准+至少三种正式情景。"
              "指标不能解释为现实政策收益；不同机制可能在缺能、排放和成本间产生不同方向的变化。",
              "", "## 完整反馈轨迹", "",
              "|步|工业电设备份额（期初）|交通电设备份额（期初）|合成可再生容量（期初）|交付电价（CU/EU）|未满足服务（SU）|",
              "|---|---:|---:|---:|---:|---:|"]
    for row in cases["full_feedback"]["rows"]:
        lines.append(f"|{row['step']}|{row['services']['industry']['electric_share']:.3f}|"
                     f"{row['services']['transport']['electric_share']:.3f}|"
                     f"{row['capacity_at_start']['renewable']:.2f}|"
                     f"{row['electricity_price_delivered']:.3f}|"
                     f"{sum(s['unserved_service'] for s in row['services'].values()):.4f}|")
    orders = [(row["step"], d) for row in cases["full_feedback"]["rows"]
              for d in row["decisions"] if d["kind"] == "generation_investment" and d["capacity_ordered"] > 0]
    if orders:
        step, order = orders[0]
        lines += ["", f"首个正投资发生在第{step}步，{order['actor']}企业订购"
                  f"{order['capacity_ordered']:.2f}容量单位，第{order['online_step']}步投运；"
                  "订购当步不增加可用容量。决策日志保留观察价格、成本、净现值、预算和信息截止步。"]
    lines += [
        "", f"期末仍在建的容量为{summaries['full_feedback']['pending_capacity_at_end_units']:.2f}抽象单位，"
        "已支出投资但未在第8步供能。未来现金流只是企业决策假设，不是期末之外的实际模拟产出。",
        "", "## 可见局限", "",
        "年度服务与报价顺序不做同一步均衡迭代，可能出现设备份额往返变化；"
        "预期销售下限是明确的合成乐观预期，未校准，可能过度投资。"
        "燃料直接用途优先、配给规则、外生预算均是研究实现假设。"
        "退役按寿命外生处理，无完整资产负债表；尚无氢、生物质、水核风光细分、储能或完整网络。",
        "另有operations/中的独立连续运行模块，细分水核风光煤气和储能；"
        "它尚未接入本年度主体投资反馈，不能称两个时间尺度已经耦合。",
        "只计算合成燃烧排放，没有全国工业过程、碳汇和中和率。"
        "不能把附件电站或单年统计直接填进配置后改称中国预测。",
        "", "## 下一步", "",
        "对真实模型先锁定单一历史版本和部门服务/设备输入，逐一替换有依据的参数并校准少量行为参数；"
        "增加煤直接终端、技术细分并与独立储能运行模块耦合，再连接附件代表项目已核验约束。"
        "历史结果在数据准入和验证完成后单独输出，不覆盖本合成报告。",
        "", "复现：run_prototype.ps1。完整轨迹、决策和配置/代码SHA256见agent_runs.json；"
        "实现契约及公式见docs/09_agent_prototype.md。"
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({"mode": result["mode"], "cases": list(result["cases"]),
                      "summary": result["summaries"]["full_feedback"]}, ensure_ascii=False))
