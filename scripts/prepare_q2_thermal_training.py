"""Create versioned search runners/designs without changing frozen prior code."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / "scripts/run_q2_corrected_recalibration.py").read_text("utf-8")
    replacements = {
        "from q2_corrected_factory import build": "from q2_thermal_configured_factory import build\nfrom q2_thermal_factory import verify_history",
        'default="workflow/q2_corrected_recalibration.json"': 'default="workflow/q2_thermal_net58_recalibration.json"',
        '    hashes = {p: sha(p) for p in sorted(sources)}': '''    if config.get("model_factory") != "q2_thermal_configured_factory:build" or config.get("thermal_mode") not in {"net55", "net58"}:
        raise ValueError("Thermal mechanism must be fixed before training")
    sources.update(verify_history())
    sources.update({"scripts/q2_thermal_configured_factory.py", "scripts/q2_thermal_factory.py",
        "scripts/q2_fuel_price_factory.py", "src/energy_model/q2_thermal_vintages.py",
        "src/energy_model/q2_fuel_prices.py", "docs/sources/q2_thermal_vintages.md",
        "scripts/prepare_q2_thermal_training.py"})
    hashes = {p: sha(p) for p in sorted(sources)}''',
        '                    training_components=training_loss(m)[1])': '                    thermal_fuel_ledger=m.thermal_fuel_ledger, year_end_operation=m.year_end_operation(),\n                    training_components=training_loss(m)[1])',
        '补贴期限与独立投资审核修正后的联合训练': '新老煤气技术分离后的联合训练',
        '修正已知适用光伏资格期限与投资连带收缩；目标权重和误差门槛保持不变；2015—2021选参，2022—2024已接触评估。': '使用设计中预先固定的新机效率参照；目标权重和误差门槛保持不变；2015—2021选参，2022—2024已接触评估。',
        '三种未知承诺额度分别训练并全部报告；不按评估选择财政制度。有限搜索不证明全局最优。': '三种未知承诺额度分别训练并全部报告；两种效率参照各自完整运行，不按评估选择财政制度或效率。有限搜索不证明全局最优。',
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise ValueError("Unexpected source runner: " + old)
        source = source.replace(old, new)
    target = ROOT / "scripts/run_q2_thermal_recalibration.py"
    if target.exists():
        raise ValueError("Do not overwrite an existing versioned runner")
    target.write_text(source, "utf-8")
    base = json.loads((ROOT / "workflow/q2_corrected_recalibration.json").read_text("utf-8"))
    original = json.loads((ROOT / "workflow/q2_national_design.json").read_text("utf-8"))
    for mode in ("net55", "net58"):
        config = json.loads(json.dumps(base))
        config.update(model_factory="q2_thermal_configured_factory:build", thermal_mode=mode,
            warm_start_run="outputs/q2_revenue_recalibration/20261019T225922280430Z",
            design_rationale="Separate inherited/new thermal efficiency in physical and profit accounts; repeat prior training blocks, then the original declared expectation/investment grid. Do not select technical assumptions using evaluation.")
        config["blocks"].append({key: original["parameter_grid"][key]
                                  for key in ("expectation_rate", "investment_response")})
        path = ROOT / f"workflow/q2_thermal_{mode}_recalibration.json"
        if path.exists():
            raise ValueError("Do not overwrite an existing design")
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+"\n", "utf-8")


if __name__ == "__main__":
    main()
