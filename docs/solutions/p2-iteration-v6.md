# 问题二 v6：光伏信息年份与资源上限的配对消融

**v6 已执行，问题二仍未完整验收。** 本轮没有新增拟合参数，12 组训练全部有效，训练损失由 v5 的 0.769515 降到 0.255207；光伏留出误差降低，风电误差增大，仍有五项数值门槛失败。来源、配置、失败与复现证据各自保存。前轮结果见 [v5 说明](p2-iteration-v5.md)。

本地分支仍为 `work/q2-yx-local`，基准和原契约未改；所有 Q2 工作未提交、未推送。2026-10-19 本轮再次 GET Issue #7 时遇到 GitHub API 403 限流，记录保留在 `tmp/q2/v6_references/downloads.json`，所以本轮不声称重新确认了远端状态。上一轮成功核实时间为当天 08:42:25（Asia/Shanghai）。

## 实质来源核对

[原有 IRENA 成本报告](../../data/raw/q2/irena_cost_2014.pdf)物理第 1 页明确写着 2015 年 1 月出版。在模型的年末投资决策中，2015 年可读取该报告。v2—v5 统一推迟到 2016 年的约定过于保守。修正仅影响新项目申请可见时间，2014 年不读取该信息，2015 年申请仍要到 2016 年才投运。

新增 [IRENA《Renewable Energy Prospects: China》](../../data/raw/q2/irena_remap_china_2014.pdf)，封面为 2014 年 11 月；完整核对物理第 59 页、印刷第 47 页的表 13：引用 CNREC（2012），地面电站光伏技术潜力 2200 GWe、屋顶光伏 500 GWe。这两项是技术潜力，既不是年度可建设规模，也不是 2030 年目标或经济可开发容量。

本轮把 2200 GWe 换成 2200000 MW，作为两类模型光伏合计的保守诊断上限。开局总光伏缺少地面/屋顶分解，因此把全部开局容量也计入该上限，属于明确的粗聚合假设；没有再加上屋顶的 500 GW。原 `20 × 开局装机 = 497200 MW` 只保留为消融控制。年度建设与接入额度、资金约束、建设时滞不因资源潜力而放宽。

还核对了 [IRENA 2012 成本报告](../../data/raw/q2/irena_cost_2012.pdf)的物理第 20、58 页：中国地面光伏 2012 年装机成本估计 2160 USD/kW、项目加权容量因子约 18%。正文美元未注明价格年，而相邻图标注 2011 USD；该成本与项目容量因子仅作为独立参考保存，**未用于候选模型**，也未倒推出初始建设队列。

上述检查、原件及记录指纹、许可用途和禁止用途见 [用途审查](../../data/catalog/q2_solar_timing_ceiling_review.json)与[逐项转录](../../data/catalog/q2_solar_timing_ceiling_transcription.json)。没有修改旧审查来扩展旧版本用途。

## 冻结实验和实际结果

[构建器](../../scripts/build_q2_solar_candidate.py)直接读取 v5 冻结输入及训练选择，固定既有成本节点、需求弹性、投资调整、建设扩张率与核电队列。四组结构各比较既有三种规则，共 12 次训练；新增连续拟合参数为零。2015—2021 训练，2022—2024 仍是已接触留出；原阈值不变。

结构顺序在运行前冻结：两项修正、仅年份、仅资源上限、v5 控制。相同训练损失时按该顺序选择，优先采用已经完成来源核查的修正，不按留出选上限。实际“仅年份”和“两项修正”的训练损失相同；这说明训练窗口不能识别资源上限，**不能据此证明 2200 GW 的映射成立**。

训练选择 `date_and_resource_ceiling / instant_margin`。之后用同一规则逐组运行完整历史路径；[四组结果](../../outputs/q2/historical_candidate_v6_ablation/summary.json)保存完整账本，没有第二次按留出择优。

| 同一规则下的结构 | 训练损失 | 风电留出 MAPE | 光伏留出 MAPE |
|---|---:|---:|---:|
| v5 控制 | 0.769515 | 17.48% | 28.46% |
| 仅资源上限 | 0.769515 | 18.15% | 28.06% |
| 仅年份 | 0.255207 | 26.25% | 23.82% |
| 两项修正 | 0.255207 | 32.85% | 19.83% |

