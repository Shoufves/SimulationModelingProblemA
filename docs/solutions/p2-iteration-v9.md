# 问题二第九轮：联合校准风光扩张率与建设约束

v9完成486组训练候选、三条完整对照路径及27组历史响应。训练损失由v8的0.262689降至0.235760，但风电留出MAPE由29.07%升至42.61%；油、气、风、光仍未通过。**全国S0、2030/2060指标及完整问题二继续未验收。**

## 设计与选择边界

v7在沿用旧风光扩张率的条件下，将共用施工、接入限制改为技术额度，出现过量扩张。其结果只能说明这组参数与新结构不匹配。v9在两种结构中分别校准风、光扩张率，使结构比较不再被继承参数混淆。

[冻结构建器](../../scripts/build_q2_joint_deployment_candidate.py)继承v8全部其他参数、初态、核电队列和2016—2018实际拒批事件。每种技术的参考扩张率为2014新增装机下限／初始在运装机，乘数仍在原0—2范围内，以0.25为间隔；风、光独立取值，9×9个组合。两种结构、三种既有行为规则共486组，全部有效；九轮累计3531组有效训练候选，失败的原v2尝试另存。

所有选择只使用2015—2021损失，权重、误差阈值和2022—2024评估窗口不改。开发前已接触留出，因此仍是探索性迭代，不是独立盲测；所选参数只是此冻结网格中的最优，不是全局最优或实测制造能力。

| 结构 | 风电乘数／年扩张率 | 光伏乘数／年扩张率 | 最佳规则 | 训练损失 |
|---|---|---|---|---:|
| v8原控制 | 2／0.429119 | 2／0.657281 | instant_margin | 0.262689 |
| 共用施工与接入约束 | 1.25／0.268199 | 2／0.657281 | instant_margin | 0.235760 |
| 各技术有限建设额度 | 0.75／0.160920 | 1.75／0.575121 | instant_margin | 0.399336 |

全局训练选择为共用约束，等效候选集只有该一组。光伏乘数位于网格上界，不能据此声称该参数已被充分识别。各技术结构经重校准后的损失明显低于v7继承参数时的2.627446，但仍高于本轮共用结构；这不能推广成对所有技术约束模型的否定。

## 真实留出与误差归因

| 指标 | 所选v9留出MAPE | RMSE／持平基线 | 原门槛 |
|---|---:|---:|---|
| 能源总量代理 | 1.16% | 0.164 | 通过 |
| 煤炭份额代理 | 0.43% | 0.163 | 通过 |
| 石油份额代理 | 9.18% | 4.118 | 未通过 |
| 天然气份额代理 | 19.47% | 5.990 | 未通过 |
| 风电装机 | 42.61% | 1.565 | 未通过 |
| 光伏装机 | 19.83% | 0.482 | 未通过 |
| 核电装机 | 4.58% | 0.558 | 通过 |
| 燃料CO2代理 | 3.95% | 0.492 | 通过 |

完整[逐目标结果](../../outputs/q2/historical_candidate_v9/historical_quality.json)和[原始曲线](../../outputs/q2/historical_candidate_v9/historical_fit.svg)均保留。所选模型风电2021—2024停留在248.78GW，不能复现后段增长；光伏早期不足、后段受共用额度压制。总量或燃料CO2代理改善不能掩盖这两条装机路径的错误。

[公平对照](../../outputs/q2/historical_candidate_v9_comparison/summary.json)为每种结构使用各自训练所选参数和规则，再运行完整2014—2024。共用模型光伏训练加权损失0.215380，占其总损失约91%；各技术模型为0.392123，占约98%。后者风电留出MAPE10.44%通过，但2024光伏达1483.63GW，光伏MAPE57.92%，且煤炭份额和燃料CO2也未通过。不能将各模型中最好的单项拼成不存在的联合结果。

三条路径都保存完整现金、资产、项目和运行账，另有[技术活动](../../outputs/q2/historical_candidate_v9_comparison/technology_activity.csv)、[约束用量](../../outputs/q2/historical_candidate_v9_comparison/constraint_usage.csv)和[训练损失分解](../../outputs/q2/historical_candidate_v9_comparison/training_loss_parts.csv)。三条完整重放的训练前缀均与冻结训练试验一致。由于规则和参数一起重选，本对照不应解释为单一约束的政策因果效应。

## 响应与复现

沿用已声明的GDP增长倍率0.8／1／1.2、降本倍率0.5／1／1.5、碳费0／25／50常价2008美元每吨，[27组历史响应](../../outputs/q2/historical_candidate_v9_sensitivity/summary.json)全部成功。其基准完整账与训练所选模型一致；2014—2024条件响应不是全国2025—2060的B6。

新增两项联合校准测试覆盖：改变全部留出目标不影响训练试验、结构、规则和参数选择；风电参数干预不改变光伏额度或原始输入。此前模型测试均保留。后续政策时间线四项及货币桥接五项测试一起完成后，完整回归337项通过，其中155项Q2。

[独立复现](../../outputs/q2/iteration9_reproduction.json)复制99个代码与输入文件，在两个既有独立环境执行构建、486组训练、三条对照和27组响应。固定环境候选17/17、对照9/9、响应33/33逐字节相同；另一环境分别16/17、9/9、33/33，唯一差异为PNG字体栅格，规范SVG和全部数值相同，图表已目视核对。v8原控制完整账未变；v9响应基准完整账与本轮配对路径一致。历史版本未覆盖。

```powershell
python -B -X utf8 scripts/build_q2_joint_deployment_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v9/manifest.json --output-dir outputs/q2/v9_reproduce
python -B -X utf8 scripts/run_q2_joint_deployment_comparison.py --output-dir outputs/q2/v9_comparison_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --config workflow/q2_candidates/v9_sensitivity.json --output-dir outputs/q2/v9_response_reproduce
```

运行必须使用新输出目录。本轮后的[历史电价时间线补核](p2-policy-timeline.md)只形成输入参照，不倒改上述冻结结果。实际政策、有效服务与设备、时序、2024初态和全国净CO2仍需进一步映射；六组全国输入缺口未关闭，B9另需两名外部评审认可最终SHA。
