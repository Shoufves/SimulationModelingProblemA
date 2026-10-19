"""Render the current V7 handoff from retained V6 and fresh verification evidence."""
import csv
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    with Path(path).open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


def main():
    from run_q2_national import verify_latest,sha,CODE,INPUTS,load
    out=ROOT/"outputs/q2/p2_lb_national"
    manifest=verify_latest(out)
    review=load(ROOT/"outputs/q2_review/p2_lb_national/verification.json")
    if any(review.get("current_hashes",{}).get(p)!=sha(ROOT/p) for p in CODE+INPUTS):
        raise ValueError("Delivery review is stale for current model or inputs")
    tests=load(ROOT/"outputs/q2_review/p2_lb/tests.json")
    calibration=load(out/"calibration.json")
    coverage=load(out/"experiment_coverage.json")
    extension=load(ROOT/"outputs/q2_review/p2_lb_national/extension_2025.json")
    cap=load(ROOT/"outputs/q2_review/p2_lb_national/construction_limit_checks.json")
    probe=load(ROOT/"outputs/q2_review/p2_lb_national/repaired_counterexamples.json")
    for evidence in (extension,cap,probe):
        if evidence["run_id"]!=manifest["run_id"]:
            raise ValueError("Supplementary evidence belongs to an older run")
    with zipfile.ZipFile(ROOT/"archive/q2_national_v6_before_review7.zip") as z:
        old={int(r["year"]):r for r in csv.DictReader(io.StringIO(z.read("outputs/q2/p2_lb_national/baseline_path.csv").decode("utf-8")))}
    current={int(r["year"]):r for r in read(out/"baseline_path.csv")}
    acceptance=calibration["quality"]["acceptance"]
    text="# 问题二：V7 评审修复与复现结果\n\n"
    text+="2026-10-19；分支 `p2/lb`；共同 base `804ec15ee43874303986a7ad91b2cde05c65b124`。\n\n"
    text+="本轮落实 review(7) 的三项 P2 修复，并统一共同入口。逐项依据、GCB 用途核查及反例见[评审响应](p2-lb-review7-response.md)。V6 的 198 份代码、配置、结果和验收文件完整保存在 `archive/q2_national_v6_before_review7.zip`，不是删除历史结果。\n\n"
    text+=("**本轮声明的检查通过，等待 mmj、yx 对新 SHA 交叉评审。**" if review["passed"] else "**修订已重新运行，但存在未通过的验收项；不能宣布问题二验收完成。**")
    text+=" 执行成功、实证误差通过与团队批准分开；`team_approved=false`，不声称官方预测或盲测。\n\n"
    text+="## 本轮关闭的实现缺陷\n\n| 评审问题 | 修复 | 反例与证据 |\n|---|---|---|\n"
    text+="| 投资响应放大突破施工上限 | 申请及审批均执行原硬上限，累计扣除同年已批准量 | 充裕资金、正NPV、响应1.75；十倍伪造申请；重复审批；全部导出审批复核 |\n"
    text+="| 输入过早缺失留下旧成功和无主空目录 | 哈希计算前写running及归属，异常写failed | 首次缺失、已有成功后缺失、恢复后重试；旧成功原样保留 |\n"
    text+="| 来源用途撤回仍能进入模型 | 强制19来源完整集合、状态、用途、操作权限及指标血缘绑定 | 哈希不变时撤回状态/用途/操作；缺失/重复来源；GCB误入训练均拒绝 |\n"
    text+="| 共同命令走旧阻断入口 | q2_inputs配置名显式兼容全国入口，实际使用单独用途审查 | 默认、显式全国配置、旧共同配置路由测试；独立复现实际走共同配置 |\n\n"
    text+=f"施工核查共{len(cap['checks'])}次审批，超出原限额{sum(r['exceeds'] for r in cap['checks'])}次，最高批准/上限比例{max(r['ratio'] for r in cap['checks']):.6f}。详见 `outputs/q2_review/p2_lb_national/construction_limit_checks.json`。\n\n"
    text+="## 实际执行与拟合\n\n"
    text+=f"全量{tests['tests']}项测试：失败{tests['failures']}、错误{tests['errors']}、跳过{tests['skipped']}。{calibration['search_budget']}组训练中{calibration['successful_trials']}组成功；{coverage['executed']}组条件试验中{coverage['successful']}组成功。验收完成{len(review['checks'])}项，整体通过状态 `{review['passed']}`。\n\n"
    text+=f"最优参数（仍仅按2015—2021训练损失选择）：`{json.dumps(calibration['best']['parameters'],ensure_ascii=False)}`。\n\n"
    text+="| 指标 | 2015—2021训练MAPE | 2022—2024已接触评估MAPE | 评估MAE |\n|---|---:|---:|---:|\n"
    training={r["metric"]:r for r in calibration["quality"]["training"]["components"]}
    for r in calibration["quality"]["already_seen_evaluation"]["components"]:
        mape="无同口径观测" if r["mape"] is None else f"{r['mape']:.4%}"
        mae="无同口径观测" if r["mae"] is None else f"{r['mae']:.6g}"
        train=training[r["metric"]]["mape"]
        text+=f"| {r['metric']} | {train:.4%} | {mape} | {mae} |\n"
    text+="\n原误差门槛及权重没有更改；PEO结构仍按份额MAE判定。\n\n| 原验收项 | 通过 |\n|---|---|\n"
    for name,passed in acceptance["checks"].items():text+=f"| {name} | {passed} |\n"
    text+="\n缺失2022—2024同口径BTR排放评估，绝不填零误差；GCB诊断不能替代该项。所有结构修订均使用已经接触的评估窗口，不改称盲测。\n\n"
    growth=calibration["best"]["parameters"]["solar_construction_growth"]
    upper=max(load(out/"frozen_design.json")["parameter_grid"]["solar_construction_growth"])
    text+=f"本轮光伏训练MAPE为{training['solar_capacity_mw']['mape']:.2%}；最优施工行业增长参数{growth}，原搜索网格上界{upper}。达到预先声明的验收门槛不能掩盖拟合与参数识别限制，不能把搜索网格内的最优值解释为中国真实施工增长率。\n\n"
    text+="## 施工约束修复前后\n\n| 年份/指标 | V6 | V7（重新训练） |\n|---|---:|---:|\n"
    metrics=[("solar_capacity_mw","光伏/TW",1e6),("wind_solar_capacity_mw","风光/TW",1e6),
             ("positive_co2_t","正CO₂/Gt",1e9),("net_co2_t","净CO₂/Gt",1e9),
             ("primary_energy_tce","一次能源/亿tce统计桥",1e8),("unmet_service_mwh","未满足服务/亿MWh服务量",1e8)]
    for year in (2030,2060):
        for key,label,scale in metrics:
            text+=f"| {year} {label} | {float(old[year][key])/scale:.4f} | {float(current[year][key])/scale:.4f} |\n"
    peak=load(out/"peak.json")
    text+=f"\n条件混合历史与未来序列的峰年为 `{peak['year']}`，状态 `{peak['status']}`；不等于官方历史达峰认证。\n\n"
    text+="## GCB新增用途的限制\n\n重新核对20年CHN Total原列和BTR三共同年份，明确新增仅限条件历史峰值桥的作者用途审查。2021锚点比例1.0304498093，缩放后2005年仍低7.2298%，2020年高0.2379%；不能据此证明同口径。源值未改；三年直接BTR值优先，其余按原明示比例假设桥接；不用于训练、误差尺度、同口径留出评估或全温室气体/官方达峰认证。详细数值、两原件哈希和操作限制见 `data/processed/q2/gcb_peak_bridge_review.json`。\n\n"
    text+="## 保留的验证与范围\n\n"
    checks={r["name"]:r for r in review["checks"]}
    reproduced=checks.get("all_scientific_artifacts_byte_identical",{})
    if reproduced.get("passed"):
        text+=f"不同进程与PYTHONHASHSEED=7919实际完整复现，{reproduced['detail']['artifacts']}份科学产物逐字节一致；共同配置命令已经真实执行。Q1的18份科学产物与原成果一致，11项受保护原件/契约与共同base一致。\n\n"
    text+="四类设备、消费者共享资金、联合风光销售、融资及跨年库存的既有修复仍复查，证据见 `repaired_counterexamples.json`。代表日不存在服务缺口也不能证明全年可靠性；缺钱情景的低排放必须与未满足服务联读，不能解释为同等服务减排。\n\n"
    text+="2025补充核对仅观察固定结果，不参与本轮选参，也不称新盲测：\n\n| 指标 | 相对误差 |\n|---|---:|\n"
    for r in extension["observations"]:text+=f"| {r['metric']} | {r['relative_error']:+.4%} |\n"
    text+="\n融资、施工能力、电网、设备年龄及收入均有聚合重建/研究假设；全国单节点24小时循环代表日不能支持跨省拥塞、季节储能、全年可靠性结论。PEO/非化石统计桥、CO₂与全温室气体口径差异保留；氢、抽蓄、CCUS完整独立链仍受初态资料限制，不能凭空计减排。问题三与官方目标认证不在本轮完成声明内。\n\n"
    text+="## 复现与交接\n\n1. `python -B -X utf8 run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/review_pr9_common_entry`。该配置名为公开的兼容别名，真实准入是全国专用审查；旧清单原字节/用途不变。\n2. `python -B -X utf8 scripts/review_q2_delivery.py`：全量测试、Q1与保护检查。\n3. `python -B -X utf8 scripts/review_q2_national_delivery.py`：账本、施工硬限额、原实证门槛、共同入口独立复现。实证不通过仍会完成复现并返回未通过，不更改阈值。\n4. `python -B -X utf8 scripts/check_q2_2025_extension.py` 与 `python -B -X utf8 scripts/check_q2_repaired_mechanisms.py`：补充证据。\n\n"
    text+="最新证据：[验收](../../outputs/q2_review/p2_lb_national/verification.json)、[运行结果](../../outputs/q2/p2_lb_national/report.md)、[全量测试](../../outputs/q2_review/p2_lb/tests.json)。旧阻断配置单独通过 `scripts/run_q2.py` 运行；旧首轮工程验收名称不代表全国候选的状态。另两名成员须评审同一最终SHA；本轮不批准、不合并PR。\n"
    text+="\n本轮替换下来的既有运行另归档于 `archive/q2_revision7_preserved_runs.zip`，逐文件哈希见同名前缀清单；早期已归档版本继续保留。\n"
    (ROOT/"docs/solutions/p2-lb-repaired.md").write_text(text,encoding="utf-8")
    print(json.dumps(dict(report="docs/solutions/p2-lb-repaired.md",review_passed=review["passed"])))


if __name__=="__main__":main()