| v6 留出指标 | MAPE | RMSE / 持平基线 | 数值门槛 |
|---|---:|---:|---|
| 能耗总量代理 | 1.16% | 0.164 | 通过 |
| 煤份额代理 | 0.84% | 0.351 | 通过 |
| 油份额代理 | 9.26% | 4.151 | 失败 |
| 气份额代理 | 19.37% | 5.959 | 失败 |
| 风电装机 | 32.85% | 1.260 | 失败 |
| 光伏装机 | 19.83% | 0.482 | 失败 |
| 核电装机 | 12.29% | 1.502 | 失败 |
| 燃料 CO₂ 代理 | 4.69% | 0.582 | 通过 |

全部逐指标检查见 [质量文件](../../outputs/q2/historical_candidate_v6/historical_quality.json)。数值通过仍不等于代理量与全国统计边界已经一致。[训练记录](../../outputs/q2/historical_candidate_v6/training_trials.json)与[逐年拟合](../../outputs/q2/historical_candidate_v6/history_fit.csv)可核对，训练损失改善不能代替逐项验收。

[年度约束表](../../outputs/q2/historical_candidate_v6_ablation/constraint_usage.csv)共 44 行，分别记录四组模型的建设额度、接入额度、光伏已建/在建、总量上限和剩余空间。选中版本从 2016 到 2024 年持续用满假定的 150 GW 年度总建设额度；2019—2024 年风电申请获批量为零。较早进入的光伏与煤、水、核项目共同挤占这一研究额度。2024 年光伏为 587842.415 MW，已摆脱 497200 MW 总量上限，但明显低于目标观测；风电只有 291079.949 MW。额度用满并不能证明现实中存在这个固定全国瓶颈，表中余量也不是 LP 影子价格。

## 同范围的 27 组响应与复现

按 [v6 冻结配置](../../workflow/q2_candidates/v6_sensitivity.json)重复 v5 相同的 GDP 增速倍率、技术降本率倍率、统一碳费组合，27 组全部有效。初态、种子、预算不变；这是历史反事实，不是未来全国 S0 灵敏度。[完整结果](../../outputs/q2/historical_candidate_v6_sensitivity/summary.json)及[单因素表](../../outputs/q2/historical_candidate_v6_sensitivity/one_factor_2024.csv)可追溯。

| 单因素变化 | 2024 光伏容量变化 | 2024 燃料 CO₂ 代理变化 |
|---|---:|---:|
| GDP 增速 ×0.8 | 0.000% | −7.041% |
| GDP 增速 ×1.2 | 0.000% | +7.785% |
| 降本率 ×0.5 | −13.620% | +0.120% |
| 降本率 ×1.5 | +10.042% | −0.657% |
| 碳费 50 美元（2008 不变价）/吨 | +33.805% | −5.993% |

光伏降本响应不再完全被旧总量上限截断，但仍受年度建设配置限制。固定高利润价格、通用核电许可、残余燃料需求和代表时段都还影响结论。没有把碳费实验解释为现实 ETS 的因果效果。

独立目录复制 96 个必要文件，离线重建冻结配置并重跑。见 [复现指纹](../../outputs/q2/iteration6_reproduction.json)：候选 17/17、响应 33/33、四组消融 8/8 字节一致；另一环境 16/17 一致，只有 PNG 渲染不同，所有数值账本和 SVG 一致。消融控制与 v5 的八个数值产物完全一致，响应基准及选中消融与 v6 的八个数值产物也完全一致。新增六项测试验证日期、投运时滞、总量与年度额度分离、引用隔离、留出不影响选模和原件篡改拒绝；完整回归 290 项通过。

```powershell
python -m pip install -r requirements-q2-lock.txt -r requirements-q2-data.txt
python -B -X utf8 scripts/build_q2_solar_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v6/manifest.json --output-dir outputs/q2/v6_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --config workflow/q2_candidates/v6_sensitivity.json --output-dir outputs/q2/v6_response_reproduce
python -B -X utf8 scripts/run_q2_solar_ablation.py --output-dir outputs/q2/v6_ablation_reproduce
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
```

每次使用新输出目录，原候选和失败记录保留。下一步必须检验年度建设资源、真实价格及项目许可，并继续完成服务/非能源分账、2024 初态与 2025—2060 全国 S0。B1—B8 的实质缺口没有由本轮文件或测试数量消除，B9 仍需另两人对最终 SHA 的外部评审。
