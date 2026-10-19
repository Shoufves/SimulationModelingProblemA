# 问题二本地整合核对：LB PR #9 主线与 YX PR #10 补充

核对日期：2026-10-19。本文记录本地整合准备，不代表团队批准、PR #9 已合并或 PR #10 已验收。

## 核对版本与范围

按用户决定，以 LB PR #9 的全国聚合条件模型为主线，从 YX PR #10 提取可核实的补强。远端 refs 已只读核对；元数据快照与 Git 对象用于复核提交内容。模型级补强作为显式可选规则实现，LB 原规则仍是默认。

| 项目 | 完整 SHA / 核对信息 |
|---|---|
| 共同 base | `804ec15ee43874303986a7ad91b2cde05c65b124` |
| 最后一次成功核验的 `origin/main` ref | `804ec15ee43874303986a7ad91b2cde05c65b124` |
| LB [PR #9](https://github.com/Shoufves/SimulationModelingProblemA/pull/9) head | `dbb582c5fc887b800e857342665407d9d3a3bfdd` |
| YX [PR #10](https://github.com/Shoufves/SimulationModelingProblemA/pull/10) head | `8e69db49b247ed7bdf221d5a4f407ebe90d003c4` |

在本次 Git 网络错误之前最后一次成功核验时，本地远端跟踪 ref `origin/main` 仍停在共同 base，`origin/p2/lb` 指向 PR #9 head；本次无法刷新，故不把这些值当作当前实时远端状态。最后可用的 `refs/pull/10/head` 指向 `8e69db4…`；本地元数据快照记录 PR #10 于 2026-10-19 06:50:29 UTC 更新，当时为 open/Draft，标题明确写出“全国校准与 S0 未完成”。PR #9 的 06:38:16 UTC 元数据快照为 open/Ready。refs 核对确认了提交头，但未重新请求 GitHub API 更新 PR 状态。

PR #10 的提交对象现已在本地 Git 对象库中，故可读取提交树中的实际文件，不再受文件列表中缺少 `patch` 的限制。该 PR 共改 1,320 条路径，其中 14 个 Q2 源模块、36 个测试文件、28 份文档、150 条 data 路径、151 条 workflow 路径、825 条 outputs 路径及 55 条 archive 路径；总计 17,122,643 行新增、43 行删除。已核对完整路径清单、12 个与 PR #9 重叠路径、两边的输入/入口差异，并阅读直接相关的方案报告、桥接审查、运行分配代码及测试。没有逐行人工检查全部 825 个结果文件，也没有独立重跑 YX 报告的 423 项测试；相关测试数和训练结果在下文均标为作者报告，不作为本次独立复现。

两边重叠的路径为 `README.md`、`WORKFLOW.md`、`data/catalog/datasets_unified.csv`、`data/catalog/workspace_catalog_summary.json`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/RUNNING.md`、`examples/q2/observations.json`、`requirements-q2.txt`、`run.py`、`scripts/build_workspace_catalog.py`、`scripts/run_q2.py` 和 `workflow/q2_inputs.json`。这些文件承担共同入口、输入契约和目录生成职责，整合时保留 LB 版本，不以 YX 版本覆盖。

`workflow/q2_inputs.json` 的语义也不同：LB 版本是 `national_pending_review` 候选清单，实际全国执行仍由单独的来源准入审查阻断；YX 版本标记 `input_admission_in_progress`，`inputs` 与 `sources` 为空。共同 base SHA 相同不表示输入已共同准入。

另有一处版本文档不一致：YX 提交中的 `docs/rounds/P2_Q2.md` 仍写“尚未开始问题二实现”，而同一 PR 的说明和实际提交已包含年度模型、历史候选及其运行证据。该段是准备阶段文字，不能据此代表 PR #10 当前状态；正式整合时应由团队核对是否更新。

## 统计口径参考及准入边界

YX PR #10 的 [2014 账桥接报告](https://github.com/Shoufves/SimulationModelingProblemA/blob/8e69db49b247ed7bdf221d5a4f407ebe90d003c4/docs/solutions/p2-balance-bridge.md)补充了两项统计口径核对：

- **煤炭类别桥接。** 报告指出，CEADs 2014 年 `B54` 原煤发电投入 181,945.9 万吨，与统计局 2016 年鉴煤炭平衡表的 184,525.3 万吨不是同一类别。按该报告记录的类别，`B54 + C54 + D54 = 181,945.9 + 32.2 + 2,547.2 = 184,525.3` 万吨。报告称 15 项对照在各自印刷精度舍入界内一致，同时明确型煤/煤矸石合并列不能被唯一拆分，天然气及交通差异仍未解决。
- **APEC 2014 详细能源账。** 报告记录 6,840 个单元格，保留未释义破折号为缺项；同源 ktoe/PJ 导出间的 1,301 个数值单元格通过单位核对，57 项可检恒等式通过。其部门缺项区间依赖“能源消费非负、整数按 1 ktoe 舍入”的明确假设，属于载体能源边界，不代表有效服务、设备存量或 2024 初态。

上述数字和核验结论均来自 YX 的提交文件，并非 mmj 本次独立重算。对应的 [煤炭审查记录](https://github.com/Shoufves/SimulationModelingProblemA/blob/8e69db49b247ed7bdf221d5a4f407ebe90d003c4/data/catalog/q2_coal_bridge_review.json)、[APEC 审查记录](https://github.com/Shoufves/SimulationModelingProblemA/blob/8e69db49b247ed7bdf221d5a4f407ebe90d003c4/data/catalog/q2_apec_balance_review.json)都标注 `team_approval=false`。APEC 审查还明确数据库版本/发布日期未知、破折号语义未明，并禁止在未完成边界桥接前用它替换 NBS 总量；本次不将其提升为 LB 训练或 2024 初始化输入。

两项工作仅作为统计口径参考诊断登记；不把它们加入 `workflow/q2_inputs.json`、全国训练、2024 初始化或 LB 的预测结果。PR #10 的 `q2_sources.json` 包含 53 条来源记录，其中 48 条对应文件不在 LB PR #9 head 中；只摘文件清单或局部目录会留下不完整来源包。本次没有复制这套原件/处理代码，也没有改变 LB 的准入清单。

## 已纳入 LB 的模型级增量

YX 的 `src/energy_model/q2/deployment.py::allocate_requests` 提供“先收窄到可行申请，再按共同约束同比分配”的审批规则。LB 原审批会先以全部申请金额计算共同资本预算比例，再分别应用融资额度和技术施工上限；某技术的硬上限若在比例分配后生效，剩余预算不会重新分给其他申请。为保留 LB 主线并允许同口径比较，本次在 `NationalModel` 增加可选 `approval_allocation="proportional_feasible_requests"`：先按 LB 现有融资额度、逐技术施工硬上限和同年已承诺量计算可行申请，再按可行申请资本金额计算共同预算比例，之后仍执行 LB 的风光联合收益核查。该模式默认关闭，`lb_budget_first` 保持默认路径。

YX 规则另有接入额度约束；LB 模型没有对应的独立连接额度，因此没有虚构或移植该项。该规则只用于模型口径比较，不改变全国输入、训练或原有预测结果。可经 `run.py q2 --approval-allocation proportional_feasible_requests` 选择；省略输出目录时会写入独立的 `outputs/q2/p2_lb_national_proportional`，并在运行清单及冻结设计中记录口径。新增合成单元测试构造“水电施工上限先绑定、燃气申请可继续吸收预算”的例子，核对两种规则、共同预算上限、申请顺序不变性和审计记录；可选规则的逐申请日志保留原申请量、预算前可行量、共同预算比例及最终批准量。测试不构成全国结果或现实政策结论。

## 其他 YX 内容的处置

| YX 内容 | 核对结果 | 整合处置 |
|---|---|---|
| 按申请比例分配建设/接入额度 | YX 的 `allocate_requests` 在技术组/出资约束后，对可行申请按共同上限同比缩放；LB 没有独立接入额度，且仍保留风光联合收益核查。 | 已将可行申请同比分配映射为 LB 的可选审批口径。仅使用 LB 已有融资、施工和共同资本预算约束；没有接入额度的规则不移植。LB 原 `lb_budget_first` 默认规则未改。 |
| 2016—2018 核电新许可阻断 | YX 的许可事件材料有窄范围历史证据，但其审查没有获得团队批准。LB 的核电年龄限制材料明确不是全国许可证数据库。 | 不把历史事件规则或拟合结果写入 LB 全国审批。 |
| 居民服务/设备映射 | YX 报告中的低温供热比例 5%/10%/20%、锅炉效率 0.85、热泵 COP 3.5 属于诊断假设，未形成全国居民设备初态。 | 保留 YX 局部诊断边界，不改 LB 参数或全国结果。 |
| 2024 状态与交通活动量 | YX 的报告明确容量分项、设备年龄、库存/SOC、建设队列和资金仍有缺项；交通统计中也标明公路货运、水运统计口径变化。 | 作为对照清单，不替换 LB 初态、需求路径或统计口径。 |
| v13 历史候选 | YX 报告称风电留出 MAPE 为 6.57%，但同一选中模型有 5 项指标失败，且未完成全国 S0 和全国灵敏度。两边目标集和代理定义不同。 | 不把 YX 单项数值拼入 LB 结果，不据此重写 LB 结论。 |

## 本地交接状态

本地整合包含 LB 模型中的可选审批分配规则、针对性测试，以及本说明和 LB 主报告的同步记录。没有改动 LB 输入、校准阈值、数据准入、数值产物或只读原文。

2026-10-19 本地自检使用 Python 3.12.14：`python -B -X utf8 run.py test` 全部 262 项通过（0 failures、0 errors、0 skipped）；受限环境中的首次尝试因临时目录 ACL 失败，随后在允许测试夹具创建/清理的环境中完整重跑通过。`python -B -X utf8 run.py audit` 通过，`python -B -X utf8 scripts/scan_google_keys.py` 无命中，清理测试生成的验证快照后 `git diff --check` 通过。本次没有重跑完整全国候选；现有 `outputs/q2/p2_lb_national` 收据因源代码哈希变化已由 `verify_latest` 判为 `Stale national code or inputs`，不能声称该旧产物已用本次代码复验。该增量仅添加显式可选规则，默认仍为 LB 原审批规则；本次自检未生成或宣称新的全国预测结果。

本次按用户最新决定，将含 LB 完整主线与上述可选规则的工作树作为一份整合候选 PR 提交到 `main`。因此新 PR 会包含 PR #9 的完整模型内容及本次补强，属于 PR #9 的整合/替代候选，不是仅含增量的窄 diff；评审范围也包含 LB 主方案。PR 说明会明确两份候选内容重叠，避免同时合并。

截至 2026-10-19，本机最后可见的 `origin/main` 为 `804ec15ee43874303986a7ad91b2cde05c65b124`，`origin/p2/lb` 为 `dbb582c5fc887b800e857342665407d9d3a3bfdd`。本次 `git fetch origin` 因连接本机代理失败，故远端 refs 尚未刷新；此前保存的 PR 状态不能据此当作当前实时状态。发布前仍需重新核对远端 base 与 head。若团队后续决定把煤炭/APEC 材料作为正式来源增量，应完整带入必要原件、来源目录、复算脚本、测试及用途审查，不得仅凭本说明扩大模型输入用途。
