# PR15 review(10)：跨运行数值等价与诊断接续

本次只修复 C8 的复现验收链。评审指出完整 Q3 在另一运行中可出现合法浮点尾差，而旧审查器按详细文件 SHA 拒绝，诊断入口和诊断独立比较也有同类问题。主模型、输入、政策与科学接受阈值不变；无可行政策、H02 为零及原有解释边界不变。

## 修复规则

- 每份 Q3 仍先执行 `verify_latest()`：最新尝试、manifest 原 SHA、当前模型/输入和用途准入、全部输出原 SHA 均须通过；另核对实际文件集合。跨运行等价不能修补单次运行损坏。
- [共同比较器](../../scripts/q3_scientific_equivalence.py)解码 CSV、JSON 和 gzip JSON。沿用 V5 `numerical` 与原 CSV 比较器的相对 `1e-10`、绝对 `1e-6`、含 `cny` 字段绝对 `0.01`。数值比较不是政策/服务验收，原 1% 服务门槛未变。
- JSON 类型、整数、布尔、字符串、键和列表顺序严格核对；项目身份/技术/审批投运退出年份/状态、政策选择及阈值严格核对。嵌入 SHA 不跳过。连续容量、费用等按上述数值界比较，变化超过界仍拒绝。CSV 按位置逐列比较，重复列名也全部核对。
- 科学比较包含原科学 CSV、案例、事件、项目计划、选择锁、初态和继承配置，并补充参数、政策权衡、完成状态与失败列表。运行收据、耗时、日志、代码快照、图像、文字报告及 gaps 不参与科学数值等价；它们仍由各次运行原 SHA 验证。
- [诊断 V3](../../workflow/q3_diagnostics_v3.json)原样继承 V2 的模型、输入、源文件哈希及诊断干预。[复现协议](../../workflow/q3_reproduction_v1.json)固定原 V5 manifest 身份。新 source 必须相对这份固定原结果通过全量等价，不能将新 source 哈希替换进旧协议。
- 新诊断保存 `source_equivalence.json`：两份真实 run ID、manifest/latest-attempt SHA、模型/输入/全部原输出哈希、逐文件比较证据、差异数和样例；另保存比较器及协议快照。诊断审查会重算来源等价并核对收据；独立诊断的全部科学产物也采用同一容差。

## 复现命令

从当前提交建立独立 checkout，在其根目录配置 Python 3.12 和已锁定依赖。使用从未用过的输出名：

```powershell
$env:PYTHONHASHSEED='3515'
python -B -X utf8 run.py q3 --config workflow/q3_inputs_v5.json --output-dir outputs/q3/pr15_review10
python -B -X utf8 scripts/review_q3_complete.py --output-dir outputs/q3/pr15_review10 --evidence outputs/validation/p3_mmj/review10_ledger.json
python -B -X utf8 scripts/diagnose_q3_mechanisms.py --source outputs/q3/pr15_review10 --output-dir outputs/validation/p3_mmj/review10_diagnostics
python -B -X utf8 scripts/review_q3_diagnostics.py --source outputs/q3/pr15_review10 --diagnostics outputs/validation/p3_mmj/review10_diagnostics --receipt outputs/validation/p3_mmj/review10_diagnostics_review.json
```

诊断入口会自动相对该 checkout 内原 V5 冻结结果完成科学等价检查。`review_q3_complete.py` 的 `--reproduction-root` 可比较另一个 checkout；已有输出用 `--existing-reproduction --reproduction-output outputs/q3/pr15_review10` 指定。审查器不再把已有运行种子硬写成 1729，实际种子须见启动收据。

诊断跨目录比较使用 `--independent <独立诊断目录> --independent-source <对应Q3目录>`，两份诊断都须先通过自身来源/原 SHA/完整账本检查；来源 run ID 不能相同。

## 自查记录

新增反例覆盖合法现金尾差接入诊断、超容差拒绝、项目/选择/极小阈值变化拒绝、JSON 类型与哈希严格比较、重复 CSV 列、数值边界、损坏字节、旧成功失效、代码指纹变化及诊断收据篡改。小夹具只用于反例，不能代替完整 Q3 复现。

实际诊断自查另发现协议重新序列化会因换行格式变化导致快照 SHA 失配；已改为保存原字节，并使“合法尾差接入”测试继续核验真实诊断收据。修复前运行、审查失败及反例重现日志均保留，不刷新旧运行的协议哈希。

本文件随实现先提交；实际两轮执行证据另存 `outputs/validation/p3_mmj/review10/`，完成后补充真实结果。保留旧 V1/V2/V5 运行及失败证据。作者自查不构成 C9，仍需另外两人评审同一最终 SHA。
