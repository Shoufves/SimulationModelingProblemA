"""Reproducible chronological synthetic operation comparisons, separate from observations."""
import json
import sys
from pathlib import Path

from workflow_status import read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.operations import simulate_operation_window, summarize_operation_window

CONFIG = "examples/synthetic_operation_windows.json"


def build(root=ROOT):
    config = read_json(root / CONFIG)
    cases = {}
    for window_name in config["windows"]:
        comparisons = {}
        for label, enabled in (("with_storage", True), ("without_storage", False)):
            run = simulate_operation_window(config, window_name, storage_enabled=enabled)
            comparisons[label] = {"summary": summarize_operation_window(run), "run": run}
        cases[window_name] = comparisons
    paths = ["src/energy_model/operations.py", "src/energy_model/accounting.py",
             "src/energy_model/agents.py", "scripts/run_operation_windows.py"]
    result = {
        "mode": "synthetic", "warning": config["warning"], "config_path": CONFIG,
        "input_sha256": sha256(root / CONFIG),
        "implementation_sha256": {path: sha256(root / path) for path in paths},
        "cases": cases, "validation_status": "program_windows_only_not_historical_or_annual_validation",
    }
    out = root / "outputs/prototype/operations"
    out.mkdir(parents=True, exist_ok=True)
    (out / "window_runs.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# 连续运行窗口：储能机制对照", "",
        "**全部参数和结果为合成；不是中国观测、全国预测、历史验证或全年停电风险。**",
        "水核风光煤气分别调度；时段按实际小时长度连续推进SOC。"
        "储能位于发电侧，只充当前富余的非燃烧出力，缺口时先于煤气放电。"
        "调度不读取未来出力或负荷，不保证全窗口经济最优。", "",
        "|合成窗口|机制|窗口小时|缺供MWh|受影响小时|最大缺供MW|弃用非燃烧电量MWh|合成燃烧排放|运行变动成本CU|期末SOC MWh|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"with_storage": "有储能", "without_storage": "无储能"}
    names = {"normal_variability": "常规波动", "persistent_low_wind_solar": "持续低风光",
             "grid_bottleneck": "送出受限"}
    for name, comparisons in cases.items():
        for label, case in comparisons.items():
            s = case["summary"]
            lines.append(
                f"|{names.get(name, name)}|{labels[label]}|{s['window_hours']:.2f}|"
                f"{s['unserved_mwh']:.4f}|{s['shortage_hours']:.2f}|{s['max_shortage_mw']:.4f}|"
                f"{s['unused_noncombustion_mwh']:.4f}|{s['energy_related_synthetic_emissions']:.4f}|"
                f"{s['resource_variable_cost_cu']:.4f}|{s['closing_storage_mwh']:.4f}|"
            )
    maximum = max(c["summary"]["max_abs_balance_residual_mwh"]
                  for comparisons in cases.values() for c in comparisons.values())
    normal = cases["normal_variability"]
    reduction = normal["without_storage"]["summary"]["unserved_mwh"] - normal["with_storage"]["summary"]["unserved_mwh"]
    lines += [
        "", "## 可以从本例得出的机制结论", "",
        f"- 常规波动窗口中，有储能相对无储能减少缺供{reduction:.4f} MWh；"
        "这只说明本配置的富余能量可转移至后续时段，不能解释为现实政策收益。",
        "- 持续低风光窗口从空储能开始且没有富余能量，储能不能凭空供电。",
        "- 送出受限窗口中，发电侧储能仍受线路上限限制；期末SOC可能留存，不能将其算作已供负荷。",
        f"- 六次运行的最大账本守恒残差为{maximum:.3e} MWh。放电不计入新非燃烧发电，燃烧排放只计一次。",
        "", "## 边界与后续", "",
        "所有对照从0 MWh期初SOC开始；逐窗口分别运行，窗口内不重置SOC。"
        "期末库存按实际输出，不伪造循环边界或免费补能。"
        "弃用非燃烧电量包含可调水核的未用能力，不能称为官方弃风弃光率。",
        "运行变动成本不含储能和电源资本/固定成本、缺供损失；碳支付另列于JSON，"
        "不能据此判断完整经济性，也不能将支付与资源成本混为一谈。",
        "仅评估所列连续窗口，不加年权重，不生成全年EENS、LOLP或停电概率。"
        "水电无水库约束、核电无最小出力和爬坡；氢、生物质、真实天气与网络尚未实现。"
        "该模块尚未与年度主体投资耦合，真实参数与历史验证仍需单独准入和校准。",
        "", "复现：run_prototype.ps1。原始合成配置在examples/synthetic_operation_windows.json，"
        "逐时轨迹和配置/代码SHA256在window_runs.json，实现边界见docs/10_operation_windows.md。",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({
        "mode": result["mode"],
        "window_summaries": {
            name: {label: case["summary"] for label, case in comparisons.items()}
            for name, comparisons in result["cases"].items()
        },
    }, ensure_ascii=False))
