"""Render a candid before/after handoff from immutable V4 and current evidence."""
import csv
import io
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    from run_q2_national import verify_latest,sha,CODE,INPUTS
    out=ROOT/"outputs/q2/p2_lb_national"
    manifest=verify_latest(out)
    with (out/"baseline_path.csv").open(encoding="utf-8") as f:
        current={int(r["year"]):r for r in csv.DictReader(f)}
    with zipfile.ZipFile(ROOT/"archive/q2_national_v4_mechanism_review.zip") as z:
        before={int(r["year"]):r for r in csv.DictReader(io.StringIO(z.read("outputs/q2/p2_lb_national/baseline_path.csv").decode("utf-8")))}
    with zipfile.ZipFile(ROOT/"archive/q2_national_v5_before_remaining_repairs.zip") as z:
        v5={int(r["year"]):r for r in csv.DictReader(io.StringIO(z.read("outputs/q2/p2_lb_national/baseline_path.csv").decode("utf-8")))}
    calibration=json.loads((out/"calibration.json").read_text(encoding="utf-8"))
    coverage=json.loads((out/"experiment_coverage.json").read_text(encoding="utf-8"))
    review=json.loads((ROOT/"outputs/q2_review/p2_lb_national/verification.json").read_text(encoding="utf-8"))
    if any(review.get("current_hashes",{}).get(p)!=sha(ROOT/p) for p in CODE+INPUTS):
        raise ValueError("Delivery review is stale for current model or inputs")
    tests=json.loads((ROOT/"outputs/q2_review/p2_lb/tests.json").read_text(encoding="utf-8"))
    ext=json.loads((ROOT/"outputs/q2_review/p2_lb_national/extension_2025.json").read_text(encoding="utf-8"))
    if ext["run_id"]!=manifest["run_id"]:
        raise ValueError("2025 crosscheck belongs to an older run")
    passed=review["passed"] and calibration["quality"]["acceptance"]["all_thresholds_passed"]
    text="# 问题二：机制修复与重新验收\n\n"
    text+="2026-10-19。共同base：`804ec15ee43874303986a7ad91b2cde05c65b124`；工作分支：`p2/lb`。\n\n"
    text+=("**本轮机制修复、声明范围内的实证误差验收与独立进程复现已完成，作为附带假设的研究候选交叉评审。**" if passed else "**当前仍有验收未通过项，不能宣布问题二完成。**")
    text+=" 该状态不等于盲测验证、官方预测或团队批准。原V4版本连同代码、配置、结果与缺陷证据保存在 `archive/q2_national_v4_mechanism_review.zip`，未删除。\n\n"
    text+="## V6：上次仍可修复的四项已处理\n\n"
    text+="V5完成了当时列出的七项机制修订，但并未穷尽可修复问题。V6专门关闭随后复查列出的四项；V5代码、参数、结果、测试和报告已原样保存于 `archive/q2_national_v5_before_remaining_repairs.zip`。原始准入、已接触评估身份与误差门槛均保持不变。\n\n"
    text+="| 剩余问题 | 本次实现 | 反例与验收 |\n|---|---|---|\n"
    text+="| 存量电力服务设备随需求免费扩容 | 四类服务均有寿命、退出、付款及下一年投运队列；需求增长不改写设备容量 | 需求放大10倍，设备容量增量为0；未付款不能投运；逐项核对队列与现金支出 |\n"
    text+="| 需求侧现金只用于记账 | 明示外生收入、留存现金、共享能源预算及设备出资；能源账单与设备支出实扣现金 | 零收入零现金仍保留全部原需求为未满足服务；多载体不重复领取同一预算；跨年现金连续 |\n"
    text+="| 投资前瞻与联合审批不一致 | 前瞻使用同一渐变用电弹性；仅延续当年GDP增长预期；按未来存续与已付款资产重算；联合批准检查每个项目在其余项目存在时的新增收益 | 两个项目单独盈利、联合重复占用市场的实际LP反例迫使缩量；最终批准量与联合审查日志一致 |\n"
    text+="| 验收运行期间残留旧通过状态 | 启动即写入running/未通过，每项检查后刷新，失败写入failed | 预置旧成功后注入验收故障，首项检查已看到running，最终不得保留passed |\n\n"
    text+="需求收入以初态每单位服务能源费用×1.25加设备年化更新费用重建；单位收入不随实际账单、燃料价格压力或实际服务量自动补偿。系研究预算假设，不是新获取的中国家庭/部门收入统计；0.5/1.5倍收入压力均单独运行。能源购买先于设备投资，两者共享同一现金余额。外贸/非能源原料仍是单独商品结算账户。\n\n"
    text+="## 原七项机制修复\n\n"
    text+="| 问题 | 修订 | 验收证据 |\n|---|---|---|\n"
    text+="| 电网随电源免费扩大 | 电网独立容量、预算、工期、退出与建设队列；储能用实际弃电/缺供反馈 | 新增电源不改变电网上限；电网付款满工期后才投运 |\n"
    text+="| 主体现金不约束投资 | 明确发起人出资、外部股权、贷款与偿付；按资产原成本折旧，不用新设备降价改写旧资产；逾期阻断融资 | 负现金拒绝新增；贷款本金和利息逐项核对；逐项目融资闭合 |\n"
    text+="| 光伏按电站存量自我放大 | 建设施工能力从初态独立增长并逐渐收敛；增长率只在训练窗口校准；检查候选项目新增售电收益 | 直接增加存量不增加施工上限；旧收益为正但无接入能力仍拒绝新项目 |\n"
    text+="| 碳价只事后记账 | 已覆盖发电的净配额机会成本进入报价，金融转移与资源费用分开；终端覆盖需单独指定 | 构造边际排序跨越反例，调度实际改变；覆盖终端替代与账本同时验证 |\n"
    text+="| SOC每年重置 | 新增储能从空状态开始；期末向下一年传递；退出所处置库存单列；燃料也继承库存 | 逐年库存交接误差检查，不以代表日权重放大库存 |\n"
    text+="| 需求与统计口径外推过强 | 用电弹性渐变并测试终值；同时报告固定统计桥和直接等价值；施工、融资、电网与初态加入范围试验 | 保留两种核算的不同含义；不把代理份额直接认证为官方目标达成 |\n"
    text+="| 测试通过被当成科学完成 | 增加针对缺陷的反例、当前全量回归、逐账复核、2025年补充核对及独立进程复现 | 所有误差门槛保持V4原值；已接触评估身份不变；缺失排放验证不填零 |\n\n"
    text+="## 实际验证结果\n\n"
    text+=f"全量{tests['tests']}项测试，失败{tests['failures']}、错误{tests['errors']}、跳过{tests['skipped']}。本轮{calibration['search_budget']}组训练候选，{calibration['successful_trials']}组执行成功；{coverage['executed']}组敏感性/结构条件试验，{coverage['successful']}组执行成功。验收报告记录{len(review['checks'])}项检查，最终通过状态为 `{review['passed']}`。\n\n"
    probe=json.loads((ROOT/"outputs/q2_review/p2_lb_national/repaired_counterexamples.json").read_text(encoding="utf-8"))
    if probe["run_id"]!=manifest["run_id"] or probe["model_hashes"]!=manifest["code_hashes"]:
        raise ValueError("Mechanism counterexamples belong to an older run")
    zero=probe["zero_consumer_funding"]
    text+=f"V6新增实际反例：零需求端资金时，原请求{zero['requested_service_mwh']:.2f}MWh服务量、实际服务{zero['served_service_mwh']:.2f}、未满足{zero['unmet_service_mwh']:.2f}，新增设备{zero['new_devices']}项；需求放大10倍后存量电力设备增量{probe['electric_device_capacity_increment_after_10x_demand_mw']:.2f}MW；基准全部能源采购最大超预算{probe['max_consumer_spending_over_budget_cny']:.6f}元。联合风光审查共{probe['joint_renewable_audit_rounds']}轮，其中{probe['joint_renewable_rejected_rounds']}轮未通过并继续缩量或拒绝。\n\n"
    text+=f"修复后实际同初态对照：初始现金分别为正/负1e15元时，新增获批装机分别为{probe['approved_new_generation_mw'][0]:.2f}MW/{probe['approved_new_generation_mw'][1]:.2f}MW；增加1TW电源时电网上限增加{probe['grid_increment_after_1TW_source_added_mw']:.1f}MW；跨年SOC最大交接残差{probe['max_cross_year_soc_residual_mwh']:.6f}MWh。详见[反例证据](../../outputs/q2_review/p2_lb_national/repaired_counterexamples.json)。这些极端值只检验机制，不是现实情景假设。\n\n"
    text+="| 2022—2024已接触评估指标 | MAPE |\n|---|---:|\n"
    for r in calibration["quality"]["already_seen_evaluation"]["components"]:
        value="无同口径观测" if r["mape"] is None else f"{r['mape']:.2%}"
        text+=f"| {r['metric']} | {value} |\n"
    text+="\nPEO结构门槛使用份额MAE；上表MAPE仅供完整展示，不替代原判据。\n\n"
    text+="## 条件结果：修复前后\n\n| 年份/指标 | V4缺陷候选 | 修复后 |\n|---|---:|---:|\n"
    metrics=[("solar_capacity_mw","光伏装机/TW",1e6),("wind_solar_capacity_mw","风光装机/TW",1e6),("primary_energy_tce","一次能源/亿tce统计桥",1e8),("net_co2_t","净CO₂/亿吨",1e8),("unmet_service_mwh","未满足服务/亿MWh服务量",1e8)]
    for y in (2030,2060):
        for key,label,scale in metrics:
            text+=f"| {y} {label} | {float(before[y][key])/scale:.3f} | {float(current[y][key])/scale:.3f} |\n"
    text+="\n这是相同研究边界下的模型比较，不是现实观测。未满足服务混合不同终端代理，不等同于总缺电量；结果变得较小不单独构成正确性证据。\n\n"
    text+="## 本次追加修复的结果变化\n\n| 2060指标 | V5 | V6 |\n|---|---:|---:|\n"
    for key,label,scale in metrics:
        text+=f"| {label} | {float(v5[2060][key])/scale:.3f} | {float(current[2060][key])/scale:.3f} |\n"
    text+="\n预算约束在默认收入路径下可以不成为紧约束；是否有效由资金短缺反例及敏感性试验判断，不能以默认输出必须大幅变化为修复标准。所有训练候选重新计算，按原训练损失选参。\n\n"
    with (out/"sensitivity.csv").open(encoding="utf-8") as f:
        income_rows=[r for r in csv.DictReader(f) if r["year"]=="2060" and r["label"].startswith("consumer_income_multiplier=")]
    text+="## 新增收入压力试验\n\n| 收入倍率 | 2060未满足服务/亿MWh服务量 | 2060净CO₂/亿吨 |\n|---|---:|---:|\n"
    for label in sorted({r["label"] for r in income_rows}):
        values={r["metric"]:float(r["value"]) for r in income_rows if r["label"]==label and r["metric"] in {"unmet_service_mwh","net_co2_t"}}
        text+=f"| {label.split('=')[1]} | {values['unmet_service_mwh']/1e8:.3f} | {values['net_co2_t']/1e8:.3f} |\n"
    text+="\n收入不足时排放可能随未满足服务增加而下降，这不能解释为提高能效或实现了同等服务减排；必须联读服务缺口与排放。该试验验证预算传播机制，不是中国居民收入或贫困率预测。\n\n"
    text+="## 冻结后的2025年补充核对\n\n| 指标 | 相对误差 |\n|---|---:|\n"
    for r in ext["observations"]:text+=f"| {r['metric']} | {r['relative_error']:+.2%} |\n"
    text+="\n原图/原文已逐项核对，准入限定为补充核对，不参与任何参数选择。2025装机主要检验初始在建队列，不能据此证明新增投资行为正确；数据此前已存在，不宣称全新盲测。\n\n"
    text+="## 尚不能声称的事项\n\n"
    text+="- 融资与施工、电网等新增数值是明示的研究假设；通过反例只能证明机制起作用，不能证明它们就是中国企业的真实参数。\n- 2022—2024已被用于多版结构修订。2020/2021仅两点同口径排放训练，缺乏2022—2024同口径排放评估。这些限制没有因测试数量增加而消失。\n- 全国单节点、24小时循环代表日不支持跨省拥塞、全年可靠性及季节储能结论。初态重建和统一电价仍是模型简化。\n- 抽蓄与水电统计边界尚不能从当前观测完整分离；氢的上游燃料包含在总量/原料余量内，未伪造全国独立转换链；CCUS没有凭空计减排。问题三若要比较这些技术，须另行补齐转换、功率、能量及成本初态。\n- 官方非化石口径与全温室气体中和不能用当前统计桥/CO₂结果代替；条件基准未达标不是程序失败，也不能反向强调参数使其达标。\n\n"
    text+="修复过程中保存了训练失败和首版修复评估失败记录。第一轮仅修施工与融资时光伏训练误差约46%；修订项目抵押和股权来源后训练改善，但评估风光仍约26%/30%，且长期过建仍明显。加入新增售电检查并细化训练网格后，仍发现按新设备现价重估抵押物导致2022年后投资冻结；最终改为逐批资产原成本与折旧。所有结构修订都公开，不把最终评估重新命名为独立验证。\n\n"
    text+="## 复现与交接\n\n1. `python -B -X utf8 run.py q2`：重新训练、评估和推演。\n2. `python -B -X utf8 scripts/review_q2_delivery.py`：全量回归、Q1原成果与工程边界检查。\n3. `python -B -X utf8 scripts/review_q2_national_delivery.py`：新机制账本、原误差门槛与独立进程复现。\n4. `python -B -X utf8 scripts/check_q2_2025_extension.py`：固定结果的2025年补充核对。\n\n"
    text+="当前机器证据：[验收](../../outputs/q2_review/p2_lb_national/verification.json)、[运行报告](../../outputs/q2/p2_lb_national/report.md)、[2025核对](../../outputs/q2_review/p2_lb_national/extension_2025.json)。每次完整运行附有代码/输入快照及哈希，旧尝试保留。PR仍需另外两人对同一最终提交评审；不代替他们批准或合并。\n"
    text+="\n中间尝试归档：[ZIP](../../archive/q2_revision5_attempts.zip)、[逐文件哈希清单](../../archive/q2_revision5_attempts_manifest.json)。早期仅训练的探索运行产生于代码快照功能加入之前，保留其结果与代码哈希，不声称已保存每份中间源码；其后的完整运行含实际代码快照。\n"
    text+="\nV6重跑所保留的旧运行及故障探针：[归档ZIP](../../archive/q2_revision6_preserved_runs.zip)、[逐文件哈希清单](../../archive/q2_revision6_preserved_runs_manifest.json)。压缩包逐文件验哈希后，展开副本移至忽略的工作历史目录；有效结果未删除。\n"
    path=ROOT/"docs/solutions/p2-lb-repaired.md"
    path.write_text(text,encoding="utf-8")
    print(json.dumps(dict(report=str(path),accepted=passed,run_id=manifest["run_id"]),ensure_ascii=False))


if __name__=="__main__":main()
