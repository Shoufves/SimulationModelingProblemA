# P3/mmj 验证证据索引

当前完整版本为V5，配置 `workflow/q3_inputs_v5.json`，运行结果 `outputs/q3/p3_mmj_v5/`。

其后新增机制诊断，主模型和V5收据不变。最新诊断验证索引是 `diagnostics_validation_summary.json`，可读结论见 `docs/solutions/p3-mmj-diagnostics.md`。下表中的V5测试数量和文件是该次主实验自查快照。

| 专项诊断证据 | 用途 |
|---|---|
| `diagnostics_v2/`、`diagnostics_v2.log` | 4对进口控制、38次事件探针、71次储能年度控制及1次不可构造；含代码、协议、完整数据和指纹 |
| `diagnostics_review_round1_final.json`、`diagnostics_review_round2.json` | 最终审查器的两轮核验；第二轮含独立运行16份产物逐字节比较 |
| `diagnostics_independent.log`、`diagnostics_independent_manifest.json`、`diagnostics_independent_tests.log` | 独立checkout的真实诊断运行与5项专项反例测试 |
| `full_tests_diagnostics_user.json`、`full_tests_diagnostics_user.log` | 当前用户权限下344项完整回归通过，0失败、0错误、0跳过 |
| `full_tests_diagnostics.json`、`full_tests_diagnostics.log` | 此前沙箱权限导致的34项测试错误，保留失败，不能冒充通过 |
| `diagnostics_v1/`、`diagnostics_v1.log`、`diagnostics_v1_source.zip`、`diagnostics_tests.log` | 2032年SOC与替换库容冲突的首次停止证据、修复前快照；测试日志为最初4项快照 |
| `diagnostics_review_round1.json`、`diagnostics_reviewer_initial.py` | 第一轮初步检查及当时代码；不代替后续增强的最终检查 |
| `diagnostics_review_round1_complete.json`、`diagnostics_reviewer_typecheck_failure.py` | 审查器把数值0/0.0误判为不同类型的失败与修复前代码；已用数值等价判断修复 |
| `audit_diagnostics.json`、`key_scan_diagnostics.json`、`formal_inputs_diagnostics.json` | 本次原件审计、密钥扫描和原九子集准入核验 |

| 当前证据 | 用途 |
|---|---|
| `v5_validation_summary.json` | 当前运行、源代码、检查及C1—C9状态的总索引；C9不能由作者自查代替 |
| `complete_review_round1.json`、`complete_review_round2.json` | 当前完整模型的两轮账本审查；第二轮含独立目录的全量结果比较 |
| `full_tests_v5.json`、`full_tests_v5.log` | 339项测试，0失败、0错误、0跳过；Q3专项42项 |
| `audit_v5_final.json`、`key_scan_v5_final.json`、`formal_inputs_v5.json` | 交付文档完成后的原件审计与密钥扫描；原九子集准入核验 |
| `q1_regression_v5.log`、`q2_replay/replay_receipt.json` | Q1独立输出重跑、Q2原参数历史/规则回放；不冒称重做1012次校准搜索 |
| `full_campaign_v5.log`、`independent_v5_reproduction.log` | 两份完整Q3入口的实际执行日志 |
| `figures/policy_comparison.png`、`figures/plot_receipt.json`、`visual_review_v5.json` | 可追溯的独立绘图和实际图表审查；保留原运行散点图 |
| `delivery_inventory_v5.json` | 交付范围、文件体积和缓存排除检查 |

`validation_summary.json`、`final_tests.json`、`final_audit.json`、`stage_review.json`等未带V5的文件是早期首阶段记录，不能当成本次完整通过证明。`method_review_round1.json`、V3/V4日志、`stopped_run_provenance.json`和原代码备份记录真实失败及修复前版本，必须保留。`unchanged_numeric_protocols.json`确认V3—V5的66项数值设定没有为了得到正向结果而改变。

运行报告中的“待独立复现”是计算结束时的快照；当前独立复现状态见第二轮收据。所有作者检查仅覆盖文档声明的全国聚合条件研究，不自动扩展为全国真实预测、所有政策可行或团队批准。
