# P3/mmj：零进口、服务缺供与储能增排的专项诊断

2026-10-20，`p3/mmj`，共同 base `500436ffe8a9ecdf0ebcad3cdae87ef9deddbf93`。对应用户要求先解决的两项机制疑点。依据只读 final 的 E3/H02、运行约束与 E4 分配影响要求开展；沿用 V5 原结果与准入范围，没有新增经验数据、调整正式政策门槛或修改主模型。

**两项原因已取得实际对照证据；原来的无可行政策结论没有因此变成通过。** H02 在当前条件下没有识别到进口风险；交通缺供同时受到供电能力与服务分配规则影响；储能政策路径的累计增排主要体现为发电用煤增加，不能解释为电池自身必然增排。

## 1. H02 为什么进口一直为零

继承的 [NationalSupplier.offer](../../src/energy_model/q2_national.py) 将条件燃料供给包络按国内/进口能力拆分。天然气的 `fuel_import_fraction=0.42` 表示进口**供给上限份额**，没有强制采购42%的进口气。供给包络使用 `fuel_supply_headroom=1.3` 和外生增长路径，不是观测到的逐小时国内产量与进口合同。

原2030同状态快照中，国内气能力为746885.55 MW、进口能力540848.16 MW；初始气库存17547089.10 MWh，期末需要恢复。国内单价224.0853元/MWh，进口单价235.2896元/MWh。国内供给加库存可以覆盖实际调度所需用气，且进口价格更高，因此原解不采购进口。这里的MW均为模型采用的燃料低位热值交付能力，不能当作现实统计数据引用。

将**全部进口气能力关闭**，保持国内能力、价格、需求、初始库存、设备与事件条件不变，真实求解以下四对控制：

| 原事件、场景 | 原窗口国内气能力利用率 | 原进口量 | 关闭全部进口后的变化 |
|---|---:|---:|---|
| selection_moderate / S0 | 82.5186% | 0 | 所有服务缺供和资源成本不变 |
| selection_moderate / SW | 85.2085% | 0 | 同上 |
| test_deeper / S0 | 82.5186% | 0 | 同上 |
| test_deeper / SW | 86.9869% | 0 | 同上 |

部分时段国内能力达到上限，库存承担跨时段调配，不能把窗口平均余量理解为每个时段都有余量。关闭全部进口比正式SG的指定来源削减更严格，结果仍相同，支持“这一组解的进口约束不活跃”。本诊断没有给系统增加国内燃料，也没有重置库存。

证据：[供气分项](../../outputs/validation/p3_mmj/diagnostics_v2/gas_import_diagnostics.csv)、[四对核验](../../outputs/validation/p3_mmj/diagnostics_v2/gas_closure_checks.json)、[完整运行输入输出](../../outputs/validation/p3_mmj/diagnostics_v2/gas_control_details.json.gz)。测试另构造了真正依赖进口的例子，关闭进口后产生缺供，比较器会拒绝“无变化”；诊断并非对任何输入都返回零。

**H02的合适表述是：当前条件供给包络和已运行事件中未识别到进口冲击及其交互作用。** 不能据此证明现实气源风险不存在，也不能为得到非零J而任意缩减国内供给。若后续需要对真实进口依赖作结论，需单独核验国内生产/交付、进口合同与库存的同口径约束，并按新版本重新校准和验收；本轮没有把此项数据缺口伪装为已完成。

## 2. 交通缺供为什么大

目标为2060年 `test_deeper/SGW`，连续11天、44个6小时时段。保留真实前24小时运行，再对后40个时段进行19种诊断；两政策共38次。后段沿用事前SOC、燃料库存、已经花掉的预算、已使用的发电能量和爬坡边界。基线后段重放与原事件的服务和排放结果相符。

### 2.1 先分清物理约束与分配规则

这些短缺发生在天气冲击下的发电交付与跨时段调节过程中。后段煤电达到当期可用功率上限的时段数为33/40（none）、26/40（storage）；风电在40个时段达到天气折减后的上限；水电窗口能量用满。与此同时，电网最大利用率约82.48%，终端设备输入能力最大利用率不超过72%，服务预算也存在余量。

单独增加1%的电网、终端设备、预算、燃料交付或储能功率，没有改善所观察的交通缺供。none增加1%全部发电功率后，交通缺供从40.6915%降到40.2875%；只增加1%煤电功率，降到40.5888%。增加水电窗口能量主要改善其他既有电力服务。

