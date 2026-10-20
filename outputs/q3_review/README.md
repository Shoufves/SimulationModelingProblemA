# P3/yx PR #13审查修复验收证据

此目录保存PR #13修复后的当前证据及下表明确标注的历史记录；最终门禁为`acceptance.json`。C1–C8仅覆盖Issue #12明确允许的条件研究范围，C9仍待两位成员对最终PR提交正式批准。原第10轮验收漏检了到龄退出，不能继续用其通过状态代替当前验收；原始证据已归档到`../../archive/q3_iterations/pr13_bf85908/`。逐项说明见[审查回应](../../docs/solutions/p3-pr13-review-response.md)。

| 证据 | 含义 |
|---|---|
| `ledger_checks.json`、`retirement_metrics_recomputed.csv` | 187条年度资产路径重建退出年，逐年及终值退休指标核对；两类L的实际工期、80组固定项目、公共预算、费用、连续库存/SOC及H02差分复算 |
| `retirement_probe.json` | 审查中的到龄反例与真正提前退出反例；修复前失败另存归档 |
| `pr13_change_comparison.json` | 与被评审完整SHA的187年度、118事件及全部科学表逐值比较；仅允许明确列出的分类修正与延迟说明 |
| `reproduction.json`、`reproduction_manifest.json` | 本次Python3.12/3.13、hashseed1313/2313、4/3进程两套完整Q3；数值比较数量与最大误差见JSON |
| `review13_primary.log`、`review13_reproduction.log`、`review13_pair_execution.json` | 本次两套完整入口日志与退出状态 |
| `round8.log`、`round9.log` | 原v3第8/9轮历史日志，不是本次执行 |
| `tests.json`、`tests.log` | 本次320项测试通过，0跳过；日志内故意拒绝坏输入的failed信息属于反例测试 |
| `workspace_audit.json`、`google_key_scan.json`、`formal_inputs.json` | 基础审计、密钥格式扫描、九个原正式准入子集检查。旧W阶段是历史局部状态，不代表新Q3完成度 |
| `protected_originals.json` | 官方PDF/四附件、只读三文档和原三份契约与共同base字节相同 |
| `q1_regression.json`、`q2_regression.json`及对应manifest | 原提交实际完成的独立目录回归；本次重新核对其18/29个科学产物，未重新运行Q1或训练Q2 |
| `review13_regression_scope.json` | 本次核验Q1的35项、Q2的17项代码/输入指纹未变，绑定历史回归manifest与产物比较收据；不是新训练凭据 |
| `findings.json` | 从最终CSV复算H01失败点、同条件规则比较、检验排序翻转和政策成本/排放差值 |
| `requirements-installed.txt`、`environment_install.log`、`dependency_check.log` | 原提交的Python3.12环境安装与检查历史；本次复用已安装环境 |

Q3科学结果在`../q3/p3_yx/`，压缩JSONL按约24MB分片；标准库gzip逐行读取即可。独立复现目录、虚拟环境和完整失败尝试留在本地ignored目录，不作为重复大文件提交。有效失败摘要及旧源码在`../../archive/q3_iterations/`。

## 复跑顺序

从仓库根目录创建Python环境并安装`requirements-q3.txt`，执行：

```powershell
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
python -B -X utf8 scripts/workflow_status.py --check-formal-inputs
python -B -X utf8 run.py q1 --output-dir outputs/q1/q3_yx_regression
python -B -X utf8 run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/q3_yx_regression
python -B -X utf8 scripts/review_q3_regressions.py --q2
python -B -X utf8 run.py q3 --config workflow/q3_inputs.json --output-dir outputs/q3/p3_yx
python -B -X utf8 scripts/review_q3_delivery.py
# 可另建同依赖的新Python环境，改变PYTHONHASHSEED，再执行完整入口
python -B -X utf8 run.py q3 --config workflow/q3_inputs.json --output-dir outputs/q3/p3_yx_reproduction
python -B -X utf8 scripts/compare_q3_runs.py
python -B -X utf8 scripts/probe_q3_retirement.py
python -B -X utf8 scripts/review_pr13_changes.py
python -B -X utf8 scripts/summarize_q3_evidence.py
```

再次汇总验收前，需把本次`outputs/validation/tests.json`、`workspace_audit.json`、`outputs/workflow/status.json`和扫描JSON复制到本目录相应证据文件，把新的独立Q3运行manifest复制为`reproduction_manifest.json`；然后执行`python -B -X utf8 scripts/accept_q3_delivery.py`。汇总器核对Q3代码、配置、产物、账本检查器和复现收据指纹；基础门禁日志仍须由复跑者保留并复核。代码在共同base上带未提交修改执行，manifest如实记dirty；科学代码哈希绑定后续提交内容，最终提交SHA以PR为准。

上方列出从头完整重建的命令。本次PR13修复实际采用范围限定复验：省略Q1/Q2运行两行，运行 `scripts/review_q3_regressions.py --q2` 重新检查历史产物，再执行 `scripts/review_pr13_regression_scope.py` 核对被评审SHA中历史回归的代码、输入及产物身份。该作用域凭据只适用于本次Q1/Q2依赖均未变化的修复，不能用于跳过变更后的回归。`review_pr13_changes.py`需要本地存在被评审提交 `bf8590809004466d2f595407eb61ddd2b6b7e5a2`；完整原结果从Git提取到ignored的tmp目录，不能自行重造参考值。

提前退役采用实际退出年严格小于自然退出年的定义；新增 `managed_natural_retired_mw` 只表示受Q3计划管理的到龄退出，不是全国全部自然退出。两类H01的 `delay_target` 是不同干预的标签，不能直接把相同L解释为相同建设延迟。

本批次156/160个H01点越界，H02缺供交互为0，滚动方法在检验点出现排序翻转。上述结果未被删除，也没有靠放宽门槛、增加冲击或重选检验集制造创新收益。五方面建议和条件限制见`../../docs/solutions/p3-yx.md`。
