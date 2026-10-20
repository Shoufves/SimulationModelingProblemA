# PR15 review(10) 验证证据

本目录对应唯一 P2：跨运行浮点尾差不能被原文件哈希比较误拒绝；新合法 Q3 运行须能接续诊断。科学模型、输入和接受阈值仍为 V5。方法与范围见[修复说明](../../../../docs/solutions/p3-mmj-review10.md)。

最终代码全量回归为357项、0失败、0错误、0跳过；13项新增反例在作者目录和独立目录分别运行。`full_tests_round1*`、`targeted_round1*` 是首次实现快照，`full_tests_final_code*`、`targeted_round2_final*` 包含后来发现的协议快照字节修复。

| 证据 | 含义 |
|---|---|
| `validation_summary.json` | 本次最终状态、真实提交/来源身份、检查和证据哈希索引 |
| `frozen_scope_check.json` | 11份受保护原件、旧主模型/输入/产物/协议保留检查 |
| `ledger_round1.json`、`ledger_round2.json` | 原V5及新完整运行的账本检查；第二轮同时比较全部科学产物 |
| `independent_full_q3.json/.log` | 种子3515、干净独立checkout、真实完整Q3入口及退出码 |
| `independent_source_inventory.json`、`independent_source_delta/`、`independent_latest_attempt.json` | 独立运行完整原始字节的节省重复存储版本：403份复用原结果，3份保留实际变化；没有重写收据 |
| `restore_evidence_command.json/.log`、`restored_integrity.json` | 恢复脚本真实执行，405份输出及manifest与实际独立运行逐字节相同，`verify_latest()`通过 |
| `diagnostics_reference_final/`、`diagnostics_independent/` | 原来源及新来源的实际V3诊断，含来源等价证据、原SHA和代码/协议快照 |
| `diagnostics_round1_final.json`、`diagnostics_round2.json` | 两轮诊断审查；第二轮核验两次来源、账本及科学结果等价 |
| `full_tests_final_code_result.json`、`targeted_round2_final.json/.log` | 最终实现的全量测试与独立反例 |
| `environment_round2.json`、`audit_final*`、`key_scan_final*`、`formal_inputs_round1*` | 实际环境、原件审计、密钥格式扫描和原九子集准入 |

主计算实际运行于 `58a83c110c799318ba5b94bc7ac93323b2363c5d`；运行结束后，独立目录更新到 `301d43815b4152983ebac2e9fb1d5e7c5006e096`，验证按原字节保存协议的最终诊断实现。两提交间只改诊断快照保存、对应测试断言和说明，主计算的全部模型/输入SHA一致；不是在更改主模型后沿用旧结果。最终交付再增加证据及导航，提交身份与文件指纹须分开读取。

## 核验已存独立证据

从仓库根目录执行，使用未存在的输出/收据名称：

```powershell
python -B -X utf8 outputs/validation/p3_mmj/review10/restore_independent_source.py
python -B -X utf8 scripts/review_q3_diagnostics.py --source outputs/q3/p3_mmj_v5 --diagnostics outputs/validation/p3_mmj/review10/diagnostics_reference_final --independent outputs/validation/p3_mmj/review10/diagnostics_independent --independent-source outputs/q3/pr15_review10_restored --receipt outputs/validation/p3_mmj/review10_saved_evidence_recheck.json
```

恢复脚本先核对原V5 manifest、所有被复用原文件、差异文件和latest-attempt的SHA，然后逐字节恢复同一份独立运行。不生成新run ID，不构成新的仿真实验。要做新的完整复现，按修复说明运行 Q3→诊断，而非仅恢复文件。

## 保留的失败与边界

- `targeted_sandbox_failure.json`：首次Windows沙箱临时目录权限失败，未进入断言；后续在当前用户权限下执行同样测试。
- `diagnostics_reference/`、`diagnostics_round1.json`及对应命令日志：首次V3重算完成，但审查发现协议重新序列化改变换行，`Protocol receipt`失败。
- `protocol_snapshot_regression_before*`：新增真实收据断言后重现该失败。随后按原字节保存协议，另建 `diagnostics_reference_final/` 重新计算；没有改旧哈希冒充成功。
- `interim_roundoff_sample.json`仅是运行中的三个文件抽查，不代替后续完整比较。本机此次科学文件字节一致不证明所有环境必然一致；合法尾差、超界、项目/选择和篡改行为由新增反例单独检验。

原V1/V2/V5及其失败证据继续保留；本次没有重新执行未受影响的Q1/Q2完整计算或1012次校准搜索，357项回归包括其既有测试。作者复现不构成另外两人的正式批准，C9仍待团队评审最终SHA。
