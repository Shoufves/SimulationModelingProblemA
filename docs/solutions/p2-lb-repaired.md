# 问题二：V7 评审修复与复现结果

> 2026-10-20更新：本文保留较早版本记录。当前review(9)修复、数据口径和实际验收以[本轮说明](p2-lb-review9-response.md)及[本轮结果](p2-lb-review9-results.md)为准。

2026-10-19；分支 `p2/lb`；共同 base `804ec15ee43874303986a7ad91b2cde05c65b124`。

本轮落实 review(7) 的三项 P2 修复，并统一共同入口。逐项依据、GCB 用途核查及反例见[评审响应](p2-lb-review7-response.md)。V6 的 198 份代码、配置、结果和验收文件完整保存在 `archive/q2_national_v6_before_review7.zip`，不是删除历史结果。

**本轮声明的检查通过，等待 mmj、yx 对新 SHA 交叉评审。** 执行成功、实证误差通过与团队批准分开；`team_approved=false`，不声称官方预测或盲测。

## 本轮关闭的实现缺陷

| 评审问题 | 修复 | 反例与证据 |
|---|---|---|
| 投资响应放大突破施工上限 | 申请及审批均执行原硬上限，累计扣除同年已批准量 | 充裕资金、正NPV、响应1.75；十倍伪造申请；重复审批；全部导出审批复核 |
| 输入过早缺失留下旧成功和无主空目录 | 哈希计算前写running及归属，异常写failed | 首次缺失、已有成功后缺失、恢复后重试；旧成功原样保留 |
| 来源用途撤回仍能进入模型 | 强制19来源完整集合、状态、用途、操作权限及指标血缘绑定 | 哈希不变时撤回状态/用途/操作；缺失/重复来源；GCB误入训练均拒绝 |
| 共同命令走旧阻断入口 | q2_inputs配置名显式兼容全国入口，实际使用单独用途审查 | 默认、显式全国配置、旧共同配置路由测试；独立复现实际走共同配置 |

施工核查共95次审批，超出原限额0次，最高批准/上限比例1.000000。详见 `outputs/q2_review/p2_lb_national/construction_limit_checks.json`。

## 实际执行与拟合

全量257项测试：失败0、错误0、跳过0。2250组训练中2250组成功；91组条件试验中91组成功。验收完成31项，整体通过状态 `True`。

最优参数（仍仅按2015—2021训练损失选择）：`{"activity_elasticity": 0.5, "expectation_rate": 0.25, "investment_response": 1.25, "renewable_mix_response": 0.7, "replacement_adoption": 0.2, "solar_construction_growth": 0.3}`。

| 指标 | 2015—2021训练MAPE | 2022—2024已接触评估MAPE | 评估MAE |
|---|---:|---:|---:|
| primary_energy_tce | 5.4972% | 2.2088% | 1.22512e+08 |
| peo_share | 5.3182% | 2.4857% | 0.00448638 |
| total_capacity_mw | 4.8293% | 6.2041% | 195058 |
| wind_capacity_mw | 8.9735% | 5.6143% | 26635.6 |
| solar_capacity_mw | 35.3515% | 19.9087% | 150588 |
| electricity_generation_mwh | 5.7771% | 1.6321% | 1.50172e+08 |
| combustion_co2_t | 11.3821% | 无同口径观测 | 无同口径观测 |

原误差门槛及权重没有更改；PEO结构仍按份额MAE判定。

| 原验收项 | 通过 |
|---|---|
| energy | True |
| generation | True |
| capacity | True |
| wind_capacity | True |
| solar_capacity | True |
| structure | True |
| sparse_training_combustion | True |

缺失2022—2024同口径BTR排放评估，绝不填零误差；GCB诊断不能替代该项。所有结构修订均使用已经接触的评估窗口，不改称盲测。

本轮光伏训练MAPE为35.35%；最优施工行业增长参数0.3，原搜索网格上界0.3。达到预先声明的验收门槛不能掩盖拟合与参数识别限制，不能把搜索网格内的最优值解释为中国真实施工增长率。

## 施工约束修复前后