storage增加1%发电功率后，交通缺供仍为31.0909%，但其他既有电力服务缺供从9.5604%降到9.0592%。因此，“交通这一项不变”不能被写成“供电能力对所有服务均无影响”。这些是当前点附近的局部扰动，不能排除更大规模、不同组合或其他年份的作用。原2060年两个目标中的气电装机均为0，给气电零装机乘1.01仍为0，不能把这个探针写成新增气电试验。

运行器 [q2_operations.py](../../src/energy_model/q2_operations.py) 按固定优先级依次最小化服务代理量缺口；继承配置中各服务都为priority 0，同层缺口系数均为1。交通电驱效率为0.9，既有电力服务为1。这种目标会影响有限电力分给谁；不同服务代理量的同层等权，是模型分配约定，不是经过现实福利权重校准的结论。

### 2.2 改交通优先级后，缺供转移到了其他服务

仅在诊断中把交通保留在priority 0，其余需求全部移到下一层，资源、服务要求和初态不变：

| 政策路径与调度规则 | 交通缺供 | 其他既有电力服务缺供 | 电力出口缺供 |
|---|---:|---:|---:|
| none，原规则 | 40.6915% | 16.9183% | 13.6364% |
| none，优先交通 | 0.3185% | 23.2249% | 36.3636% |
| storage，原规则 | 31.0909% | 9.5604% | 0% |
| storage，优先交通 | 0% | 14.4342% | 0% |

另五项服务在这四种结果中均无缺供。报告逐服务保留损失，**不能把保护交通后的交通零缺供称为整体安全改善**，也不能跨服务直接相加解释为社会福利。40.6915%是指定11天窗口内的交通服务代理量缺口占该服务需求的比例，既不是全国全年缺电率，也不是现实交通停运比例。

证据：[全部304条逐服务探针结果](../../outputs/validation/p3_mmj/diagnostics_v2/event_probe_effects.csv)、[约束利用情况](../../outputs/validation/p3_mmj/diagnostics_v2/event_active_constraints.csv)、[完整后段输入输出](../../outputs/validation/p3_mmj/diagnostics_v2/event_probe_details.json.gz)。约束接近上限本身不证明唯一成因，因此同时保存了实际扰动求解。

## 3. 为什么储能方案改善事件缺供却累计增排

这里比较的是两套带年度投资反馈的政策路径，不是相同发电资产下仅替换电池。事件缺供改善9.6006个百分点和2025—2060累计增排4.290365 Gt来自不同时间尺度，不能直接把二者当成一次充放电的因果关系。

### 3.1 增排发生在哪里

逐年从燃料投入重新核算，扣除非能源原料：两方案直接燃烧排放完全相同；差额全部来自发电转换投入。

| 燃料 | storage减none的累计燃烧CO₂ |
|---|---:|
| 煤 | +4.221327 Gt |
| 天然气 | +0.028863 Gt |
| 油 | +0.040175 Gt |
| 合计 | +4.290365 Gt |

模型生物质燃烧系数为0，沿用原口径；这里不是生命周期或全温室气体排放。累计发电中，煤电增加5082.053 TWh、风电减少9250.465 TWh、光伏增加4934.676 TWh。不能只看总发电量就忽略来源替换。

电力恒等式逐年成立：总发电量 = 终端负荷折算到发电母线的输入 + 储能净损耗。两路径累计差额为 **898.165 TWh = 701.459 TWh + 196.707 TWh**。有额外损耗，但这项能量差额并不等于全部排放差额，也不能按某个任意统一排放因子分摊。

证据：[燃料分项](../../outputs/validation/p3_mmj/diagnostics_v2/annual_carbon_components.csv)、[逐技术发电与容量](../../outputs/validation/p3_mmj/diagnostics_v2/annual_generation.csv)、[电力恒等式](../../outputs/validation/p3_mmj/diagnostics_v2/annual_electricity_identity.csv)。

### 3.2 固定其余条件，只替换储能能力

对none路径2025—2060每年保存的运行输入，仅换成storage路径该年的储能功率与库容；保留none当年的其他设备、需求、燃料供应、价格、预算及原SOC，独立求解36次。累计排放变化为 **−0.525251 Gt**。其中个别年份仍增排，不能写成每年减排。

因此，在这一明确替换顺序下，累计总差额可写为：

`+4.290365 = −0.525251 + 4.815616 Gt`

后项是从控制运行到实际storage路径的剩余差异，含年度资产、需求/状态路径和相互作用；不是严格单独识别出的“投资因果贡献”。控制没有补做资金审批和建设，只用于解释既有结果，**不属于新可行政策**。

反向替换请求36次，其中2032年原SOC为36968.0574 MWh，换入的库容只有33640 MWh，无法同时保持原库存。该次明确记为不可构造，其余35次真实运行。没有削减或重置SOC，没有将缺失效应填0，也没有用35年结果冒充完整36年反向归因。

