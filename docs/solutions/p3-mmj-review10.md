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

两轮自查已完成，完整证据与恢复方法见[本轮索引](../../outputs/validation/p3_mmj/review10/README.md)，汇总见[验证收据](../../outputs/validation/p3_mmj/review10/validation_summary.json)。

| 实际检查 | 结果 |
|---|---|
| 最终代码全量回归 | 357项通过，0失败、0错误、0跳过；包含新增13项反例，不能再将13项重复相加 |
| 两目录反例 | 作者目录、独立checkout均通过；合法尾差能通过诊断入口及真实收据检查，越界、项目/选择变化和篡改被拒绝 |
| 独立完整Q3 | Python 3.12.14、种子3515；116例全部完成，0意外失败，入口退出0；2179.63秒 |
| 新运行完整账本与跨运行比较 | 394份科学产物通过，20,367,422个数值叶；JSON整数及CSV离散身份严格比较。该计数不将CSV离散数字字符串当连续数值 |
| 新source接续诊断 | run ID `20261020T043342453606Z`；4对进口控制、38次探针、71次年度控制完成，1项不可构造保留；入口退出0，含准入比较202.44秒 |
| 两轮诊断审查 | 来源收据、原SHA、全部诊断账本通过；两次诊断14份科学产物比较通过 |
| 原始字节恢复 | 403份复用原结果、3份差异文件；实际恢复后405份输出及manifest与独立原运行逐字节相同，`verify_latest()`通过 |

本机此次394份科学产物及14份诊断科学产物均逐字节一致，没有复现评审机器上的浮点尾差，也不据种子推断尾差原因。新增小夹具使用评审报告中的两类现金数值差异验证合法尾差准入，并验证实质变化仍被拒绝；真实完整计算链另由上表记录，二者不混同。

完整Q3执行于 `58a83c110c799318ba5b94bc7ac93323b2363c5d`。随后在 `301d43815b4152983ebac2e9fb1d5e7c5006e096` 修复协议快照字节并执行最终诊断与检查；两提交间主计算模型/输入SHA全部相同，未修改主模型后复用旧计算。最终提交另外补充证据和导航，原主运行与旧 V1/V2/V5 失败证据全部保留。作者自查不构成 C9，仍需另外两人评审同一最终 SHA。