| 年份/指标 | V6 | V7（重新训练） |
|---|---:|---:|
| 2030 光伏/TW | 4.6013 | 4.2065 |
| 2030 风光/TW | 5.7448 | 5.6113 |
| 2030 正CO₂/Gt | 11.1905 | 11.0874 |
| 2030 净CO₂/Gt | 9.8440 | 9.7409 |
| 2030 一次能源/亿tce统计桥 | 69.4556 | 69.4642 |
| 2030 未满足服务/亿MWh服务量 | 0.0000 | 0.0000 |
| 2060 光伏/TW | 6.2773 | 7.4700 |
| 2060 风光/TW | 13.3465 | 12.8693 |
| 2060 正CO₂/Gt | 7.4933 | 8.3461 |
| 2060 净CO₂/Gt | 6.1468 | 6.9996 |
| 2060 一次能源/亿tce统计桥 | 90.3620 | 90.2854 |
| 2060 未满足服务/亿MWh服务量 | 0.0000 | 0.0000 |

条件混合历史与未来序列的峰年为 `2025`，状态 `sustained_in_simulated_horizon`；不等于官方历史达峰认证。

## GCB新增用途的限制

重新核对20年CHN Total原列和BTR三共同年份，明确新增仅限条件历史峰值桥的作者用途审查。2021锚点比例1.0304498093，缩放后2005年仍低7.2298%，2020年高0.2379%；不能据此证明同口径。源值未改；三年直接BTR值优先，其余按原明示比例假设桥接；不用于训练、误差尺度、同口径留出评估或全温室气体/官方达峰认证。详细数值、两原件哈希和操作限制见 `data/processed/q2/gcb_peak_bridge_review.json`。

## 保留的验证与范围

不同进程与PYTHONHASHSEED=7919实际完整复现，26份科学产物逐字节一致；共同配置命令已经真实执行。Q1的18份科学产物与原成果一致，11项受保护原件/契约与共同base一致。

四类设备、消费者共享资金、联合风光销售、融资及跨年库存的既有修复仍复查，证据见 `repaired_counterexamples.json`。代表日不存在服务缺口也不能证明全年可靠性；缺钱情景的低排放必须与未满足服务联读，不能解释为同等服务减排。

2025补充核对仅观察固定结果，不参与本轮选参，也不称新盲测：

| 指标 | 相对误差 |
|---|---:|
| total_capacity_mw | -6.2086% |
| wind_capacity_mw | -8.7382% |
| solar_capacity_mw | -10.0426% |
| primary_energy_tce | -0.6468% |

融资、施工能力、电网、设备年龄及收入均有聚合重建/研究假设；全国单节点24小时循环代表日不能支持跨省拥塞、季节储能、全年可靠性结论。PEO/非化石统计桥、CO₂与全温室气体口径差异保留；氢、抽蓄、CCUS完整独立链仍受初态资料限制，不能凭空计减排。问题三与官方目标认证不在本轮完成声明内。

## 复现与交接

1. `python -B -X utf8 run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/review_pr9_common_entry`。该配置名为公开的兼容别名，真实准入是全国专用审查；旧清单原字节/用途不变。
2. `python -B -X utf8 scripts/review_q2_delivery.py`：全量测试、Q1与保护检查。
3. `python -B -X utf8 scripts/review_q2_national_delivery.py`：账本、施工硬限额、原实证门槛、共同入口独立复现。实证不通过仍会完成复现并返回未通过，不更改阈值。
4. `python -B -X utf8 scripts/check_q2_2025_extension.py` 与 `python -B -X utf8 scripts/check_q2_repaired_mechanisms.py`：补充证据。

最新证据：[验收](../../outputs/q2_review/p2_lb_national/verification.json)、[运行结果](../../outputs/q2/p2_lb_national/report.md)、[全量测试](../../outputs/q2_review/p2_lb/tests.json)。旧阻断配置单独通过 `scripts/run_q2.py` 运行；旧首轮工程验收名称不代表全国候选的状态。另两名成员须评审同一最终SHA；本轮不批准、不合并PR。

本轮替换下来的既有运行另归档于 `archive/q2_revision7_preserved_runs.zip`，逐文件哈希见同名前缀清单；早期已归档版本继续保留。