证据：[72项控制状态及结果](../../outputs/validation/p3_mmj/diagnostics_v2/annual_storage_swaps.csv)、[71次完整控制](../../outputs/validation/p3_mmj/diagnostics_v2/annual_swap_details.json.gz)、[不可构造记录](../../outputs/validation/p3_mmj/diagnostics_v2/unavailable_annual_controls.json)。

### 3.3 建设队列证实资产路径发生了变化

继承的年度机制将发电销售收入、现金、预期利润、弃电及新增风光边际收入反馈到下一轮投资；不是给储能方案强行附加煤电结论。两个实际队列存在以下差异：

- 2031年批准的光伏容量，none为81005.32 MW，storage为162010.64 MW；2032年storage批准的风电为104887.74 MW，none为209775.48 MW。后续年份也有不同的风光批次与规模。
- storage于2047—2050年分别批准79771.14、81765.42、83809.56、85904.79 MW煤电，2051—2054年投运；none没有对应四批。合计331250.91 MW，正好对应2060年两路径煤电装机差额。
- 到2060年，none煤电589350.02 MW，storage为920600.94 MW。因此原事件安全改善也包含不同资产路径的效果，不能全部算作同资产下储能直接收益。

证据：[建设项目表](../../outputs/validation/p3_mmj/diagnostics_v2/generation_projects.csv)及原始 [none年度账](../../outputs/q3/p3_mmj_v5/cases/policy_none.json.gz)、[storage年度账](../../outputs/q3/p3_mmj_v5/cases/policy_storage.json.gz)。项目应按技术、审批年、投运年与容量核对，不能仅凭跨路径内部流水号不同就认定新增。

## 4. 两轮自查与交付边界

执行程序为 [diagnose_q3_mechanisms.py](../../scripts/diagnose_q3_mechanisms.py)，协议为 [q3_diagnostics_v2.json](../../workflow/q3_diagnostics_v2.json)。程序核验原V5模型、输入与科学文件指纹，拒绝覆盖已有诊断目录，保存完整输入输出、代码快照及收据。

[review_q3_diagnostics.py](../../scripts/review_q3_diagnostics.py)不使用诊断程序的汇总函数，独立核验能量、库存、预算、事前状态、合法控制改动、逐服务指标、原料扣除及累计排放。

- 第一轮最终核验：[diagnostics_review_round1_final.json](../../outputs/validation/p3_mmj/diagnostics_review_round1_final.json)。4对进口控制、38次事件探针、71次年度控制通过；1项不可构造如实保留。
- 第二轮：[diagnostics_review_round2.json](../../outputs/validation/p3_mmj/diagnostics_review_round2.json)。在原独立checkout中，以`PYTHONHASHSEED=1729`从另一份真实V5复现结果重新计算，16份诊断产物逐字节一致。独立运行日志和manifest另存验证目录。
- V1在2032年非法库容替换处退出1；V2将其保留为不可构造后继续其他控制。V1日志、协议、代码快照与失败收据保留。增强审查器还发现自身把数字0与0.0误判为不同结构，已修正数字等价判断，并增加反例；失败记录与修复前代码保留。均未改动主模型或研究阈值。
- 全套344项测试已通过，0失败、0错误、0跳过，含新增5项诊断反例。沙箱运行曾因Windows临时目录/进程权限出现34项错误，失败日志保留；同一代码在当前用户权限下真实重跑通过。原件审计、密钥扫描、原九子集准入及当前源指纹检查见[本次验证汇总](../../outputs/validation/p3_mmj/diagnostics_validation_summary.json)。旧V5的339项测试记录仍只表示原快照。

复现时使用新输出名，保护已有证据：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/diagnose_q3_mechanisms.py --output-dir outputs/validation/p3_mmj/diagnostics_recheck
.\.venv\Scripts\python.exe -B -X utf8 scripts/review_q3_diagnostics.py --diagnostics outputs/validation/p3_mmj/diagnostics_recheck --receipt outputs/validation/p3_mmj/diagnostics_recheck_review.json
.\.venv\Scripts\python.exe -B -X utf8 run.py test
.\.venv\Scripts\python.exe -B -X utf8 run.py audit
.\.venv\Scripts\python.exe -B -X utf8 scripts/scan_google_keys.py
```

本轮完成的是“原因可验证、结论有边界”的诊断补强。现实进口依赖校准、服务优先级的团队认可及新增可行政策，不能由这份诊断替代。原1%服务界与累计碳界保留；原政策仍未通过。未commit、push或创建PR，C9仍待另外两人评审同一最终SHA。
