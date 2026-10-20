# PR13第二次复审修复记录

评审对象为`af4529bfa7d163052b4412b850a66a4895479a6e`，评审原文由用户提供于工作区根`review_pr13_2.md`。本轮只修复两项P2，不新增研究假设、调参或放宽科学门槛；属于原R9协议的缺陷修复复验，不是第11轮创新探索。

## P2：不可替代原料的服务身份

非能源原料按`nonenergy_feedstock/coal`、`/oil`、`/gas`分别记需求、缺供量与缺供率；其他同部门同用途的能源设备继续按部门汇总，保留设备之间的真实替代。该口径统一用于实际年度、静态预测、完整年度反馈预测及下游比较，未知/缺失原料身份报错。

回归反例在固定PR14真实调度LP中只将煤电容量从20 MW改成0 MW，保持供给、需求、价格、优先级、库存不变。旧汇总看见原料总缺供相同；新口径须识别气原料从0%恶化到100%，并使逐项保留筛查拒绝该动作。另检查油原料身份与能源用途替代不被误拆。

## P2：累计成本的浮点复现门槛

仅在研究验收层，对`/summary/discounted_resource_cost_cny`采用`max(0.02元, 4 × max(ULP(实际值), ULP(参考值)))`。约1.83×10¹⁴元处一个ULP为0.03125元，四个为0.125元；这是累计统计量的有界舍入预算，不是政策或现金容差。差异实际值、原门槛、新门槛及ULP数都保留。四ULP是窄范围工程容差约定，不声称涵盖任意算法/平台的理论误差界。

所有其他字段仍调用原PR14比较器；年份、动作集合、结构、服务、年度成本、现金/物理守恒门槛不变，非有限值仍拒绝。测试必须接受一ULP及四ULP累计差异、拒绝五ULP及1元差异，并拒绝动作/服务/现金/年度金额改变。近似通过不得标成exact_match。

## 冻结复验安排与记录

沿用原`workflow/n2_validation_r9.json`、`n2_controls_r7.json`、`n2_fixed_r9.json`、`n2_reproduction_r9.json`的原字节：40条主路径、32条强对照、4条固定消融、1条另进程不同哈希种子复现，共77条。目录为`tmp/n2/pr13_review2/{primary,controls,fixed,reproduction}`，旧R0—R9归档保留。修复版和旧版服务身份不同，不强行做全字段等价；分别核对共有科学指标和新分原料结果。

评审的78条独立路径及一ULP失败是评审报告所述，当前机器不能访问报告中的E盘附件；不将其冒充本轮亲自执行。评审原文SHA及访问范围见本次归档`review_source.json`。

## 实际自检结果

| 检查 | 本轮实际结果 | 证据（相对outputs/research_n2/pr13_review2） |
|---|---|---|
| 研究测试 | 22项全部通过，新增8项；真实LP反例被识别并拒绝不当退出 | research_tests.json、feedstock_counterexample.json |
| 累计舍入正反例 | 实际旧W08归档注入一ULP：旧比较器失败、新比较器通过且exact_match=false；注入1元拒绝 | roundoff_counterexample.json；这是明确标注的扰动测试，不冒充独立复现 |
| 主验证 | 8×5=40条全部完成，原协议所有门槛通过，8/8少延退、6/8节省≥5% | primary/acceptance.json |
| 强对照 | 8×4=32条重新执行；完整前沿8/8不被支配，7类物理轨迹 | controls、primary/extended_comparison.json |
| 固定项目消融 | 4条重跑，投资与守恒检查通过；少延退11.79%，逐服务缺供相同 | fixed/fixed_invariants.json、fixed/comparisons.json |
| W08独立进程复现 | 1条重跑，PYTHONHASHSEED=83；9091个数字字段，科学JSON exact_match=true | reproduction/reproduction.json |
| 新旧共有结果 | 40条主路径的年度路径、summary、实际退役动作及期末批次均exact_match；新服务与预测向量身份变化明确排除，不能称全JSON相同 | previous_revision_comparison.json |
| 累计账目 | 40条逐年折现重算全部通过 | independent_accounting.json |
| 原料影响范围 | 40条×36年×3原料=4320单元，身份完整、实际年度原料缺供均为0 | material_observed_scope.json |
| 既有测试 | 复用339项原通过收据，对应既有实现/测试未改动；本轮没有重新执行 | legacy_test_reuse.json |

两项P2的自检均通过。修复后的延退、成本和CO2效果量与原报告一致；主候选路径耗时约101—166秒，为同次原滚动规则约8.49—14.57倍，机器负载影响计时，不称速度创新。8/8仍违反系统2%硬服务界，外生保留费用和全国范围限制不变。

修复版77条路径与306份证据文件单独归档，旧641份历史证据不覆盖。完整命令见[方法报告](n2-method-and-results.md)，机器汇总见[最新验收](../../outputs/research_n2/pr13_review2/final_acceptance.json)。仅局部数值比较容差改变，冻结科学门槛、原PR14代码及只读方案不变。人工复核仍为pending，不替评审者批准新SHA。
