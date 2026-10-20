# P3/yx 第10轮本地验收证据

此目录保存本轮实际执行的证据；最终门禁为`acceptance.json`。C1–C8仅覆盖Issue #12明确允许的条件研究范围，C9仍待两位成员对最终PR提交正式批准。原Q1/Q2验收文件保持交接字节，新的执行记录放在本目录。

| 证据 | 含义 |
|---|---|
| `ledger_checks.json` | 全部年度路径、80组固定项目集合、公共预算、资金与资源费用、期末已付资产、连续库存/SOC及分服务H02差分复算 |
| `reproduction.json`、`reproduction_manifest.json` | Python3.12/3.13、不同哈希种子和独立目录全量运行；187条年度与118个事件，26,659,130个数值比较 |
| `round8.log`、`round9.log` | 两次完整入口真实执行日志；没有用旧输出代替 |
| `tests.json`、`tests.log` | 最终模型315项测试通过，0跳过；日志内故意拒绝坏输入的failed信息属于反例测试 |
| `workspace_audit.json`、`google_key_scan.json`、`formal_inputs.json` | 基础审计、密钥格式扫描、九个原正式准入子集检查。旧W阶段是历史局部状态，不代表新Q3完成度 |
| `protected_originals.json` | 官方PDF/四附件、只读三文档和原三份契约与共同base字节相同 |
| `q1_regression.json`、`q2_regression.json`及对应manifest | 当前代码独立目录实际回归；Q1逐字节，Q2按冻结数值容差及分离的代码快照身份核对 |
| `findings.json` | 从最终CSV复算H01失败点、同条件规则比较、检验排序翻转和政策成本/排放差值 |
| `requirements-installed.txt`、`environment_install.log`、`dependency_check.log` | 干净Python3.12环境实装记录与依赖一致性检查 |

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
python -B -X utf8 scripts/summarize_q3_evidence.py
```

再次汇总验收前，需把本次`outputs/validation/tests.json`、`workspace_audit.json`、`outputs/workflow/status.json`和扫描JSON复制到本目录相应证据文件，把新的独立Q3运行manifest复制为`reproduction_manifest.json`；然后执行`python -B -X utf8 scripts/accept_q3_delivery.py`。汇总器核对Q3代码、配置、产物、账本检查器和复现收据指纹；基础门禁日志仍须由复跑者保留并复核。代码在共同base上带未提交修改执行，manifest如实记dirty；科学代码哈希绑定后续提交内容，最终提交SHA以PR为准。

本批次156/160个H01点越界，H02缺供交互为0，滚动方法在检验点出现排序翻转。上述结果未被删除，也没有靠放宽门槛、增加冲击或重选检验集制造创新收益。五方面建议和条件限制见`../../docs/solutions/p3-yx.md`。
